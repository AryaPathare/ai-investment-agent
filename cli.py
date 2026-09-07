"""The command line front end — the only way a person runs this pipeline.

    python -m cli
    python -m cli --profile examples/beginner_renewables.json
    python -m cli --save-profile mine.json
    python -m cli --list                     # what is saved, and what can resume
    python -m cli --resume cli-8f3a2b91      # continue a run that stopped

Everything before this was driven from Python snippets and eval runners, which
meant the system worked but could not be DEMONSTRATED. This closes that gap and
nothing more: it asks the profile questions, runs the graph, carries a
clarification answer back in when Agent 1 asks for one, and prints the result.

FOUR THINGS THIS HAS TO GET RIGHT

1. The clarification interrupt. Agent 1 can stop mid-run and ask the user a
   question. ``graph.stream`` yields an ``__interrupt__`` chunk, the CLI asks,
   and ``Command(resume=answer)`` restarts from exactly that point. The graph
   bounds the loop (``max_clarification_attempts``); this file does not have to,
   and deliberately does not try to second-guess it.

2. Visible progress. A full run is roughly a dozen model calls over several
   minutes. Printing nothing until the end is indistinguishable from a hang, so
   each stage announces itself and reports what it produced as it lands. The
   counts are not decoration - "3 candidates from 11 examined" is the same
   observability the evals rely on, shown to whoever is watching.

3. Recommending nothing must not look like failure. An empty result is the
   outcome the whole design exists to make possible. It gets its own banner and
   its reason printed large, not a blank screen and an exit code.

4. Stopping must be survivable. State is checkpointed to SQLite (see
   checkpoints.py), so closing the terminal at a clarification prompt - or
   Ctrl-C during the three-minute research call - loses nothing. ``--resume``
   picks the run up where it stopped and does not repeat the stages that
   already completed, which on this project's quota is what makes stopping
   cheap rather than expensive.

WHAT IT DOES NOT DO

No file output for the decision, no formatting options, no colour. The eval
runners already persist results for analysis; this prints for a reader.
"""

import argparse
from datetime import datetime
import json
import sys
import textwrap
import time
import uuid
from pathlib import Path

from langgraph.types import Command
from pydantic import ValidationError

import checkpoints
import recordings
import render
from models.decision import Decision
from models.user_input import UserInput

WIDTH = 78


class Cancelled(Exception):
    """The user pressed Ctrl-C or closed stdin. Not an error, just a stop."""


# --- Terminal plumbing -------------------------------------------------------


def _force_utf8_output() -> None:
    """The Windows console is cp1252 and cannot encode what the model emits.

    Same guard the eval runners use. Without it a thesis containing a dash the
    model liked crashes the program at the very last step, after every API call
    has already been paid for.
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def _banner(title: str, char: str = "=") -> None:
    print()
    print(char * WIDTH)
    print(f" {title}")
    print(char * WIDTH)


def _wrap(text: str, indent: str = "     ") -> str:
    return textwrap.fill(
        " ".join(text.split()),
        width=WIDTH,
        initial_indent=indent,
        subsequent_indent=indent,
    )


def _bullet(text: str, indent: str = "       ", marker: str = "• ") -> str:
    """A list item whose continuation lines hang under the text, not the dash.

    Without this a two-line exit condition wraps back to the margin and reads
    as two separate conditions, which is a bad way to misread the one part of
    the output a person is meant to act on.
    """
    return textwrap.fill(
        " ".join(text.split()),
        width=WIDTH,
        initial_indent=indent + marker,
        subsequent_indent=indent + " " * len(marker),
    )


# --- Asking the questions ----------------------------------------------------
#
# These validate SHAPE only: is it a number, is it one of the allowed words.
# Range and cross-field rules stay where they already live, in UserInput, and
# ask_profile() below re-asks whatever Pydantic rejects. Duplicating the bounds
# here would give two places for them to drift apart.


def _read(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        raise Cancelled from None


def _ask_int(question: str) -> int:
    while True:
        raw = _read(f"  {question}: ")
        try:
            return int(raw)
        except ValueError:
            print("     Please enter a whole number.")


def _ask_float(question: str) -> float:
    while True:
        # People type "10,000" and "$10000". Neither should be a rejection.
        raw = _read(f"  {question}: ").replace(",", "").lstrip("$£€")
        try:
            return float(raw)
        except ValueError:
            print("     Please enter an amount, e.g. 10000.")


def _ask_choice(question: str, options: tuple[str, ...]) -> str:
    """Ask for one of a fixed set, matching however the person capitalises it.

    Case-insensitive on the way IN and canonical on the way out, because the
    options are not all the same shape: risk levels are lowercase words and
    currency codes are uppercase. Lowercasing the reply and comparing directly
    worked only while every option happened to be lowercase - "USD" could never
    match, and the prompt looped forever on a correct answer.
    """
    joined = "/".join(options)
    canonical = {option.lower(): option for option in options}
    while True:
        raw = _read(f"  {question} ({joined}): ").strip().lower()
        if raw in canonical:
            return canonical[raw]
        print(f"     Please answer one of: {joined}")


def _ask_text(question: str) -> str:
    while True:
        raw = _read(f"  {question}: ")
        if raw:
            return raw
        print("     Please give an answer.")


def _ask_list(question: str) -> list[str]:
    """A comma separated list. Empty is a legitimate answer for restrictions."""
    raw = _read(f"  {question}: ")
    return [item.strip() for item in raw.split(",") if item.strip()]


# One name for render.py's menu rather than a second copy. Both front ends show
# the same eleven sectors with the same narrowing examples, because the examples
# are what stop everybody picking from the broad end.
SECTORS = render.SECTORS


def _ask_sectors() -> list[str]:
    """Ask what to research, showing the market's sectors as a starting point.

    A beginner faced with a blank prompt and three examples does not know what
    is allowed, which is the problem this solves. But the menu is a starting
    point rather than a set of options: anything typed is accepted, because the
    best answers to this question are narrower than any sector name.

    Numbers, names and free text all work, and can be mixed - "1, grid storage"
    is a perfectly good answer. Numbers are resolved to the provider's own
    wording; anything else is passed through exactly as typed, since a person
    who writes "grid storage" has given something better than the menu offers.
    """
    width = max(len(name) for name, _ in SECTORS)
    print()
    print(f"  {_label('sectors_of_interest')}")
    print()
    for index, (name, example) in enumerate(SECTORS, start=1):
        print(f"    {index:2d}  {name.ljust(width)}   e.g. {example}")
    print()
    print("  Pick numbers, or type something of your own.")
    print(f"  {render.SECTOR_GUIDANCE}")

    raw = _read("  Your answer, comma separated: ")

    chosen: list[str] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if item.isdigit() and 1 <= int(item) <= len(SECTORS):
            chosen.append(SECTORS[int(item) - 1][0])
        else:
            # Typed rather than picked, and left exactly as written. Correcting
            # it towards a menu entry would discard the specificity that makes
            # a typed answer the better one.
            chosen.append(item)
    return chosen


# The questions, in the order they are asked, each paired with how this terminal
# asks it. The WORDING and the allowed answers come from render.py, which the
# web form reads too: entry 96 is about exactly this - a question whose wording
# drifted away from what the field meant, disabling the only guard that would
# have caught the confusion. Two front ends wording it two ways is that failure
# with a second copy of the mistake.
_FIELDS = {field["name"]: field for field in render.form_fields()}

EXPERIENCE = tuple(_FIELDS["investment_experience"]["options"])
RISK = tuple(_FIELDS["risk_tolerance"]["options"])
CURRENCIES = tuple(_FIELDS["investment_currency"]["options"])


def _label(name: str) -> str:
    return _FIELDS[name]["label"]


QUESTIONS: list[tuple[str, object]] = [
    ("age", lambda: _ask_int(_label("age"))),
    (
        "investment_experience",
        lambda: _ask_choice(_label("investment_experience"), EXPERIENCE),
    ),
    ("risk_tolerance", lambda: _ask_choice(_label("risk_tolerance"), RISK)),
    ("investment_amount", lambda: _ask_float(_label("investment_amount"))),
    (
        "investment_currency",
        lambda: _ask_choice(
            f"{_label('investment_currency')}\n"
            f"     ({_FIELDS['investment_currency']['help'].rstrip('.')[0].lower() + _FIELDS['investment_currency']['help'].rstrip('.')[1:]})",
            CURRENCIES,
        ),
    ),
    ("holding_period", lambda: _ask_text(_label("holding_period"))),
    # The single highest-signal answer in the whole run: Agent 2 turns this
    # straight into search queries, so it gets a menu of its own rather than a
    # one-line prompt. See render.SECTORS: the list exists to stop a beginner
    # facing a blank, and its examples exist to stop the menu making everyone
    # broader.
    ("sectors_of_interest", _ask_sectors),
    (
        "restrictions",
        lambda: _ask_list(
            f"{_label('restrictions').rstrip('?')}, comma separated\n"
            f"     (e.g. no fossil fuels, no tobacco - blank if none)"
        ),
    ),
]


def ask_profile() -> UserInput:
    """Ask the eight questions, then let UserInput have the final word."""
    _banner("YOUR PROFILE")
    print()

    askers = dict(QUESTIONS)
    answers = {field: asker() for field, asker in QUESTIONS}

    while True:
        try:
            return UserInput(**answers)
        except ValidationError as exc:
            print()
            for err in exc.errors():
                field = err["loc"][0] if err["loc"] else None
                if field not in askers:
                    # Nothing we can re-ask; surface it rather than looping.
                    raise
                print(f"  That will not work: {field} - {err['msg']}")
                answers[field] = askers[field]()


def load_profile(path: Path | str) -> UserInput:
    """Load a saved profile so a run can be repeated without retyping it.

    Worth having because the Groq daily ceiling is the binding constraint on
    this project: you re-run the same profile many times while changing one
    thing, and eight prompts between each attempt is friction that discourages
    the re-run.
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"No such profile file: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} is not valid JSON: {exc}")

    try:
        return UserInput(**raw)
    except (ValidationError, TypeError) as exc:
        expected = ", ".join(UserInput.model_fields)
        raise SystemExit(
            f"{path} is not a valid profile:\n{exc}\n\nExpected keys: {expected}"
        )


def describe_profile(user: UserInput) -> str:
    """What the system believes the user said, read back to them.

    The WORDS are render.py's, because this same summary heads the demo, the
    loaded-profile line and anything the HTTP layer shows: "will not hold: no
    restrictions" is a statement about their answer, not a layout choice. The
    newlines and the two-space indent are this terminal's, and stay here.
    """
    parts = render.profile_parts(user)
    return (
        f"{parts['headline']}\n"
        f"  interested in: {parts['sectors']}\n"
        f"  will not hold: {parts['restrictions']}"
    )


# --- Running the graph -------------------------------------------------------

# One name for render.py's table rather than a second copy of it. Three places
# have to agree on what a stage is called: the progress display announcing the
# next one, the resume path working out where a saved run stopped, and the HTTP
# layer's stage events.
STAGE_LABELS = render.STAGE_LABELS


class Progress:
    """Prints what each stage produced, as it produces it.

    Stage numbers are announced one step AHEAD of the node that will fill them
    in, because ``stream`` only yields an update once a node has FINISHED and
    the slowest node here takes minutes. Announcing the next stage on completion
    of the previous one is what keeps the screen honest about what is happening
    right now rather than what already happened.
    """

    STAGES = render.STAGES

    def __init__(self) -> None:
        self._started = time.monotonic()

    def stage(self, number: int, label: str) -> None:
        print(f"\n[{number}/{self.STAGES}] {label} ...", flush=True)

    def detail(self, text: str) -> None:
        print(f"        {text}", flush=True)

    def failed(self, reason: str) -> None:
        print(f"        FAILED  {reason}", flush=True)

    @property
    def elapsed(self) -> str:
        return f"{time.monotonic() - self._started:.0f}s"


def _report(progress: Progress, node: str, update: dict) -> None:
    """Turn one node's state update into a line or two on screen.

    The COUNTS come from ``render.stage_detail``, which the HTTP layer also
    reads, so the two front ends cannot end up reporting different numbers for
    the same run. What is left here is the sentence they are written into.
    """
    if update.get("error"):
        progress.failed(update["error"])
        return

    detail = render.stage_detail(node, update)

    if node == "profile_agent":
        if detail["needs_clarification"]:
            progress.detail("your answers appear to conflict")
        else:
            progress.detail("profile valid")
            progress.stage(*STAGE_LABELS["research"])

    elif node == "clarification":
        progress.detail("answer recorded")
        progress.stage(1, "Re-checking your profile")

    elif node == "research":
        progress.detail(
            f"{len(detail['themes'])} theme(s), {detail['articles_cited']} cited "
            f"article(s) from {detail['articles_retrieved']} retrieved"
        )
        for theme in detail["themes"]:
            progress.detail(f"  - {theme['name']} ({theme['confidence']} confidence)")
        progress.stage(*STAGE_LABELS["companies"])

    elif node == "companies":
        progress.detail(
            f"{len(detail['candidates'])} candidate(s) from "
            f"{detail['companies_examined']} companies examined"
        )
        if detail["candidates"]:
            progress.detail("  " + ", ".join(detail["candidates"]))
        if detail["drop_summary"]:
            dropped = ", ".join(
                f"{n} {why}" for why, n in detail["drop_summary"].items()
            )
            progress.detail(f"  dropped: {dropped}")
        progress.stage(*STAGE_LABELS["risk_critic"])

    elif node == "risk_critic":
        for critique in detail["critiques"]:
            if critique["was_critiqued"]:
                progress.detail(
                    f"  {critique['ticker']}: {critique['verdict']} "
                    f"({critique['risks']} risk(s) from "
                    f"{critique['articles_reviewed']} article(s))"
                )
            else:
                progress.detail(
                    f"  {critique['ticker']}: not critiqued - "
                    f"{critique['skipped_reason']}"
                )
            if critique["press_releases_withheld"]:
                progress.detail(
                    f"    withheld {critique['press_releases_withheld']} company "
                    f"press release(s)"
                )
            if critique["sources_withheld"]:
                # A filter that removes evidence without saying so is its own
                # kind of unreliable narrator. Recording it in state and then
                # not printing it would move the silence rather than end it.
                progress.detail(
                    f"    withheld {critique['sources_withheld_count']} article(s) "
                    f"from: {', '.join(critique['sources_withheld'])}"
                )
        progress.stage(*STAGE_LABELS["decide"])

    elif node == "decide":
        progress.detail(f"{len(detail['recommendations'])} recommendation(s)")


def ask_clarification(payload: dict) -> str:
    """Agent 1 has stopped to ask a question. Get an answer to resume with."""
    question = render.describe_question(payload)
    _banner(
        f"CLARIFICATION NEEDED  "
        f"(attempt {question['attempt']} of {question['max_attempts']})",
        char="-",
    )
    print()
    print(_wrap(question["intro"], indent="  "))
    print()
    print(_wrap(question["reason"], indent="    "))
    print()
    print(_wrap(question["prompt"], indent="  "))
    print()

    while True:
        answer = _read("  > ")
        if answer:
            return answer
        # A blank answer would consume one of a small number of attempts and
        # tell the agent nothing, so it is not accepted as an answer.
        print(f"     {question['blank_answer_hint']}")


def run(graph, thread_id: str, start, opening: tuple[int, str]) -> dict:
    """Drive the graph to completion, answering any clarification on the way.

    ``start`` is whatever should be sent first, and it is the only difference
    between a new run and a resumed one:

    * ``{"user_input": ...}``   a new run
    * ``Command(resume=...)``   picking up at a question that was asked before
    * ``None``                  picking up a run killed partway through a stage

    Returns the full final state. ``stream`` yields only per-node updates, so
    the accumulated state is read back from the checkpointer at the end - it is
    what holds the articles the decision cites.
    """
    config = {"configurable": {"thread_id": thread_id}}
    progress = Progress()

    _banner("RUNNING")
    print("\nThis makes real API calls and takes a few minutes.")
    print(f"Run id: {thread_id}")
    print("If this stops before it finishes, resume it with")
    print(f"  python -m cli --resume {thread_id}")
    progress.stage(*opening)

    payload = start
    while True:
        pending = None
        for chunk in graph.stream(payload, config, stream_mode="updates"):
            if "__interrupt__" in chunk:
                pending = chunk["__interrupt__"][0].value
                continue
            for node, update in chunk.items():
                _report(progress, node, update)

        if pending is None:
            break
        payload = Command(resume=ask_clarification(pending))

    print(f"\nDone in {progress.elapsed}.")
    return graph.get_state(config).values


# --- Printing the result -----------------------------------------------------
#
# LAYOUT ONLY. What a reader is TOLD lives in render.py and is shared with the
# HTTP layer; everything below decides where those words sit on a 78-column
# terminal. The line between the two: if changing it would tell a reader
# something different it belongs in render.py, and if it only moves the words on
# the page it belongs here.


def _grounds(entries: list[dict], indent: str = "           ") -> str:
    """Lay out what a reader could go and check, already indented.

    A source runs to three lines - headline, publisher and date, link - and they
    have to line up under each other or the citation stops looking like one
    thing. ``render.grounds_for`` decides WHICH source and what to call a metric;
    this decides the shape.
    """
    lead = f"{indent}Check: "
    cont = " " * len(lead)

    if entries and entries[0]["kind"] == "metric":
        return f"{lead}{entries[0]['text']}"

    lines: list = []
    for entry in entries:
        if entry["kind"] == "article":
            lines.append('"' + entry["title"] + '"')
            lines.append(f"{entry['source']}, {entry['published_on']}")
            # Appended AFTER wrapping, below: textwrap breaks a long URL
            # mid-token, which makes it uncopyable - and a link the reader
            # cannot follow defeats the only reason this block exists.
            lines.append(("url", entry["url"]))
        else:
            lines.append(entry["text"])

    block = []
    for index, line in enumerate(lines):
        prefix = lead if index == 0 else cont
        if isinstance(line, tuple):  # a URL: emitted whole, never wrapped
            block.append(prefix + line[1])
        else:
            block.append(
                textwrap.fill(line, width=WIDTH, initial_indent=prefix,
                              subsequent_indent=cont)
            )
    return "\n".join(block)


def print_as_of_notice(when, what: str) -> None:
    """Say, before anything else, that these numbers are from a past moment.

    A resumed run and the shipped recording both replay state that was true
    when it was fetched. Share prices move daily, and the brief now prints one
    next to a share count - so a reader arriving at an old run needs to know
    that BEFORE they read a number, not in a footnote after it.
    """
    when = render.as_datetime(when)
    if when is None:
        return
    print()
    print(_wrap(
        f"{what} on {when:%d %b %Y}. Share prices below are from that day and "
        "will have moved since.",
        indent="  ",
    ))


def print_next_steps(described: dict) -> None:
    """Turn the brief into something a reader can actually act on.

    Prices, what the stated amount would buy, and a date to look again. No
    forecast and no allocation: nothing here predicts a price or suggests how
    much to put anywhere, because nothing in this pipeline models either.
    """
    if not described["recommendations"]:
        return

    _banner("WHAT TO DO NEXT", char="-")
    print()

    for rec in described["recommendations"]:
        price = rec["price"]
        if price is None:
            print(f"  {rec['ticker']}: no price was available from the data provider.")
            continue
        line = (
            f"  {rec['ticker']}  {price['currency']} "
            f"{price['amount']:,.2f} per share"
        )
        # The price in THEIR money, when the share trades in something else.
        # "CNY 373.00" tells a reader almost nothing on its own.
        if price["in_investor_currency"] is not None:
            line += (
                f"  (about {price['investor_currency']} "
                f"{price['in_investor_currency']:,.2f})"
            )
        print(f"{line}   (as of {price['as_of_on']})")

        if rec["affordable"]:
            print(_wrap(rec["affordable"], indent="        "))

    print()
    print(_wrap(
        f"Look at this again on {described['next_review_on']}, about three "
        "months from now - roughly one set of results. What to check is listed "
        "under each company above.",
        indent="  ",
    ))


def print_recommendation(rec: dict) -> None:
    """One company, written for someone who has not invested before.

    The screen score is deliberately NOT printed. It is a ranking number, and
    `agents/screening.py` records why its absolute value cannot be read as a
    grade: it saturates at the top and caps financial companies at 0.50. A
    reader shown "0.64" will take it for 64% of something. The position in this
    list is the part of that number that means anything, and the list already
    shows it.
    """
    print()
    print(f" {rec['index']}. {rec['name']} ({rec['ticker']})")
    if rec["themes"]:
        print(_wrap(f"Came up because of: {', '.join(rec['themes'])}", indent="     "))
    if rec["verdict_text"]:
        print(f"     {rec['verdict_text']}")

    print()
    print("     Why it might be worth a look")
    print(_wrap(rec["thesis"], indent="       "))

    print()
    print("     What would mean the idea has stopped working")
    for condition in rec["exit_conditions"]:
        print(_bullet(condition["condition"]))
        print(_grounds(condition["grounds"]))

    if rec["known_risks"]:
        print()
        print("     Worth knowing")
        for risk in rec["known_risks"]:
            print(_bullet(risk))


def print_decision(decision: Decision, state: dict) -> None:
    """Print the Decision. An empty one is a result, and is printed like one."""
    described = render.describe_decision(decision, state, state.get("user_input"))

    if described["recommended_nothing"]:
        # Deliberately the loudest thing on screen. Everywhere else in this
        # project an empty result is a legitimate outcome that must not read as
        # a crash; this is the one place a person actually sees it, so it gets
        # the banner and the reason rather than silence.
        _banner(described["nothing_headline"].upper())
        print()
        print(_wrap(described["nothing_explanation"], indent="  "))
        print()
        print("  Why")
        print(_wrap(described["no_recommendation_reason"], indent="    "))
    else:
        _banner(described["headline"].upper())
        for rec in described["recommendations"]:
            print_recommendation(rec)

    if described["excluded"]:
        _banner("ALSO CONSIDERED, BUT NOT RECOMMENDED", char="-")
        print()
        # Every candidate is accounted for here on purpose: a company that
        # simply vanished between the ranking and the output would be the one
        # failure a reader could never detect. The stored reason is an enum for
        # code to branch on, so render.py translates it rather than printing it.
        for item in described["excluded"]:
            print(f"  {item['name']} ({item['ticker']})")
            print(_wrap(item["reason_text"], indent="      "))
            if item["detail"]:
                print(_wrap(item["detail"], indent="      "))

    if not described["recommended_nothing"]:
        print_next_steps(described)

    # Observability, kept small and at the bottom. A conditions_discarded count
    # that climbs means the model is writing conditions grounded in nothing,
    # and the briefs above would still read perfectly well.
    if described["footnotes"]:
        print()
        print("-" * WIDTH)
        for note in described["footnotes"]:
            print(_wrap(note, indent="  "))

    print()
    print("=" * WIDTH)
    print(_wrap(render.DISCLAIMER, indent=" "))
    print("=" * WIDTH)


def print_outcome(state: dict) -> int:
    """Print whatever the run ended with. Returns the process exit code."""
    described = render.describe_run(state)

    if described["status"] == "failed":
        _banner("THE RUN COULD NOT FINISH")
        print()
        print(_wrap(described["error"], indent="  "))
        print()
        print(_wrap(described["error_hint"], indent="  "))
        return 1

    if described["status"] == "no_decision":
        # Should be unreachable: every path either sets a decision or an error.
        # Saying so is better than printing nothing and exiting 0.
        _banner("THE RUN ENDED WITHOUT A DECISION OR AN ERROR")
        print(f"\n  State reached: {described['state_reached']}")
        return 1

    print_decision(state["decision"], state)
    # Recommending nothing exits 0. It is an answer, and a non-zero code would
    # tell every script wrapping this that the run had failed.
    return 0


# --- Saved runs --------------------------------------------------------------


STATUS_TEXT = {
    "paused": "paused, waiting on your answer",
    "stopped": "stopped partway through",
    "finished": "finished",
    "failed": "failed at the last stage",
}


def print_saved_runs(runs: list) -> int:
    """List what is in the checkpoint database. Returns the exit code."""
    _banner("SAVED RUNS")
    print()

    if not runs:
        print(_wrap(
            "Nothing saved yet. Runs appear here once you start one, and stay "
            "until you delete the database.",
            indent="  ",
        ))
        return 0

    width = max(len(run.thread_id) for run in runs)
    for run in runs:
        sectors = ", ".join(run.sectors) or "no sectors recorded"
        print(f"  {run.thread_id:<{width}}  {STATUS_TEXT[run.status]:<30}  {sectors}")

    resumable = [run for run in runs if run.can_resume]
    if resumable:
        print()
        print(_wrap(
            f"Resume one with: python -m cli --resume {resumable[0].thread_id}",
            indent="  ",
        ))
    return 0


def resume(store, thread_id: str) -> int:
    """Continue a saved run. Returns the exit code.

    The profile is deliberately NOT asked for again: ``user_input`` is already
    in the saved state, and asking a returning user to retype eight answers
    would defeat the point of having saved anything.
    """
    saved = store.run(thread_id)

    if saved is None:
        # Loud rather than silent, which is the reason resuming is its own flag
        # instead of --thread-id guessing. A typo must not quietly start a new
        # run that spends a day's quota under a name nobody will look for.
        print(f"\nNo saved run called {thread_id!r}.")
        print("Run python -m cli --list to see what is saved.")
        return 1

    if saved.status == "failed":
        # A failed run is shaped like a finished one - nothing pending - so it
        # fell into the branch below and announced "already finished, showing
        # what it produced" directly above a banner reading THE RUN COULD NOT
        # FINISH. The error always reached the reader; the sentence introducing
        # it contradicted it.
        print(f"\nRun {thread_id!r} failed before it could finish. Here is why.")
        print_as_of_notice(saved.updated_at, "This run was made")
        return print_outcome(store.graph.get_state(store.config(thread_id)).values)

    if saved.status == "finished":
        # Not an error: the answer is right there. Reprint it rather than
        # refusing, because "it already finished" is not a useful reply to
        # somebody who wants to see the result again.
        print(f"\nRun {thread_id!r} already finished. Showing what it produced.")
        print_as_of_notice(saved.updated_at, "This run was made")
        return print_outcome(store.graph.get_state(store.config(thread_id)).values)

    print(f"\nResuming {thread_id!r} - {STATUS_TEXT[saved.status]}.")
    if saved.sectors:
        print(f"  researching: {', '.join(saved.sectors)}")

    if saved.question is not None:
        # It stopped at a question, so re-ask that exact question. Somebody
        # coming back tomorrow needs to see what conflicted, not just a prompt.
        start = Command(resume=ask_clarification(saved.question))
        # NOT the profile_agent label: the node that runs first here is the
        # clarification one, recording the answer. Announcing "checking your
        # profile" and then printing "answer recorded" under it describes the
        # wrong thing.
        opening = (1, "Applying your answer")
    else:
        # It died partway through a stage. Sending nothing tells the graph to
        # pick up the unfinished node - the stages that DID complete are not
        # repeated, which on this project's quota is the whole point.
        start = None
        node = store.graph.get_state(store.config(thread_id)).next[0]
        opening = STAGE_LABELS.get(node, (1, f"Continuing at {node}"))

    state = run(store.graph, thread_id, start, opening)
    return print_outcome(state)


# --- Entry point -------------------------------------------------------------


# Deliberately NOT under examples/, which is documented as saved profiles for
# --profile and is walked by a test that loads every file there as one. A
# recording is a different kind of thing and belongs in its own place.
DEMO_PATH = Path(__file__).parent / "demo" / "recorded_run.json"


def run_demo(path: Path | str = DEMO_PATH) -> int:
    """Print a recorded run, so the pipeline can be seen with no keys at all.

    The first thing anyone does with a repository is try to run it, and this one
    needs three API keys before it can produce a single line of output. That is
    a long way to walk on trust. This prints a REAL run - the same renderer,
    the same models, the same grounded exit conditions - from a recording that
    ships with the code, with no network call and nothing to sign up for.

    It is deliberately a recording rather than a fake. Every article, ticker and
    threshold below was produced by the live pipeline; only the API calls are
    absent. A hand-written fixture could say anything, and would rot silently
    the first time the schemas changed - this one cannot, because it is loaded
    through the same Pydantic models the graph writes.
    """
    try:
        state = recordings.load(path)
    except recordings.RecordingError as exc:
        print(f"\n{exc}")
        print("It ships with the repository; re-clone or check it out again.")
        return 1

    user = state["user_input"]

    _banner("A RECORDED RUN")
    print()
    print(_wrap(
        "This is real output from a real run, replayed from a recording that "
        "ships with the repository. No API key, no network call and no quota "
        "were used to print it.",
        indent="  ",
    ))
    recorded = state.get("recorded_on")
    if recorded:
        print_as_of_notice(datetime.fromisoformat(recorded), "It was recorded")
    print()
    print("  The person this was researched for:")
    print(f"  {describe_profile(user)}")
    print()
    print(_wrap(
        "To run the pipeline for yourself you will need a free Groq key - see "
        "the README. Then: python -m cli --profile examples/semiconductors_high_risk.json",
        indent="  ",
    ))

    return print_outcome(state)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m cli",
        description="Run the investment research pipeline and print the result.",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        metavar="FILE",
        help="Run a saved profile (JSON) instead of asking the questions.",
    )
    parser.add_argument(
        "--save-profile",
        type=Path,
        metavar="FILE",
        help="Write the answers to FILE so this run can be repeated with --profile.",
    )
    parser.add_argument(
        "--thread-id",
        metavar="ID",
        help="Name this run, so --resume can find it. Generated if not given.",
    )
    parser.add_argument(
        "--resume",
        metavar="ID",
        help="Continue a saved run instead of starting a new one.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Print a recorded run. Needs no API key and makes no network call.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_runs",
        help="Show saved runs and which of them can be resumed.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        metavar="FILE",
        help=f"Checkpoint database to use (default: {checkpoints.DB_PATH}).",
    )
    args = parser.parse_args(argv)

    if args.demo and (args.resume or args.profile or args.list_runs):
        parser.error("--demo prints a recording; it takes no other options.")
    if args.resume and args.profile:
        parser.error("--resume continues a saved run; it takes no --profile.")
    if args.resume and args.list_runs:
        parser.error("--resume and --list do different things; pick one.")

    _force_utf8_output()

    print("=" * WIDTH)
    print(" AI INVESTMENT RESEARCH AGENT")
    print("=" * WIDTH)

    # Before the store is opened, deliberately. The demo must not construct the
    # graph, because building it imports every agent, and the point of this path
    # is that it works on a machine with no configuration at all.
    if args.demo:
        return run_demo()

    try:
        # The database is opened for every path, including --list, and closed
        # on the way out however this ends.
        with checkpoints.open_store(args.db) as store:
            if args.list_runs:
                return print_saved_runs(store.saved_runs())

            if args.resume:
                return resume(store, args.resume)

            user = load_profile(args.profile) if args.profile else ask_profile()

            if args.profile:
                print(f"\nLoaded {args.profile}:")
                print(f"  {describe_profile(user)}")

            if args.save_profile:
                args.save_profile.write_text(
                    json.dumps(user.model_dump(), indent=2), encoding="utf-8"
                )
                print(f"\nProfile saved to {args.save_profile}")

            thread_id = args.thread_id or f"cli-{uuid.uuid4().hex[:8]}"

            # Starting a NEW run on a thread that already exists silently
            # inherits its state. Verified: a second run under the same id is
            # handed the first run's clarification_responses, so Agent 1 sees a
            # conflict it believes was already resolved and returns "valid"
            # WITHOUT ASKING - a contradictory profile straight through the one
            # gate built to stop it. Refusing is the only safe answer, and it is
            # why resuming is an explicit flag rather than something inferred.
            if store.run(thread_id) is not None:
                print()
                print(f"A run called {thread_id!r} already exists.")
                print("  Continue it:  python -m cli --resume " + thread_id)
                print("  Or start fresh under a different --thread-id.")
                return 1
            state = run(
                store.graph,
                thread_id,
                {"user_input": user},
                STAGE_LABELS["profile_agent"],
            )
            return print_outcome(state)

    except (Cancelled, KeyboardInterrupt):
        # KeyboardInterrupt as well as Cancelled: _read() converts Ctrl-C at a
        # PROMPT into Cancelled, but Ctrl-C during graph.stream - the three
        # minutes where it is most likely - never passes through _read and would
        # otherwise print a traceback. That directly contradicts the promise
        # made in this module's docstring and in the README, and the state is
        # genuinely safe, so saying so is the whole point.
        print()
        print()
        print("Stopped. The run is saved; python -m cli --list will show it.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
