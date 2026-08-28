"""Durable checkpoints — state that survives the process exiting.

``InMemorySaver`` loses everything when the program ends. For the eval runners
that is fine: they start, run, print, and stop. For a person it is not, because
this pipeline can STOP AND ASK THEM A QUESTION, and until now closing the
terminal at that prompt threw away the run and every API call it had paid for.

WHAT A SAVED RUN CAN LOOK LIKE

Four states, and they need different treatment, which is why ``SavedRun``
exists rather than a bare thread id:

``paused``    The graph interrupted to ask the user something and is waiting
              on the answer. Resume by supplying it.
``stopped``   The process died partway through a stage — Ctrl-C during the
              three-minute research call, a closed laptop, a crash. Resume by
              supplying nothing; the graph picks up at the stage that had not
              finished and does NOT repeat the ones that had.
``finished``  It ran to the end. There is a decision to read and nothing to
              resume.
``failed``    It reached the end because a node caught its own exception and
              recorded it rather than letting a traceback out. Shaped exactly
              like ``finished`` - nothing pending - so it was reported as
              finished until 2026-08-28. Not resumable today; the work already
              paid for is stranded. See section 2.10.

That ``stopped`` runs resume mid-pipeline is the part worth knowing. A run
killed during Agent 4 keeps Agents 1, 2 and 3's work, which on this project's
quota is the difference between losing a minute and losing a day's budget.

WHY THE CONNECTION IS MANAGED HERE

``SqliteSaver.from_conn_string`` is the documented entry point and it does not
accept ``serde=``. So the connection is opened here and handed to
``SqliteSaver`` directly, which is the only way to pass the project's
serializer.

That matters more than it first appears, and not for the obvious reason.
Passing ``allowed_msgpack_modules`` OPTS INTO a strict allowlist: a type not on
the list is refused and comes back as a plain dict, which is exactly what
happened to Agents 4 and 5 last session. Omitting the serializer entirely does
NOT reproduce that — it falls back to LangGraph's permissive default, which
reconstructs anything and merely warns:

    "Deserializing unregistered type ... This will be blocked in a future
    version."

So dropping ``serde=`` would look fine today and fail everywhere at once when
that future version lands, having silently discarded the guarantee
CHECKPOINTED_TYPES exists to provide in the meantime. A round-trip test cannot
catch it while the default is still permissive, so test_checkpoints.py asserts
the serializer's IDENTITY instead.
"""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from langgraph.checkpoint.sqlite import SqliteSaver

from config import PROJECT_ROOT
from workflow import build_graph, serializer

DB_PATH = PROJECT_ROOT / ".state" / "checkpoints.sqlite"
"""Where saved runs live.

Deliberately NOT under ``.cache/``. That directory is documented as holding
re-fetchable API responses and is safe to delete to force fresh data — and a
person halfway through a clarification is neither re-fetchable nor safe to
delete. Sooner or later somebody clears the cache; they should not lose a live
session by doing it.
"""

RunStatus = Literal["paused", "stopped", "finished", "failed"]


@dataclass(frozen=True)
class SavedRun:
    """One thread in the checkpoint database, described well enough to choose."""

    thread_id: str
    status: RunStatus
    question: dict | None
    """The pending interrupt payload, when the run is ``paused``.

    Carried so the CLI can re-ask the ORIGINAL question after a restart. Asking
    "please clarify" without repeating what conflicted would be useless to
    somebody coming back to this tomorrow.
    """
    sectors: list[str]
    """What the run was researching. The only thing that makes a list of thread
    ids identifiable as belonging to a person rather than a machine."""
    updated_at: str | None

    @property
    def can_resume(self) -> bool:
        """Whether ``--resume`` can carry this run forward.

        Written as a list of what CAN resume rather than "not finished".
        ``failed`` is also finished in the graph's terms - nothing is pending -
        so the old test would have started calling it resumable the moment the
        status existed, and offered a resume that cannot work.
        """
        return self.status in ("paused", "stopped")


class CheckpointStore:
    """A compiled graph plus the ability to see what is already saved in it."""

    def __init__(self, graph, saver: SqliteSaver) -> None:
        self.graph = graph
        self._saver = saver

    @staticmethod
    def config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    def run(self, thread_id: str) -> SavedRun | None:
        """Describe one saved run, or None if that thread does not exist.

        Returning None rather than an empty run matters: a mistyped id must be
        reportable as "no such run" instead of quietly starting a fresh one,
        which is the whole reason resuming is an explicit flag.
        """
        snapshot = self.graph.get_state(self.config(thread_id))

        # An unknown thread yields a snapshot with empty values and no
        # timestamp rather than raising, so the timestamp is the existence test.
        if snapshot.created_at is None:
            return None

        interrupts = [i for task in snapshot.tasks for i in task.interrupts]
        if not snapshot.next:
            # A node that caught its own exception records it and lets the graph
            # END, deliberately, so no traceback reaches a user. That makes a
            # failed run indistinguishable from a successful one by shape alone
            # - both simply have nothing left to do - and it was being listed as
            # "finished". The error is already in state; this reads it.
            status: RunStatus = "failed" if snapshot.values.get("error") else "finished"
        elif interrupts:
            status = "paused"
        else:
            status = "stopped"

        user_input = snapshot.values.get("user_input")
        return SavedRun(
            thread_id=thread_id,
            status=status,
            question=interrupts[0].value if interrupts else None,
            sectors=list(getattr(user_input, "sectors_of_interest", []) or []),
            updated_at=snapshot.created_at,
        )

    def saved_runs(self) -> list[SavedRun]:
        """Every saved run, most recently written first.

        ``list()`` walks checkpoints, not threads, and a single run writes one
        per step — so the thread ids are collected in the order they first
        appear and then described once each.
        """
        thread_ids: list[str] = []
        for checkpoint in self._saver.list(None):
            thread_id = checkpoint.config["configurable"]["thread_id"]
            if thread_id not in thread_ids:
                thread_ids.append(thread_id)

        runs = (self.run(thread_id) for thread_id in thread_ids)
        return [run for run in runs if run is not None]


@contextmanager
def open_store(db_path: Path | str | None = None):
    """Open the checkpoint database and yield a store over it.

    A context manager because the SQLite connection has to be closed, and
    because the alternative — a module-level connection — would open and create
    the database file merely on import, including in every test run.
    """
    path = Path(db_path) if db_path is not None else DB_PATH
    # ":memory:" is a valid SQLite target with no directory to create.
    if path.name != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)

    # check_same_thread=False because LangGraph may touch the connection from a
    # worker thread. Every documented LangGraph example connects the same way.
    connection = sqlite3.connect(str(path), check_same_thread=False)
    try:
        saver = SqliteSaver(connection, serde=serializer)
        yield CheckpointStore(build_graph(saver), saver)
    finally:
        connection.close()
