"""Tests for the recordings the gallery replays, and the tool that writes them.

Two different jobs here, and the second is the one that matters most.

The TOOL is ordinary code and is tested as such: it refuses what it cannot
honestly record, and it verifies before it writes.

The RECORDINGS are the reason ``demo/`` exists at all. A hand-written example
could say anything and would rot silently the first time a model gained a
required field - the front page would keep printing until somebody read it
closely. These load every committed recording back through the same Pydantic
models the graph writes, so a schema change goes red here instead.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from backend import cli
from backend.config import PROJECT_ROOT
from backend.models.decision import Decision
from backend.models.research import ResearchFindings
from backend.models.risk import RiskFindings
from backend.models.user_input import UserInput
from backend.scripts.record_run import NotRecordable, build, record, verify

GALLERY = PROJECT_ROOT / "shared" / "gallery"


def recordings() -> list[Path]:
    return sorted(GALLERY.glob("*.json"))


def test_there_are_recordings_to_test():
    """A directory-walking test over an empty directory passes while proving
    nothing. This is the guard on the guard - the same reason the log-render
    check counts entries rather than only diffing."""
    assert recordings(), "demo/gallery holds no recordings"


@pytest.mark.parametrize("path", recordings(), ids=lambda p: p.stem)
def test_every_recording_loads_through_the_models_that_wrote_it(path):
    """The property that makes these recordings rather than fixtures."""
    payload = json.loads(path.read_text(encoding="utf-8"))

    UserInput.model_validate(payload["profile"])
    Decision.model_validate(payload["decision"])
    ResearchFindings.model_validate(payload["research_findings"])
    RiskFindings.model_validate(payload["risk_findings"])


@pytest.mark.parametrize("path", recordings(), ids=lambda p: p.stem)
def test_every_recording_renders_a_brief(path, capsys):
    """Loading is not the same as being readable. A recording that parses and
    then prints nothing would be a blank page nobody notices until a visitor
    arrives."""
    assert cli.run_demo(path) == 0
    out = capsys.readouterr().out

    assert "This is research, not advice" in out
    assert "WORTH A LOOK" in out or "NOTHING IS BEING RECOMMENDED" in out


@pytest.mark.parametrize(
    "path", recordings() + [PROJECT_ROOT / "shared" / "recorded_run.json"],
    ids=lambda p: p.stem,
)
def test_every_recording_says_when_it_was_run(path):
    """A brief carries share prices from the day it ran.

    Without this the reader is shown a price with no indication of its age,
    which is the one thing they might act on directly. It was listed as an open
    v1.0.1 item for the shipped demo alone; the gallery would have multiplied it
    by five.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload.get("recorded_on"), f"{path.name} does not say when it was run"
    datetime.fromisoformat(payload["recorded_on"])


def test_the_recording_date_is_when_the_run_happened(finished, tmp_path):
    """Not when the file was written. A recording made today of a run made last
    week is dated last week, or the notice above lies about the prices."""
    payload = build(finished, recorded_on="2026-08-26T15:37:50+00:00")

    assert payload["recorded_on"] == "2026-08-26T15:37:50+00:00"


def test_the_gallery_includes_a_run_that_recommends_nothing():
    """The outcome the whole design exists to make possible, and the one a
    gallery of successes would quietly drop. An honest empty answer is more
    persuasive than a full one that happens to look good."""
    empty = [
        path
        for path in recordings()
        if not json.loads(path.read_text(encoding="utf-8"))["decision"]["recommendations"]
    ]
    assert empty, "every recorded run recommends something; that is not the system"


# --- The tool ----------------------------------------------------------------


def _state(user, decision, research, risk, error=None):
    values = {
        "user_input": user,
        "decision": decision,
        "research_findings": research,
        "risk_findings": risk,
    }
    if error:
        values["error"] = error
    return values


@pytest.fixture
def finished(clean_user):
    return _state(
        clean_user,
        Decision(no_recommendation_reason="Nothing cleared the bar."),
        ResearchFindings(articles_retrieved=4),
        RiskFindings(),
    )


def test_a_finished_run_becomes_a_recording(finished, tmp_path):
    payload = build(finished)
    verify(payload)

    assert set(payload) == {"profile", "decision", "research_findings", "risk_findings"}
    assert payload["profile"]["sectors_of_interest"] == ["renewable energy"]


def test_a_run_that_failed_is_refused(finished):
    """"Interrupted" and "failed" are worth showing and are a different thing
    with a different shape. Presenting one as a brief would be the one kind of
    dishonesty this project has not committed."""
    finished["error"] = "Decision failed: BadRequestError"

    with pytest.raises(NotRecordable, match="failed"):
        build(finished)


def test_a_half_finished_run_is_refused(finished):
    del finished["risk_findings"]

    with pytest.raises(NotRecordable, match="missing risk_findings"):
        build(finished)


def test_an_unknown_run_is_refused_rather_than_written(tmp_path):
    with pytest.raises(NotRecordable, match="no run called"):
        record("web-does-not-exist", tmp_path / "out.json")


def test_nothing_is_written_when_the_run_cannot_be_recorded(tmp_path):
    """Verified before written, so a broken recording is never left on disk to
    be found by a visitor instead of by this."""
    destination = tmp_path / "out.json"

    with pytest.raises(NotRecordable):
        record("web-does-not-exist", destination)

    assert not destination.exists()


def test_a_recording_carries_what_the_person_actually_typed(finished, tmp_path):
    """Never edited into saying something nicer. The shipped demo still holds
    restrictions ["no"] because that is what its investor wrote, and editing a
    saved run would make every other recording unciteable."""
    finished["user_input"] = finished["user_input"].model_copy(
        update={"restrictions": ["no"]}
    )

    payload = build(finished)
    assert payload["profile"]["restrictions"] == ["no"]
