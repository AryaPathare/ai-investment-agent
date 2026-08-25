"""Tests for durable checkpoints.

The claim being tested is narrow and important: **a run that stops can be
picked up again, in a different process, with nothing lost.** Everything here
exists to hold one part of that up.

The awkward part is that "a different process" is the whole point, and a test
runs in one process. So the store is opened, closed, and opened again against
the same file — which is what actually exercises serialization, because a
second `open_store` shares no Python objects with the first. Anything that
survives that round trip came out of SQLite, not out of memory.

No network, no model. The agents are stubbed exactly as in test_cli.py.
"""

import sqlite3

import pytest

import checkpoints
import workflow
from models.companies import CompanyFindings
from models.decision import Decision
from models.profile import InvestorProfile
from models.research import ResearchFindings
from models.risk import RiskFindings
from models.user_input import UserInput
from tests.conftest import DEFAULT_DB_PATH


@pytest.fixture
def db(tmp_path):
    return tmp_path / "runs.sqlite"


def _user(sectors=("renewable energy",)) -> UserInput:
    return UserInput(
        age=30,
        investment_experience="beginner",
        risk_tolerance="low",
        investment_amount=1000.0,
        investment_window="within 6 months",
        holding_period="5 years",
        sectors_of_interest=list(sectors),
        restrictions=[],
    )


@pytest.fixture
def agents(monkeypatch):
    """Stub Agents 1 to 5. ``blocks`` decides whether Agent 1 asks a question."""

    def _install(blocks=False, research=None):
        def profile(user_input, clarifications=None):
            if blocks and not clarifications:
                return InvestorProfile(
                    **user_input.model_dump(),
                    status="needs_clarification",
                    clarification_reason="wants technology but ruled technology out",
                )
            return InvestorProfile(**user_input.model_dump(), status="valid")

        monkeypatch.setattr(workflow, "create_investor_profile", profile)
        monkeypatch.setattr(
            workflow, "research_themes",
            research or (lambda p, **k: ResearchFindings(articles_retrieved=7)),
        )
        monkeypatch.setattr(
            workflow, "analyse_companies",
            lambda r, **k: CompanyFindings(companies_examined=4),
        )
        monkeypatch.setattr(workflow, "critique_companies", lambda f, **k: RiskFindings())
        monkeypatch.setattr(
            workflow, "decide",
            lambda c, r, p, research=None: Decision(
                no_recommendation_reason="nothing cleared the bar"
            ),
        )

    return _install


# --- The file itself ---------------------------------------------------------


def test_importing_the_module_creates_no_database():
    """Import must not touch the filesystem.

    A module-level connection would create the database merely because
    something imported it - including every test run and every `python -c`.
    Checked in a subprocess because this process imported the module long ago;
    skipped when a real run has already created the file, since then the
    question cannot be answered by looking.
    """
    import subprocess
    import sys

    from config import PROJECT_ROOT

    if DEFAULT_DB_PATH.exists():
        pytest.skip("a real run has already created the database")

    subprocess.run(
        [sys.executable, "-c", "import cli, checkpoints"],
        cwd=PROJECT_ROOT,
        check=True,
    )
    assert not DEFAULT_DB_PATH.exists()


def test_opening_the_store_creates_the_directory(tmp_path, agents):
    agents()
    nested = tmp_path / "deep" / "down" / "runs.sqlite"
    with checkpoints.open_store(nested):
        pass
    assert nested.exists()


def test_the_default_lives_outside_the_cache():
    """`.cache/` is documented as safe to delete to force fresh API data. A
    paused clarification is neither re-fetchable nor safe to delete, so it must
    not sit under a path people are told they can clear."""
    parts = DEFAULT_DB_PATH.parts
    assert ".cache" not in parts
    assert ".state" in parts


def test_the_connection_is_closed_even_when_the_body_raises(db, agents):
    agents()
    with pytest.raises(RuntimeError):
        with checkpoints.open_store(db):
            raise RuntimeError("boom")

    # A leaked connection would hold a lock; reopening proves it did not.
    with checkpoints.open_store(db) as store:
        assert store.saved_runs() == []


# --- Surviving the process ---------------------------------------------------


def test_a_paused_run_survives_being_closed_and_reopened(db, agents):
    """THE test for this file. Close the store, open a new one on the same
    file, and the run is still there waiting."""
    agents(blocks=True)

    with checkpoints.open_store(db) as store:
        store.graph.invoke({"user_input": _user()}, store.config("t1"))

    with checkpoints.open_store(db) as store:
        saved = store.run("t1")

    assert saved is not None
    assert saved.status == "paused"
    assert saved.question["reason"].startswith("wants technology")
    assert saved.sectors == ["renewable energy"]


def test_a_reopened_run_can_actually_be_finished(db, agents):
    """Surviving is not enough - it has to be resumable to the end."""
    from langgraph.types import Command

    agents(blocks=True)
    with checkpoints.open_store(db) as store:
        store.graph.invoke({"user_input": _user()}, store.config("t1"))

    with checkpoints.open_store(db) as store:
        result = store.graph.invoke(Command(resume="drop technology"), store.config("t1"))
        assert store.run("t1").status == "finished"

    assert result["clarification_responses"] == ["drop technology"]
    assert result["decision"].recommended_nothing


def test_the_store_uses_the_projects_serializer(db):
    """The guarantee CHECKPOINTED_TYPES provides is only in force while the
    project's serializer is the one actually being used.

    Checked by identity rather than by round-tripping an object, because a
    round trip cannot currently tell the two apart: passing
    allowed_msgpack_modules opts INTO a strict allowlist, while passing no
    serializer at all falls back to LangGraph's permissive default, which
    reconstructs everything and only warns that it will stop doing so. Dropping
    serde= therefore looks harmless today and breaks everything at once later.
    This assertion is what notices.
    """
    with checkpoints.open_store(db) as store:
        assert store._saver.serde is workflow.serializer


def test_types_come_back_as_objects_not_dicts(db, agents):
    """The end-to-end version: through SQLite, out of a second store, still an
    object with working properties."""
    agents(blocks=True)
    with checkpoints.open_store(db) as store:
        store.graph.invoke({"user_input": _user()}, store.config("t1"))

    with checkpoints.open_store(db) as store:
        values = store.graph.get_state(store.config("t1")).values

    assert isinstance(values["user_input"], UserInput)
    assert isinstance(values["investor_profile"], InvestorProfile)
    # A property is what a dict cannot answer, and what the CLI reads first.
    assert values["investor_profile"].needs_clarification is True


def test_a_finished_run_carries_its_decision_back(db, agents):
    agents()
    with checkpoints.open_store(db) as store:
        store.graph.invoke({"user_input": _user()}, store.config("t1"))

    with checkpoints.open_store(db) as store:
        values = store.graph.get_state(store.config("t1")).values

    assert isinstance(values["decision"], Decision)
    assert values["decision"].recommended_nothing


# --- Describing what is saved ------------------------------------------------


def test_an_unknown_thread_is_None_not_an_empty_run(db, agents):
    """A mistyped id must be reportable as "no such run". Returning a blank run
    would let the CLI quietly start a fresh one under the typo."""
    agents()
    with checkpoints.open_store(db) as store:
        assert store.run("never-existed") is None


def test_a_finished_run_reports_finished_and_cannot_resume(db, agents):
    agents()
    with checkpoints.open_store(db) as store:
        store.graph.invoke({"user_input": _user()}, store.config("done"))
        saved = store.run("done")

    assert saved.status == "finished"
    assert saved.can_resume is False
    assert saved.question is None


def test_a_run_killed_mid_stage_reports_stopped_and_can_resume(db, agents):
    """Ctrl-C during the three-minute research call. Not a clarification, so
    there is no question to re-ask - but the run is not finished either, and
    calling that "finished" would throw away completed work."""

    def killed(profile, **kwargs):
        # BaseException, so research_node's `except Exception` does not turn it
        # into a recorded error the way a real failure would.
        raise KeyboardInterrupt("user pressed Ctrl-C")

    agents(research=killed)
    with checkpoints.open_store(db) as store:
        with pytest.raises(KeyboardInterrupt):
            store.graph.invoke({"user_input": _user()}, store.config("killed"))

    with checkpoints.open_store(db) as store:
        saved = store.run("killed")

    assert saved.status == "stopped"
    assert saved.question is None
    assert saved.can_resume is True


def test_a_stopped_run_resumes_without_repeating_finished_stages(db, agents):
    """The property that makes stopping cheap. Agent 1 already ran and cost a
    model call; resuming must not spend it again."""
    calls = []

    def counted_profile(user_input, clarifications=None):
        calls.append(1)
        return InvestorProfile(**user_input.model_dump(), status="valid")

    def killed(profile, **kwargs):
        raise KeyboardInterrupt("user pressed Ctrl-C")

    agents(research=killed)
    import workflow as wf

    wf.create_investor_profile = counted_profile
    with checkpoints.open_store(db) as store:
        with pytest.raises(KeyboardInterrupt):
            store.graph.invoke({"user_input": _user()}, store.config("killed"))
    assert len(calls) == 1

    agents()  # research works this time
    wf.create_investor_profile = counted_profile
    with checkpoints.open_store(db) as store:
        # Sending nothing means "carry on from the unfinished node".
        result = store.graph.invoke(None, store.config("killed"))

    assert len(calls) == 1, "Agent 1 must not run a second time"
    assert result["research_findings"].articles_retrieved == 7
    assert isinstance(result["decision"], Decision)


# --- Listing ------------------------------------------------------------------


def test_saved_runs_lists_every_thread_once(db, agents):
    """One run writes a checkpoint per step, so the ids must be deduplicated."""
    agents()
    with checkpoints.open_store(db) as store:
        for thread_id in ("a", "b", "c"):
            store.graph.invoke({"user_input": _user()}, store.config(thread_id))
        runs = store.saved_runs()

    assert sorted(r.thread_id for r in runs) == ["a", "b", "c"]


def test_saved_runs_is_most_recent_first(db, agents):
    agents()
    with checkpoints.open_store(db) as store:
        for thread_id in ("oldest", "middle", "newest"):
            store.graph.invoke({"user_input": _user()}, store.config(thread_id))
        assert [r.thread_id for r in store.saved_runs()] == [
            "newest",
            "middle",
            "oldest",
        ]


def test_saved_runs_records_what_each_was_researching(db, agents):
    """A list of bare thread ids is unusable. The sectors are what make a row
    recognisable as the run you were in the middle of."""
    agents()
    with checkpoints.open_store(db) as store:
        store.graph.invoke({"user_input": _user(["banking"])}, store.config("a"))
        store.graph.invoke({"user_input": _user(["semiconductors"])}, store.config("b"))
        found = {r.thread_id: r.sectors for r in store.saved_runs()}

    assert found == {"a": ["banking"], "b": ["semiconductors"]}


def test_an_empty_database_lists_nothing_rather_than_failing(db):
    with checkpoints.open_store(db) as store:
        assert store.saved_runs() == []


def test_the_store_can_be_pointed_at_an_in_memory_database(agents):
    """":memory:" has no parent directory to create, and the code must not try."""
    agents()
    with checkpoints.open_store(":memory:") as store:
        store.graph.invoke({"user_input": _user()}, store.config("t1"))
        assert store.run("t1").status == "finished"


def test_the_database_is_a_real_sqlite_file(db, agents):
    """Cheap, but it is the difference between "persisted" and "believed to be
    persisted" - the file has to exist with tables in it."""
    agents()
    with checkpoints.open_store(db) as store:
        store.graph.invoke({"user_input": _user()}, store.config("t1"))

    connection = sqlite3.connect(db)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        connection.close()

    assert "checkpoints" in tables
