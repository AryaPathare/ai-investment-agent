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
import json
import sys
import textwrap
import time
import uuid
from pathlib import Path
from typing import get_args

from langgraph.types import Command
from pydantic import ValidationError

import checkpoints
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


def _bullet(text: str, indent: str = "       ", marker: str = "- ") -> str:
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
    joined = "/".join(options)
    while True:
        raw = _read(f"  {question} ({joined}): ").lower()
        if raw in options:
            return raw
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


# The allowed words come from UserInput's own Literal types rather than being
# retyped here, so adding a risk level in one place cannot leave the CLI
# offering the old three.
EXPERIENCE = get_args(UserInput.model_fields["investment_experience"].annotation)
RISK = get_args(UserInput.model_fields["risk_tolerance"].annotation)

QUESTIONS: list[tuple[str, object]] = [
    ("age", lambda: _ask_int("Your age")),
    ("investment_experience", lambda: _ask_choice("Investment experience", EXPERIENCE)),
    ("risk_tolerance", lambda: _ask_choice("Risk tolerance", RISK)),
    ("investment_amount", lambda: _ask_float("Amount you want to invest")),
    ("investment_window", lambda: _ask_text("When do you need the money back")),
    ("holding_period", lambda: _ask_text("How long do you expect to hold")),
    # The single highest-signal answer in the whole run: Agent 2 turns this
    # straight into search queries. The examples matter - "technology" and
    # "grid storage" produce very different research, and people do not know
    # that the specific answer is the better one unless they are shown.
    (
        "sectors_of_interest",
        lambda: _ask_list(
            "Sectors or fields to research, comma separated\n"
            "     (e.g. renewable energy, semiconductors, grid storage)"
        ),
    ),
    (
        "restrictions",
        lambda: _ask_list(
            "Anything you will not invest in, comma separated\n"
            "     (e.g. no fossil fuels, no tobacco - blank if none)"
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
    sectors = ", ".join(user.sectors_of_interest) or "no sectors given"
    limits = ", ".join(user.restrictions) or "no restrictions"
    return (
        f"age {user.age}, {user.investment_experience}, "
        f"{user.risk_tolerance} risk, {user.investment_amount:,.0f} "
        f"over {user.investment_window}\n"
        f"  interested in: {sectors}\n"
        f"  will not hold: {limits}"
    )


# --- Running the graph -------------------------------------------------------

# What each graph node is called on screen, and which of the five stages it is.
# Kept in one table because it is needed in two places that must agree: the
# progress display announcing the next stage, and the resume path working out
# where a saved run stopped. Two copies would drift the moment a node is added.
STAGE_LABELS: dict[str, tuple[int, str]] = {
    "profile_agent": (1, "Checking your profile makes sense"),
    "clarification": (1, "Waiting for your clarification"),
    "clarification_exhausted": (1, "Giving up on the profile"),
    "research": (2, "Researching current themes in your sectors"),
    "companies": (3, "Finding companies genuinely exposed to those themes"),
    "risk_critic": (4, "Stress-testing each candidate against bad news"),
    "decide": (5, "Writing the brief"),
}


class Progress:
    """Prints what each stage produced, as it produces it.

    Stage numbers are announced one step AHEAD of the node that will fill them
    in, because ``stream`` only yields an update once a node has FINISHED and
    the slowest node here takes minutes. Announcing the next stage on completion
    of the previous one is what keeps the screen honest about what is happening
    right now rather than what already happened.
    """

    STAGES = 5

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
    """Turn one node's state update into a line or two on screen."""
    if update.get("error"):
        progress.failed(update["error"])
        return

    if node == "profile_agent":
        profile = update["investor_profile"]
        if profile.needs_clarification:
            progress.detail("your answers appear to conflict")
        else:
            progress.detail("profile valid")
            progress.stage(*STAGE_LABELS["research"])

    elif node == "clarification":
        progress.detail("answer recorded")
        progress.stage(1, "Re-checking your profile")

    elif node == "research":
        found = update["research_findings"]
        progress.detail(
            f"{len(found.themes)} theme(s), {len(found.articles)} cited article(s) "
            f"from {found.articles_retrieved} retrieved"
        )
        for theme in found.themes:
            progress.detail(f"  - {theme.name} ({theme.confidence} confidence)")
        progress.stage(*STAGE_LABELS["companies"])

    elif node == "companies":
        found = update["company_findings"]
        progress.detail(
            f"{len(found.candidates)} candidate(s) from "
            f"{found.companies_examined} companies examined"
        )
        if found.candidates:
            progress.detail("  " + ", ".join(c.ticker for c in found.candidates))
        if found.drop_summary:
            dropped = ", ".join(f"{n} {why}" for why, n in found.drop_summary.items())
            progress.detail(f"  dropped: {dropped}")
        progress.stage(*STAGE_LABELS["risk_critic"])

    elif node == "risk_critic":
        found = update["risk_findings"]
        for critique in found.critiques:
            if critique.was_critiqued:
                progress.detail(
                    f"  {critique.ticker}: {critique.verdict} "
                    f"({len(critique.risks)} risk(s) from "
                    f"{critique.articles_reviewed} article(s))"
                )
            else:
                progress.detail(
                    f"  {critique.ticker}: not critiqued - {critique.skipped_reason}"
                )
            if critique.press_releases_withheld:
                progress.detail(
                    f"    withheld {critique.press_releases_withheld} company "
                    f"press release(s)"
                )
            if critique.sources_withheld:
                # A filter that removes evidence without saying so is its own
                # kind of unreliable narrator. Recording it in state and then
                # not printing it would move the silence rather than end it.
                withheld = ", ".join(sorted(set(critique.sources_withheld)))
                progress.detail(
                    f"    withheld {len(critique.sources_withheld)} article(s) "
                    f"from: {withheld}"
                )
        progress.stage(*STAGE_LABELS["decide"])

    elif node == "decide":
        decision = update["decision"]
        progress.detail(f"{len(decision.recommendations)} recommendation(s)")


def ask_clarification(payload: dict) -> str:
    """Agent 1 has stopped to ask a question. Get an answer to resume with."""
    _banner(
        f"CLARIFICATION NEEDED  "
        f"(attempt {payload['attempt']} of {payload['max_attempts']})",
        char="-",
    )
    print()
    print(_wrap("Two of your answers appear to contradict each other:", indent="  "))
    print()
    print(_wrap(payload["reason"], indent="    "))
    print()
    print(_wrap(payload.get("question", "Please clarify your preference."), indent="  "))
    print()

    while True:
        answer = _read("  > ")
        if answer:
            return answer
        # A blank answer would consume one of a small number of attempts and
        # tell the agent nothing, so it is not accepted as an answer.
        print("     Please say which of the two you would rather keep.")


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


def _find_article(article_id: str, state: dict):
    """Look an article id up in both stores that could hold it.

    Exit conditions cite bear-case articles from Agent 4 OR theme articles from
    Agent 2, and neither store knows about the other.
    """
    for findings in (state.get("risk_findings"), state.get("research_findings")):
        if findings is not None:
            article = findings.article_by_id(article_id)
            if article is not None:
                return article
    return None


def _grounds(condition, state: dict, indent: str = "         ") -> str:
    """Say what a reader could go and check to see whether a condition has hit.

    Returned as a block already indented, because a source runs to three lines -
    headline, publisher and date, link - and they have to line up under each
    other or the citation stops looking like one thing.

    An id that resolves in neither store is reported as such rather than printed
    as a bare uuid: "the source was not retained" is information, and a hex
    string on its own is not.
    """
    lead = f"{indent}grounds: "
    cont = " " * len(lead)

    if condition.metric:
        return f"{lead}metric {condition.metric}"

    lines: list[str] = []
    for article_id in condition.article_ids:
        article = _find_article(article_id, state)
        if article is None:
            lines.append(f"article {article_id[:8]} (source not retained)")
            continue
        lines.append(f'"{article.title}"')
        lines.append(f"{article.source}, {article.published_at:%Y-%m-%d}")
        lines.append(article.url)

    if not lines:
        lines = ["nothing checkable"]

    block = [textwrap.fill(lines[0], width=WIDTH, initial_indent=lead, subsequent_indent=cont)]
    block += [
        textwrap.fill(line, width=WIDTH, initial_indent=cont, subsequent_indent=cont)
        for line in lines[1:]
    ]
    return "\n".join(block)


def print_recommendation(index: int, rec, state: dict) -> None:
    print()
    print(f" {index}. {rec.ticker} - {rec.name}")
    print(f"     screen score {rec.screen_score:.2f}  |  risk verdict: {rec.verdict}")
    if rec.themes:
        print(_wrap(f"themes: {', '.join(rec.themes)}", indent="     "))

    print()
    print("     WHY")
    print(_wrap(rec.thesis, indent="       "))

    print()
    print("     WHAT WOULD MEAN THIS HAS STOPPED BEING A GOOD IDEA")
    for condition in rec.exit_conditions:
        print(_bullet(condition.condition))
        print(_grounds(condition, state))

    if rec.known_risks:
        print()
        print("     RISKS IT STILL CARRIES")
        for risk in rec.known_risks:
            print(_bullet(risk))


def print_decision(decision: Decision, state: dict) -> None:
    """Print the Decision. An empty one is a result, and is printed like one."""
    if decision.recommended_nothing:
        # Deliberately the loudest thing on screen. Everywhere else in this
        # project an empty result is a legitimate answer that must not read as
        # a crash; this is the one place a person actually sees it, so it gets
        # the banner and the reason rather than silence.
        _banner("NOTHING IS BEING RECOMMENDED")
        print()
        print(
            _wrap(
                "This is a real answer, not a failure. The pipeline ran and "
                "concluded that nothing cleared the bar.",
                indent="  ",
            )
        )
        print()
        print("  WHY")
        print(
            _wrap(decision.no_recommendation_reason or "no reason recorded", indent="    ")
        )
    else:
        _banner(f"{len(decision.recommendations)} RECOMMENDATION(S)")
        for index, rec in enumerate(decision.recommendations, start=1):
            print_recommendation(index, rec, state)

    if decision.excluded:
        _banner("CONSIDERED AND NOT RECOMMENDED", char="-")
        print()
        # Every candidate is accounted for here on purpose: a company that
        # simply vanished between the ranking and the output would be the one
        # failure a reader could never detect.
        for item in decision.excluded:
            print(f"  {item.ticker} - {item.name}")
            print(f"      reason: {item.reason}")
            if item.detail:
                print(_wrap(item.detail, indent="        "))
        summary = ", ".join(
            f"{n} {why}" for why, n in decision.exclusion_summary.items()
        )
        print(f"\n  ({summary})")

    # Observability, kept small and at the bottom. A conditions_discarded count
    # that climbs means the model is writing conditions grounded in nothing,
    # and the briefs above would still read perfectly well.
    footnotes = []
    if decision.conditions_discarded:
        footnotes.append(
            f"{decision.conditions_discarded} exit condition(s) discarded as ungrounded"
        )
    if decision.notes:
        footnotes.append(decision.notes)
    if footnotes:
        print()
        print("-" * WIDTH)
        for note in footnotes:
            print(_wrap(note, indent="  "))

    print()
    print("=" * WIDTH)
    print(
        _wrap(
            "Research, not advice. This system does not size positions or tell "
            "anyone what to buy.",
            indent=" ",
        )
    )
    print("=" * WIDTH)


def print_outcome(state: dict) -> int:
    """Print whatever the run ended with. Returns the process exit code."""
    if state.get("error"):
        _banner("THE RUN COULD NOT FINISH")
        print()
        print(_wrap(state["error"], indent="  "))
        print()
        print(
            _wrap(
                "If this mentions a rate limit or a quota, the daily ceiling has "
                "been reached; try again later. Run python -m scripts.check_setup "
                "to tell a configuration problem from an outage.",
                indent="  ",
            )
        )
        return 1

    decision = state.get("decision")
    if decision is None:
        # Should be unreachable: every path either sets a decision or an error.
        # Saying so is better than printing nothing and exiting 0.
        _banner("THE RUN ENDED WITHOUT A DECISION OR AN ERROR")
        print(f"\n  State reached: {sorted(state)}")
        return 1

    print_decision(decision, state)
    # Recommending nothing exits 0. It is an answer, and a non-zero code would
    # tell every script wrapping this that the run had failed.
    return 0


# --- Saved runs --------------------------------------------------------------


STATUS_TEXT = {
    "paused": "paused, waiting on your answer",
    "stopped": "stopped partway through",
    "finished": "finished",
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

    if saved.status == "finished":
        # Not an error: the answer is right there. Reprint it rather than
        # refusing, because "it already finished" is not a useful reply to
        # somebody who wants to see the result again.
        print(f"\nRun {thread_id!r} already finished. Showing what it produced.")
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

    if args.resume and args.profile:
        parser.error("--resume continues a saved run; it takes no --profile.")
    if args.resume and args.list_runs:
        parser.error("--resume and --list do different things; pick one.")

    _force_utf8_output()

    print("=" * WIDTH)
    print(" AI INVESTMENT RESEARCH AGENT")
    print("=" * WIDTH)

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
            state = run(
                store.graph,
                thread_id,
                {"user_input": user},
                STAGE_LABELS["profile_agent"],
            )
            return print_outcome(state)

    except Cancelled:
        # The state is already on disk, so this is genuinely recoverable now.
        print("\n\nStopped. The run is saved; python -m cli --list will show it.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
