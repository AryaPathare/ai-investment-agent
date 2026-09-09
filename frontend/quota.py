"""How many runs are probably left today, said as an estimate because it is one.

WHY THIS CANNOT BE MEASURED PROPERLY

Groq does not report the DAILY budget in its response headers - only the
per-minute one - so there is no way to ask how much room is left. The obvious
workaround is to probe with a small call and read its success as permission.
That was tried, and it is recorded in this project's log as the clearest example
of a test that cannot fail:

    Limit 200000, Used 199921, Requested 3430

Seventy-nine tokens remained. A one-token probe fits inside seventy-nine tokens,
so the probe could not have failed, and its success carried no information at
all about whether the next 25,000 would fit.

What DOES work is the refusal. A 429 states Limit, Used and Requested exactly,
costs nothing, and adds nothing to the window it reports on - rejected requests
do not count against it. So the honest design is: estimate for the screen,
attempt anyway, and let the refusal be the gate. Never refuse a visitor on the
strength of a number this module produced.

WHICH CEILING BINDS FIRST

Counted rather than guessed, from the provenance block every cached news
response carries. Across 16 full pipeline runs on disk:

    news requests per run     min 7, median ~13, max 24
    tokens per run            25-30k (measured, and the figure that was once
                              documented as ~6k - trusting that killed a
                              five-profile verification run)

    news    100/day  ->  100/13  ~= 7.7 runs, and 100/24 ~= 4 on a bad one
    tokens  200k/day ->  200/27  ~= 7.4 runs

**They land within one run of each other**, which the handoff did not expect,
and which one binds depends on how many candidates a run produces: a run that
reaches four candidates spends eight bear-case searches on top of research and
is news-bound, while a run that reaches one is token-bound. So there is no
single tighter constraint to pick. Seven is the floor of both, and the word
"about" on screen is doing real work.

WHY RUNS AND NOT REQUESTS

News requests could be counted exactly - the cache provenance is a ledger of
them. Tokens cannot be counted at all. A counter mixing one exact number with
one unmeasurable one would look more precise than its worst half, which is the
failure this project keeps recording: a metric that clips cannot also be its own
alarm. Counting whole runs is uniformly rough, and says so.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.config import PROJECT_ROOT

RUNS_PER_DAY = 7
"""The floor of both measured ceilings. See the module docstring for the sums."""

WINDOW = timedelta(hours=24)
"""Groq's limit is a ROLLING 24 hours, not a calendar day.

Checked against the provider's own console, which buckets by calendar day and
therefore disagrees with the limit being enforced: a session running past
midnight is split across two rows and neither of them is the number that
matters. The window drains continuously - three refusals seconds apart reported
Used 199921, 199916, 199912, going DOWN while requests were being refused.
"""

LEDGER = PROJECT_ROOT / ".state" / "runs_served.json"
"""When each run was started.

In ``.state/`` beside the checkpoints, deliberately NOT in ``.cache/``. That
directory is documented as re-fetchable and safe to delete to force fresh data,
and somebody clearing it should not thereby hand the day's budget back.

Durable rather than in-process for the same reason: a restart that reset the
count to zero would let a deploy spend the day twice.
"""


def _read() -> list[str]:
    try:
        stamps = json.loads(LEDGER.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        # A missing or corrupt ledger means "nothing recorded", never an error.
        # Failing a visitor's run over the bookkeeping would be worse than
        # over-serving by a run.
        return []
    return stamps if isinstance(stamps, list) else []


def _within_window(stamps: list[str], now: datetime) -> list[str]:
    cutoff = now - WINDOW
    kept = []
    for stamp in stamps:
        try:
            when = datetime.fromisoformat(stamp)
        # TypeError as well as ValueError. The docstring above promises that a
        # corrupt ledger reads as "nothing recorded", and a JSON list holding
        # numbers rather than strings broke that promise in the one direction
        # that matters: it raised, inside the call that decides whether a
        # visitor may run.
        except (TypeError, ValueError):
            continue
        if when > cutoff:
            kept.append(stamp)
    return kept


def record(now: datetime | None = None) -> None:
    """Note that a run has been started.

    At the START, not the end. A run that fails halfway has already spent what
    it spent, and a counter that only records successes would drift upward
    exactly when the day is going badly.
    """
    now = now or datetime.now(timezone.utc)
    stamps = _within_window(_read(), now)
    stamps.append(now.isoformat())
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(stamps), encoding="utf-8")


def describe(now: datetime | None = None) -> dict:
    """What to put on screen, with the uncertainty attached to it.

    ``estimate`` is not decoration. A reader told "4 runs left" will believe it,
    and the only honest thing this module knows is how many runs it has started
    recently - not how many tokens those cost, and not what anything else on the
    same key has been doing.
    """
    now = now or datetime.now(timezone.utc)
    used = len(_within_window(_read(), now))
    remaining = max(RUNS_PER_DAY - used, 0)
    return {
        "runs_used": used,
        "runs_remaining": remaining,
        "runs_per_day": RUNS_PER_DAY,
        "estimate": True,
        "note": (
            f"About {remaining} run{'' if remaining == 1 else 's'} left today. "
            "This is an estimate: the provider does not report the daily budget, "
            "so the real limit only shows up as a refusal - which costs nothing "
            "and states the numbers exactly."
        ),
    }
