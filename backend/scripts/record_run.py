"""Turn a finished run into a recording the gallery can replay.

    python -m backend.scripts.record_run web-72bcb175 --to demo/gallery/technology.json
    python -m backend.scripts.record_run --list

WHY A RECORDING RATHER THAN THE CHECKPOINT

The checkpoint database is where runs live, and it is deliberately NOT in the
repository: ``.state/`` holds work a person has not finished, and it is
machine-local. So a visitor to a deployed site, or anybody who clones this,
would see exactly one run - the committed demo - and nothing else, however many
have been made here.

A recording is the same state written to a file the repository can carry. It is
loaded back through the same Pydantic models the graph writes, so a schema
change breaks a test rather than the front page. That is the property that makes
this a recording and not a fixture: a hand-written example could say anything,
and would rot silently the first time a model gained a required field.

WHAT IT REFUSES TO DO

A run that did not finish. A run that failed. And any run whose state does not
round-trip through the models cleanly. The gallery shows real, complete runs;
"interrupted" and "failed" are worth showing too, but they are a different thing
with a different shape, and pretending an incomplete run is a brief would be the
one kind of dishonesty this project has never committed.

It also never edits. Whatever the person typed is what the recording carries -
the shipped demo still holds ``restrictions: ["no"]`` because that is what its
investor wrote, and a test asserts both that the file still says it and that
loading it yields an empty list. Editing a saved run into saying something
nicer would make every other recording unciteable.
"""

import argparse
import json
from pathlib import Path

from backend import checkpoints
from backend.models.decision import Decision
from backend.models.research import ResearchFindings
from backend.models.risk import RiskFindings
from backend.models.user_input import UserInput

REQUIRED = ("user_input", "decision", "research_findings", "risk_findings")
"""What a recording needs, and what --demo reads back.

``company_findings`` is deliberately absent: the brief a reader sees is built
from the decision plus the two article stores, and the demo has never carried
the candidate list. Adding it would put a second, larger copy of the same
companies in every file for nothing anybody reads.
"""


class NotRecordable(Exception):
    """The run exists and is not a finished brief."""


def build(values: dict, recorded_on: str | None = None) -> dict:
    """The recording for one run's state.

    ``mode="json"`` throughout, because the state carries datetimes - article
    dates, a price's as_of - and the default dump leaves objects that ``json``
    then refuses. That failure would land after the run was already paid for.
    """
    missing = [key for key in REQUIRED if values.get(key) is None]
    if missing:
        raise NotRecordable(f"state is missing {', '.join(missing)}")
    if values.get("error"):
        raise NotRecordable(f"the run failed: {values['error']}")

    payload = {}
    if recorded_on:
        # WHEN THE RUN HAPPENED, not when the file was written. Share prices in
        # a brief are from a moment, and a reader arriving at an old recording
        # needs to know that before they read a number rather than after.
        payload["recorded_on"] = recorded_on

    return {
        **payload,
        "profile": values["user_input"].model_dump(mode="json"),
        "decision": values["decision"].model_dump(mode="json"),
        "research_findings": values["research_findings"].model_dump(mode="json"),
        "risk_findings": values["risk_findings"].model_dump(mode="json"),
    }


def verify(payload: dict) -> None:
    """Load the recording back through the models before writing it.

    The same check ``--demo`` performs at read time, done here so a broken
    recording is never written rather than being discovered by a visitor. It is
    also what makes the round trip real: if these models stop accepting what the
    graph produced, this raises here instead of the front page going quiet.
    """
    UserInput.model_validate(payload["profile"])
    Decision.model_validate(payload["decision"])
    ResearchFindings.model_validate(payload["research_findings"])
    RiskFindings.model_validate(payload["risk_findings"])


def record(thread_id: str, destination: Path, db_path=None) -> dict:
    """Write one run to a recording file. Returns a short description of it."""
    with checkpoints.open_store(db_path) as store:
        saved = store.run(thread_id)
        if saved is None:
            raise NotRecordable(f"no run called {thread_id!r}")
        if saved.status != "finished":
            raise NotRecordable(
                f"{thread_id} is {saved.status}, and only a finished run is a brief"
            )
        values = store.graph.get_state(store.config(thread_id)).values

    payload = build(values, recorded_on=saved.updated_at)
    verify(payload)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    decision = values["decision"]
    return {
        "thread_id": thread_id,
        "path": str(destination),
        "sectors": values["user_input"].sectors_of_interest,
        "recommendations": [r.ticker for r in decision.recommendations],
        "recommended_nothing": decision.recommended_nothing,
        "bytes": destination.stat().st_size,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.scripts.record_run",
        description="Write a finished run to a recording the gallery can replay.",
    )
    parser.add_argument("thread_id", nargs="?", help="The run to record.")
    parser.add_argument("--to", type=Path, help="Where to write it.")
    parser.add_argument(
        "--list", action="store_true", dest="list_runs",
        help="Show the finished runs that could be recorded.",
    )
    parser.add_argument("--db", type=Path, help="Checkpoint database to read.")
    args = parser.parse_args(argv)

    if args.list_runs:
        with checkpoints.open_store(args.db) as store:
            for run in store.saved_runs():
                if run.status != "finished":
                    continue
                print(f"  {run.thread_id:16} {', '.join(run.sectors) or '-'}")
        return 0

    if not args.thread_id or not args.to:
        parser.error("give a run id and --to, or use --list")

    try:
        made = record(args.thread_id, args.to, args.db)
    except NotRecordable as exc:
        print(f"Not recorded: {exc}")
        return 1

    what = (
        "recommends nothing"
        if made["recommended_nothing"]
        else ", ".join(made["recommendations"])
    )
    print(f"Recorded {made['thread_id']} -> {made['path']} ({made['bytes']:,} bytes)")
    print(f"  sectors: {', '.join(made['sectors'])}")
    print(f"  result : {what}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
