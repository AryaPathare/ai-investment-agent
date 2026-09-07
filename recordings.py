"""Real runs, saved to files the repository can carry.

WHY THESE EXIST

Three API keys stand between a stranger and the first line of output, and the
checkpoint database that holds every run made here is machine-local and
deliberately untracked. So without recordings, a person arriving from a link
sees nothing at all until they sign up for three services on trust.

A recording is a finished run written to a file. Same models, same renderer,
same grounded exit conditions - only the API calls are absent. That is what
makes it a RECORDING and not a fixture: it is loaded back through the Pydantic
models the graph writes, so a schema change breaks a test rather than quietly
printing something that is no longer true.

WHY THIS MODULE RATHER THAN THE CLI

``--demo`` has loaded the shipped recording since session 12. The gallery is the
second caller, and a second copy of "which keys become which models" is a second
thing to keep in step - the split this project made for rendering, applied to
reading. The CLI's demo now reads through here.

WHAT A GALLERY ENTRY IS NOT

Every recording is a run that FINISHED. Runs that failed or were interrupted are
worth showing and are a different shape, so they are not folded in here and
dressed as briefs. ``scripts/record_run.py`` refuses to write one.
"""

import json
from pathlib import Path

from config import PROJECT_ROOT
from models.decision import Decision
from models.research import ResearchFindings
from models.risk import RiskFindings
from models.user_input import UserInput

GALLERY_DIR = PROJECT_ROOT / "demo" / "gallery"
DEMO_PATH = PROJECT_ROOT / "demo" / "recorded_run.json"


class RecordingError(Exception):
    """The file is missing, or is not a recording."""


def load(path: Path | str) -> dict:
    """One recording, as the state a renderer expects.

    ``user_input`` belongs in the state and not merely in a header: the
    next-steps section reads the amount and its currency to say what the money
    would buy, and a recording without it silently loses that line.
    """
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RecordingError(f"no recording at {path}") from None
    except json.JSONDecodeError as exc:
        raise RecordingError(f"{path} is not valid JSON: {exc}") from None

    try:
        return {
            "user_input": UserInput.model_validate(payload["profile"]),
            "decision": Decision.model_validate(payload["decision"]),
            "research_findings": ResearchFindings.model_validate(
                payload["research_findings"]
            ),
            "risk_findings": RiskFindings.model_validate(payload["risk_findings"]),
            "recorded_on": payload.get("recorded_on"),
        }
    except KeyError as exc:
        raise RecordingError(f"{path} is missing {exc.args[0]}") from None


def available(directory: Path | None = None) -> list[Path]:
    """Every recording in the gallery, in a stable order.

    Sorted by name rather than by modification time, so the site shows the same
    order on every machine and after every clone.
    """
    directory = directory or GALLERY_DIR
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.json"))


def summarise(path: Path) -> dict:
    """Enough to list a recording without loading the whole brief.

    The SECTORS are what a visitor is choosing between, so they are read from
    the profile rather than from the file name - a name is a label somebody
    typed, and this project has been caught twice by prose that stopped
    matching the thing it described.
    """
    state = load(path)
    user, decision = state["user_input"], state["decision"]
    count = len(decision.recommendations)
    return {
        "name": path.stem,
        "recorded_on": state.get("recorded_on"),
        "sectors": list(user.sectors_of_interest),
        "recommended_nothing": decision.recommended_nothing,
        "recommendations": [r.ticker for r in decision.recommendations],
        "headline": (
            "Nothing is being recommended"
            if decision.recommended_nothing
            else f"{count} {'company' if count == 1 else 'companies'} worth a look"
        ),
        # The profile is shown alongside, because "narrower researches better"
        # is the most useful thing this system knows about how to ask it, and a
        # gallery that hides the question teaches none of it.
        "amount": user.investment_amount,
        "currency": user.investment_currency,
        "experience": user.investment_experience,
        "risk_tolerance": user.risk_tolerance,
        "holding_period": user.holding_period,
    }
