"""Tests for the command line front end.

The CLI is the only part of this project a person touches directly, and it is
the part with no eval behind it — there is nothing to score about a printed
page. So the suite carries more of the weight here than it does elsewhere, and
it is aimed at the three things that would actually hurt:

* the clarification interrupt not resuming, which strands the user mid-run
* recommending nothing rendering as a blank screen or a failure exit code
* an exit condition's grounds not being shown, which is the whole reason the
  citation was carried this far

Everything is stubbed. No network, no model, no real keys.
"""

import json
from datetime import date, datetime, timezone

import pytest

import cli
import workflow
from config import get_settings
from models.companies import CompanyFindings
from models.decision import Decision, ExcludedCompany, ExitCondition, Recommendation
from models.research import ResearchFindings
from models.risk import RiskFindings
from models.user_input import UserInput
from tests.conftest import make_article


@pytest.fixture
def answers(monkeypatch):
    """Feed a scripted list of keystrokes to every input() the CLI makes."""

    def _install(*lines):
        queued = list(lines)

        def fake_input(prompt=""):
            if not queued:
                raise AssertionError(
                    f"the CLI asked more questions than the test scripted; "
                    f"it was stuck on {prompt!r}"
                )
            return queued.pop(0)

        monkeypatch.setattr("builtins.input", fake_input)
        return queued

    return _install


PROFILE_ANSWERS = [
    "35",
    "intermediate",
    "moderate",
    "5000",
    "USD",
    "within 3 months",
    "5+ years",
    "renewable energy, grid storage",
    "no fossil fuels",
]


# --- Reading answers ---------------------------------------------------------


def test_a_number_question_re_asks_instead_of_crashing(answers, capsys):
    answers("thirty five", "", "35")
    assert cli._ask_int("Your age") == 35
    assert "whole number" in capsys.readouterr().out


def test_amounts_survive_the_way_people_actually_type_them(answers):
    """"$10,000" is what a person writes. Rejecting it would be the CLI's fault."""
    answers("$10,000")
    assert cli._ask_float("Amount") == 10000.0


def test_a_choice_question_re_asks_until_it_gets_one_of_the_options(answers, capsys):
    answers("very risky", "MODERATE")
    assert cli._ask_choice("Risk", cli.RISK) == "moderate"
    assert "Please answer one of" in capsys.readouterr().out


def test_a_list_question_splits_and_drops_blanks(answers):
    answers("solar, , wind ,batteries")
    assert cli._ask_list("Sectors") == ["solar", "wind", "batteries"]


def test_an_empty_list_answer_is_accepted(answers):
    """Having no restrictions is a normal thing to have."""
    answers("")
    assert cli._ask_list("Restrictions") == []


def test_ctrl_c_is_a_stop_not_a_traceback(monkeypatch):
    def interrupted(prompt=""):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupted)
    with pytest.raises(cli.Cancelled):
        cli._read("anything")


def test_closing_stdin_is_a_stop_not_a_traceback(monkeypatch):
    def eof(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    with pytest.raises(cli.Cancelled):
        cli._read("anything")


# --- Building the profile ----------------------------------------------------


def test_the_questions_produce_a_valid_profile(answers):
    answers(*PROFILE_ANSWERS)
    user = cli.ask_profile()

    assert user.age == 35
    assert user.investment_experience == "intermediate"
    assert user.investment_amount == 5000.0
    assert user.sectors_of_interest == ["renewable energy", "grid storage"]
    assert user.restrictions == ["no fossil fuels"]


def test_a_field_pydantic_rejects_is_asked_again(answers, capsys):
    """Range rules live in UserInput. The CLI's job is to re-ask, not to
    duplicate the bound and let the two drift apart."""
    answers("0", *PROFILE_ANSWERS[1:], "35")
    user = cli.ask_profile()

    assert user.age == 35
    assert "That will not work: age" in capsys.readouterr().out


def test_the_offered_options_come_from_the_model_not_from_a_copy():
    """If someone adds a risk level to UserInput, the CLI must offer it."""
    from typing import get_args

    assert cli.RISK == get_args(UserInput.model_fields["risk_tolerance"].annotation)
    assert cli.EXPERIENCE == get_args(
        UserInput.model_fields["investment_experience"].annotation
    )


def test_every_question_maps_to_a_real_field():
    """A renamed field would otherwise be discovered by a user, at a prompt."""
    for field, _ in cli.QUESTIONS:
        assert field in UserInput.model_fields
    assert {f for f, _ in cli.QUESTIONS} == set(UserInput.model_fields)


# --- Saved profiles ----------------------------------------------------------


def test_a_saved_profile_round_trips(tmp_path, answers):
    answers(*PROFILE_ANSWERS)
    original = cli.ask_profile()

    path = tmp_path / "mine.json"
    path.write_text(json.dumps(original.model_dump()), encoding="utf-8")

    assert cli.load_profile(path) == original


def test_a_missing_profile_file_says_so(tmp_path):
    with pytest.raises(SystemExit, match="No such profile file"):
        cli.load_profile(tmp_path / "nope.json")


def test_a_malformed_profile_file_says_so(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit, match="not valid JSON"):
        cli.load_profile(path)


def test_an_incomplete_profile_lists_what_was_expected(tmp_path):
    path = tmp_path / "partial.json"
    path.write_text(json.dumps({"age": 35}), encoding="utf-8")

    with pytest.raises(SystemExit, match="Expected keys"):
        cli.load_profile(path)


def test_every_shipped_example_profile_loads():
    """These are the demo path. A stale one fails in front of an audience."""
    from config import PROJECT_ROOT

    examples = sorted((PROJECT_ROOT / "examples").glob("*.json"))
    assert examples, "the examples directory should not be empty"
    for path in examples:
        assert isinstance(cli.load_profile(path), UserInput), path


# --- Showing what grounds an exit condition ----------------------------------


def test_a_metric_condition_names_the_metric():
    condition = ExitCondition(condition="debt_to_equity rises above 3", metric="debt_to_equity")
    assert cli._grounds(condition, {}).strip() == (
        "Check: the company's reported debt-to-equity"
    )


def test_a_citation_lines_up_under_itself():
    """A source runs to three lines - headline, publisher, link - and they have
    to align or the citation stops reading as one thing."""
    article = make_article("u9", "Regulator opens probe", source="reuters.com")
    condition = ExitCondition(condition="the probe results in a fine", article_ids=["u9"])

    lines = cli._grounds(condition, {"risk_findings": RiskFindings(articles=[article])})
    indents = {len(ln) - len(ln.lstrip()) for ln in lines.split("\n")[1:]}
    assert len(indents) == 1, "continuation lines must share one indent"
    assert indents.pop() == lines.index("Check:") + len("Check: ")


def test_a_cited_bear_case_article_is_shown_with_its_source():
    article = make_article("u9", "Regulator opens probe", source="reuters.com")
    state = {"risk_findings": RiskFindings(articles=[article])}
    condition = ExitCondition(condition="the probe results in a fine", article_ids=["u9"])

    grounds = cli._grounds(condition, state)
    assert "Regulator opens probe" in grounds
    assert "reuters.com" in grounds
    assert article.url in grounds


def test_a_theme_article_is_found_too(articles):
    """Conditions cite Agent 4's articles OR Agent 2's. Both stores are searched."""
    state = {
        "risk_findings": RiskFindings(),
        "research_findings": ResearchFindings(articles=articles),
    }
    condition = ExitCondition(condition="the order is cancelled", article_ids=["u1"])
    assert "Battery order won by Waaree" in cli._grounds(condition, state)


def test_an_unresolvable_citation_says_so_rather_than_printing_a_hex_string():
    """Silence here would look identical to a citation that worked."""
    condition = ExitCondition(condition="something happens", article_ids=["deadbeefcafe"])
    grounds = cli._grounds(condition, {"risk_findings": RiskFindings()})
    assert "was not kept" in grounds


# --- Printing the decision ---------------------------------------------------


def _recommendation(**overrides) -> Recommendation:
    base = dict(
        ticker="WAAREE",
        name="Waaree Energies",
        thesis="Makes the solar modules the grid buildout consumes.",
        exit_conditions=[
            ExitCondition(condition="debt_to_equity rises above 3.0", metric="debt_to_equity"),
            ExitCondition(condition="the Italian order is cancelled", article_ids=["u2"]),
        ],
        screen_score=0.72,
        verdict="survives",
        exposure="direct",
        themes=["grid storage buildout"],
        evidence_article_ids=["u1"],
        known_risks=["Concentrated in one customer"],
    )
    return Recommendation(**{**base, **overrides})


def test_a_recommendation_prints_its_thesis_and_its_way_out(capsys, articles):
    decision = Decision(recommendations=[_recommendation()])
    state = {"research_findings": ResearchFindings(articles=articles)}

    cli.print_decision(decision, state)
    out = capsys.readouterr().out

    assert "WAAREE" in out
    assert "solar modules" in out
    assert "debt-to-equity rises above 3.0" in out
    assert "Check: the company's reported debt-to-equity" in out
    # The citation is resolved to something a reader could go and open.
    assert "Solar financing secured in Italy" in out
    assert "Concentrated in one customer" in out


def test_recommending_nothing_is_loud_and_carries_its_reason(capsys):
    """The outcome the whole design exists to make possible. A blank screen
    would read as a crash, which is exactly the failure mode being avoided."""
    decision = Decision(
        no_recommendation_reason="All three candidates were disqualified by a critical risk."
    )
    cli.print_decision(decision, {})
    out = capsys.readouterr().out

    assert "NOTHING IS BEING RECOMMENDED" in out
    assert "not a failure" in out
    assert "disqualified by a critical risk" in out


def test_every_excluded_company_is_named_with_its_reason(capsys):
    decision = Decision(
        recommendations=[_recommendation()],
        excluded=[
            ExcludedCompany(ticker="ADANI", name="Adani Green", reason="disqualified_by_risk",
                            detail="A critical governance risk broke the thesis."),
            ExcludedCompany(ticker="TSLA", name="Tesla", reason="outside_top_three"),
        ],
    )
    cli.print_decision(decision, {})
    out = capsys.readouterr().out

    # The enum names are for code to branch on. A reader gets the reason in
    # words, and the stored detail only where it describes the COMPANY.
    assert "ADANI" in out and "disqualified_by_risk" not in out
    assert "A serious problem we found ruled it out." in out
    assert "governance risk" in out
    assert "TSLA" in out and "outside_top_three" not in out
    assert "Ranked just outside the top three." in out


def test_discarded_conditions_are_reported(capsys):
    """A number climbing here means the briefs are being written from memory,
    and the prose above would still read perfectly well."""
    decision = Decision(recommendations=[_recommendation()], conditions_discarded=4)
    cli.print_decision(decision, {})
    assert "4 thing(s) to watch for were left out" in capsys.readouterr().out


def test_the_output_says_it_is_not_advice(capsys):
    cli.print_decision(Decision(recommendations=[_recommendation()]), {})
    assert "not advice" in capsys.readouterr().out.lower()


# --- Exit codes --------------------------------------------------------------


def test_recommending_nothing_exits_zero(capsys):
    """A non-zero code would tell every wrapping script the run had failed."""
    state = {"decision": Decision(no_recommendation_reason="nothing cleared the bar")}
    assert cli.print_outcome(state) == 0


def test_a_recommendation_exits_zero():
    assert cli.print_outcome({"decision": Decision(recommendations=[_recommendation()])}) == 0


def test_a_failed_run_exits_one_and_explains_itself(capsys):
    assert cli.print_outcome({"error": "Research failed: ConnectionError: down"}) == 1
    out = capsys.readouterr().out
    assert "COULD NOT FINISH" in out
    assert "ConnectionError" in out
    assert "check_setup" in out


def test_a_run_with_neither_a_decision_nor_an_error_is_not_silently_a_success(capsys):
    assert cli.print_outcome({"user_input": None}) == 1
    assert "WITHOUT A DECISION" in capsys.readouterr().out


# --- Driving the graph -------------------------------------------------------


def _start(user, thread_id, graph=None):
    """Start a new run. These tests exercise run()'s loop, not persistence, so
    they use the in-memory graph; durability is tested in test_checkpoints.py."""
    return cli.run(
        graph or workflow.investment_graph,
        thread_id,
        {"user_input": user},
        cli.STAGE_LABELS["profile_agent"],
    )


@pytest.fixture
def stub_pipeline(monkeypatch):
    """Replace Agents 2 to 5 so the graph runs end to end with no network."""

    def _install(decision=None):
        monkeypatch.setattr(
            workflow, "research_themes",
            lambda profile, **k: ResearchFindings(articles_retrieved=7, notes="ok"),
        )
        monkeypatch.setattr(
            workflow, "analyse_companies",
            lambda research, **k: CompanyFindings(companies_examined=4, notes="ok"),
        )
        monkeypatch.setattr(
            workflow, "critique_companies", lambda findings, **k: RiskFindings()
        )
        monkeypatch.setattr(
            workflow, "decide",
            lambda companies, risks, profile, research=None: decision
            or Decision(no_recommendation_reason="no candidates were produced"),
        )

    return _install


@pytest.fixture
def always_valid(monkeypatch):
    from models.profile import InvestorProfile

    monkeypatch.setattr(
        workflow, "create_investor_profile",
        lambda user_input, clarifications=None: InvestorProfile(
            **user_input.model_dump(), status="valid"
        ),
    )


def test_a_clean_run_never_asks_a_question(
    always_valid, stub_pipeline, clean_user, answers, capsys
):
    stub_pipeline()
    answers()  # any input() at all is an assertion failure

    state = _start(clean_user, "cli-clean")

    assert "decision" in state
    assert "error" not in state
    assert "[5/5]" in capsys.readouterr().out


def test_a_clarification_answer_is_carried_in_and_the_graph_resumes(
    monkeypatch, stub_pipeline, conflicted_user, answers, capsys
):
    """THE test for this file. Agent 1 stops, the CLI asks, and the run
    continues from exactly where it paused rather than starting over."""
    from models.profile import InvestorProfile

    seen = []

    def blocks_once(user_input, clarifications=None):
        seen.append(list(clarifications or []))
        if clarifications:
            return InvestorProfile(**user_input.model_dump(), status="valid")
        return InvestorProfile(
            **user_input.model_dump(),
            status="needs_clarification",
            clarification_reason="you want technology but ruled technology out",
        )

    monkeypatch.setattr(workflow, "create_investor_profile", blocks_once)
    stub_pipeline()
    answers("drop the restriction")

    state = _start(conflicted_user, "cli-clarify")

    assert seen == [[], ["drop the restriction"]], "the answer must reach Agent 1"
    assert state["clarification_responses"] == ["drop the restriction"]
    assert "decision" in state, "the run must continue past the clarification"

    out = capsys.readouterr().out
    assert "CLARIFICATION NEEDED" in out
    assert "you want technology but ruled technology out" in out
    assert "attempt 1 of" in out


def test_a_blank_clarification_is_refused_rather_than_wasting_an_attempt(
    monkeypatch, stub_pipeline, conflicted_user, answers, capsys
):
    from models.profile import InvestorProfile

    def blocks_once(user_input, clarifications=None):
        if clarifications:
            return InvestorProfile(**user_input.model_dump(), status="valid")
        return InvestorProfile(
            **user_input.model_dump(),
            status="needs_clarification",
            clarification_reason="a conflict",
        )

    monkeypatch.setattr(workflow, "create_investor_profile", blocks_once)
    stub_pipeline()
    answers("", "   ", "keep technology")

    state = _start(conflicted_user, "cli-blank")

    assert state["clarification_responses"] == ["keep technology"]
    assert "rather keep" in capsys.readouterr().out


def test_the_cli_stops_when_the_graph_gives_up(
    monkeypatch, stub_pipeline, conflicted_user, answers
):
    """The loop bound belongs to the graph. The CLI must respect it and not
    keep asking, and must not hang waiting for an answer nobody will give."""
    from models.profile import InvestorProfile

    monkeypatch.setattr(
        workflow, "create_investor_profile",
        lambda user_input, clarifications=None: InvestorProfile(
            **user_input.model_dump(),
            status="needs_clarification",
            clarification_reason="an unresolvable conflict",
        ),
    )
    stub_pipeline()
    limit = get_settings().max_clarification_attempts
    remaining = answers(*["no idea"] * limit)

    state = _start(conflicted_user, "cli-exhausted")

    assert remaining == [], f"expected exactly {limit} questions"
    assert "Could not resolve the profile" in state["error"]
    assert "decision" not in state


def test_a_node_failure_is_reported_as_it_happens(
    always_valid, monkeypatch, clean_user, answers, capsys
):
    monkeypatch.setattr(
        workflow, "research_themes",
        lambda profile, **k: (_ for _ in ()).throw(ConnectionError("news API down")),
    )
    answers()

    state = _start(clean_user, "cli-node-failure")
    out = capsys.readouterr().out

    assert "FAILED" in out
    assert "news API down" in out
    assert cli.print_outcome(state) == 1


# --- main() ------------------------------------------------------------------


def test_main_runs_a_saved_profile_without_asking_anything(
    always_valid, stub_pipeline, answers, capsys
):
    stub_pipeline(Decision(recommendations=[_recommendation()]))
    answers()

    code = cli.main(["--profile", "examples/beginner_renewables.json"])

    assert code == 0
    out = capsys.readouterr().out
    assert "renewable energy" in out
    assert "WAAREE" in out


def test_main_can_save_the_answers_for_next_time(
    always_valid, stub_pipeline, answers, tmp_path, capsys
):
    stub_pipeline()
    saved = tmp_path / "mine.json"
    answers(*PROFILE_ANSWERS)

    assert cli.main(["--save-profile", str(saved)]) == 0
    assert cli.load_profile(saved).sectors_of_interest == [
        "renewable energy",
        "grid storage",
    ]


def test_main_treats_ctrl_c_as_a_stop(monkeypatch, capsys):
    monkeypatch.setattr(
        "builtins.input", lambda prompt="": (_ for _ in ()).throw(KeyboardInterrupt)
    )
    assert cli.main([]) == 1
    assert "Stopped." in capsys.readouterr().out


# --- Saved runs: --list and --resume -----------------------------------------


@pytest.fixture
def db(tmp_path):
    return tmp_path / "runs.sqlite"


@pytest.fixture
def blocks_once(monkeypatch):
    """Agent 1 asks a question the first time and accepts the answer after."""
    from models.profile import InvestorProfile

    def _profile(user_input, clarifications=None):
        if clarifications:
            return InvestorProfile(**user_input.model_dump(), status="valid")
        return InvestorProfile(
            **user_input.model_dump(),
            status="needs_clarification",
            clarification_reason="you want crypto but ruled crypto out",
        )

    monkeypatch.setattr(workflow, "create_investor_profile", _profile)


def _paused_run(db, thread_id="saved-1"):
    """Leave a run paused at a clarification, as a killed process would."""
    import checkpoints

    with checkpoints.open_store(db) as store:
        store.graph.invoke(
            {"user_input": cli.load_profile("examples/conflicted_crypto.json")},
            store.config(thread_id),
        )


def test_listing_an_empty_database_says_so_rather_than_printing_nothing(
    db, answers, capsys
):
    answers()
    assert cli.main(["--db", str(db), "--list"]) == 0
    assert "Nothing saved yet" in capsys.readouterr().out


def test_listing_shows_a_paused_run_with_what_it_was_researching(
    blocks_once, stub_pipeline, db, answers, capsys
):
    """A bare thread id is unusable. The sectors are what make a row
    recognisable as the run you were in the middle of."""
    stub_pipeline()
    _paused_run(db, "saved-1")
    answers()

    assert cli.main(["--db", str(db), "--list"]) == 0
    out = capsys.readouterr().out

    assert "saved-1" in out
    assert "paused" in out
    assert "cryptocurrency" in out
    assert "--resume saved-1" in out


def test_resuming_an_unknown_run_fails_loudly(db, answers, capsys):
    """A typo must not quietly start a new run under the wrong name - which is
    the whole reason resuming is its own flag rather than --thread-id guessing."""
    answers()
    assert cli.main(["--db", str(db), "--resume", "typo-here"]) == 1
    out = capsys.readouterr().out
    assert "No saved run called 'typo-here'" in out
    assert "--list" in out


def test_resuming_re_asks_the_original_question_and_finishes(
    blocks_once, stub_pipeline, db, answers, capsys
):
    """THE test for this feature. A fresh process picks the run up, shows the
    user what conflicted, and carries their answer through to a decision."""
    stub_pipeline(Decision(recommendations=[_recommendation()]))
    _paused_run(db, "saved-1")
    answers("drop the crypto")  # the profile is NOT asked again

    assert cli.main(["--db", str(db), "--resume", "saved-1"]) == 0
    out = capsys.readouterr().out

    assert "Resuming 'saved-1'" in out
    # The original question, not just a bare prompt.
    assert "you want crypto but ruled crypto out" in out
    assert "WAAREE" in out


def test_resuming_does_not_ask_for_the_profile_again(
    blocks_once, stub_pipeline, db, answers
):
    """user_input is already saved. Asking eight questions again would defeat
    the point of having saved anything."""
    stub_pipeline()
    _paused_run(db, "saved-1")
    remaining = answers("drop the crypto")

    cli.main(["--db", str(db), "--resume", "saved-1"])
    assert remaining == [], "exactly one question - the clarification"


def test_resuming_a_finished_run_reprints_it_rather_than_refusing(
    always_valid, stub_pipeline, db, answers, capsys
):
    """"It already finished" is not a useful reply to somebody who wants to see
    the result again."""
    import checkpoints

    stub_pipeline(Decision(recommendations=[_recommendation()]))
    with checkpoints.open_store(db) as store:
        store.graph.invoke(
            {"user_input": cli.load_profile("examples/beginner_renewables.json")},
            store.config("done-1"),
        )
    answers()

    assert cli.main(["--db", str(db), "--resume", "done-1"]) == 0
    out = capsys.readouterr().out
    assert "already finished" in out
    assert "WAAREE" in out


def test_resume_and_profile_are_refused_together(db):
    """--resume continues a saved profile; supplying another one is a mistake
    worth stopping rather than silently ignoring."""
    with pytest.raises(SystemExit):
        cli.main(["--db", str(db), "--resume", "x", "--profile", "y.json"])


def test_a_run_prints_the_id_needed_to_resume_it(
    always_valid, stub_pipeline, db, answers, capsys
):
    """A durable checkpoint nobody can name is not recoverable."""
    stub_pipeline()
    answers()

    cli.main([
        "--db", str(db),
        "--thread-id", "nilesh-1",
        "--profile", "examples/beginner_renewables.json",
    ])
    out = capsys.readouterr().out
    assert "Run id: nilesh-1" in out
    assert "--resume nilesh-1" in out


def test_stopping_says_the_run_was_saved(monkeypatch, db, capsys):
    """The message has to change now that it is true - before checkpointing,
    stopping really did throw the run away."""
    monkeypatch.setattr(
        "builtins.input", lambda prompt="": (_ for _ in ()).throw(KeyboardInterrupt)
    )
    assert cli.main(["--db", str(db)]) == 1
    assert "The run is saved" in capsys.readouterr().out


# --- Fixes found by review ---------------------------------------------------


def test_reusing_a_thread_id_for_a_new_run_is_refused(
    always_valid, stub_pipeline, db, answers, capsys
):
    """Found by review, and worse than it looked.

    LangGraph merges new input into an EXISTING thread, so a second run under
    the same id inherits the first run's clarification_responses. Reproduced:
    runs 2, 3 and 4 returned "profile valid" WITHOUT ASKING, because Agent 1 was
    handed a stale clarification and believed the conflict resolved - a
    contradictory profile straight through the one gate built to stop it.
    """
    stub_pipeline()
    answers()

    first = cli.main(["--db", str(db), "--thread-id", "reused",
                      "--profile", "examples/beginner_renewables.json"])
    assert first == 0

    second = cli.main(["--db", str(db), "--thread-id", "reused",
                       "--profile", "examples/beginner_renewables.json"])
    out = capsys.readouterr().out

    assert second == 1
    assert "already exists" in out
    assert "--resume reused" in out, "must point at the supported way to continue"


def test_ctrl_c_during_the_run_is_not_a_traceback(
    always_valid, monkeypatch, db, answers, capsys
):
    """_read() converts Ctrl-C at a PROMPT into Cancelled, but Ctrl-C during
    graph.stream never passes through _read. That is the three-minute window
    where it is most likely, and a traceback there contradicts the promise the
    docstring and README both make."""
    def interrupted(profile, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(workflow, "research_themes", interrupted)
    answers()

    code = cli.main(["--db", str(db), "--profile", "examples/beginner_renewables.json"])
    out = capsys.readouterr().out

    assert code == 1
    assert "The run is saved" in out


def test_a_long_url_is_printed_whole(articles):
    """textwrap breaks a long URL mid-token, and a link the reader cannot copy
    defeats the only reason the grounds block exists."""
    from models.research import Article, ResearchFindings
    from models.decision import ExitCondition

    long_url = "https://example.com/" + "a" * 90 + "/story"
    article = Article(
        uuid="u9", title="A probe was opened", description="", snippet="",
        url=long_url, source="reuters.com",
        published_at=articles[0].published_at,
    )
    condition = ExitCondition(condition="the probe concludes", article_ids=["u9"])

    rendered = cli._grounds(condition, {"research_findings": ResearchFindings(articles=[article])})
    assert long_url in rendered, "the URL must survive intact on one line"


# --- the recorded demo -------------------------------------------------------
#
# The first thing anyone does with a repository is try to run it, and this one
# needs three API keys before it prints a line. `--demo` renders a REAL recorded
# run with none of them. The tests that matter are the two that stop it becoming
# a lie: that it stays loadable as the schemas move, and that it needs no config.


def test_the_shipped_recording_still_loads_through_the_current_models():
    """The guard against silent rot.

    A hand-written fixture can say anything and goes stale the moment a model
    gains a required field - and nothing would notice, because the demo would
    keep printing until someone read it closely. Validating the shipped file
    through the same Pydantic models the graph writes means a schema change
    breaks this test rather than the front page of the repository.
    """
    code = cli.run_demo()

    assert code == 0


def test_the_demo_prints_a_real_brief(capsys):
    cli.run_demo()
    out = capsys.readouterr().out

    assert "WORTH A LOOK" in out
    # Whichever company the recording happens to hold, the brief must carry the
    # things that make it worth showing: a price, and a date to look again.
    assert "per share" in out
    assert "Look at this again on" in out
    # The grounded exit conditions are the point of the whole project; a demo
    # that printed a thesis and no grounds would sell the wrong thing.
    assert "What would mean the idea has stopped working" in out
    assert "Check:" in out


def test_the_demo_says_it_is_a_recording(capsys):
    """It must never read as a live run. Someone showing this to another person
    should not have to add the caveat out loud."""
    cli.run_demo()
    out = capsys.readouterr().out

    assert "A RECORDED RUN" in out
    assert "No API key" in out


def test_a_missing_recording_explains_itself(tmp_path, capsys):
    code = cli.run_demo(tmp_path / "gone.json")

    assert code == 1
    assert "missing" in capsys.readouterr().out


def test_the_demo_refuses_to_be_combined_with_a_real_run():
    """--demo reads a file and --profile runs the pipeline; silently ignoring
    one of them would be the worst of the three options."""
    with pytest.raises(SystemExit):
        cli.main(["--demo", "--profile", "examples/beginner_renewables.json"])


def test_the_demo_never_builds_the_graph(monkeypatch):
    """It has to work on a machine with no configuration at all.

    Building the graph imports every agent, and an agent that read settings at
    import time would make the demo fail in exactly the situation it exists for:
    a stranger who has cloned the repository and not signed up for anything.
    """
    def explode(*args, **kwargs):
        raise AssertionError("the demo opened the checkpoint store")

    monkeypatch.setattr(cli.checkpoints, "open_store", explode)

    assert cli.main(["--demo"]) == 0


# --- Prices, and what an amount would buy -------------------------------------
#
# The one figure in the brief a beginner might act on directly, so the rules
# about when it is NOT shown matter more than the arithmetic.


def _affordable(rec, user):
    return cli._affordable_shares(rec, user)


def _priced(currency="USD", amount=100.0, shares=None, own=None, **kw):
    from models.companies import MarketPrice
    rec = _recommendation(**kw)
    rec.price = MarketPrice(
        amount=amount, currency=currency,
        as_of=datetime(2026, 8, 26, tzinfo=timezone.utc),
    )
    rec.shares_affordable = shares
    rec.price_in_investor_currency = own
    return rec


def _investor(currency="USD", amount=5000.0):
    return UserInput(
        age=30, investment_experience="beginner", risk_tolerance="moderate",
        investment_amount=amount, investment_currency=currency,
        investment_window="within 3 months", holding_period="3-5 years",
        sectors_of_interest=["technology"], restrictions=[],
    )


def test_the_stored_share_count_is_what_gets_printed():
    """The arithmetic happens in Agent 5, next to the price it came from. This
    layer only formats, so it can run with no network - which is what lets the
    demo and a resumed run print at all."""
    line = _affordable(_priced(shares=50), _investor("USD", 5000.0))

    assert "50 shares" in line


def test_zero_shares_is_an_answer_not_a_silence():
    """A computed zero means one share costs more than the whole amount, which
    a reader cannot work out from a price in a currency they do not use."""
    line = _affordable(_priced(shares=0), _investor("USD", 5000.0))

    assert "costs more than" in line


def test_an_uncomputable_count_says_nothing():
    """None means no price, no stated currency or no exchange rate. The brief
    shows the price alone rather than guessing."""
    assert _affordable(_priced(shares=None), _investor("USD")) is None


def test_no_stated_currency_says_nothing():
    investor = _investor()
    investor.investment_currency = None

    assert _affordable(_priced(shares=50), investor) is None


def test_the_review_date_is_three_months_out_not_the_holding_period():
    """Deliberately not derived from holding_period: it is free text, and
    someone holding for five years should not first check back in five years."""
    assert cli._next_review(date(2026, 8, 26)) == date(2026, 11, 25)


def test_a_replayed_run_says_its_prices_are_old(capsys):
    cli.print_as_of_notice(datetime(2026, 8, 26, tzinfo=timezone.utc), "It was recorded")
    out = capsys.readouterr().out

    assert "26 Aug 2026" in out
    assert "will have moved since" in out


def test_an_unparseable_timestamp_is_passed_over_quietly(capsys):
    """The notice is a courtesy. Failing a whole run over a date it could not
    format would be a poor trade."""
    cli.print_as_of_notice("not a date", "It was recorded")

    assert capsys.readouterr().out == ""


# --- Choosing what to research ------------------------------------------------
#
# The highest-signal answer in the run, and the one a beginner is least equipped
# to give. The menu exists so nobody faces a blank prompt; the examples beside
# each entry exist so the menu does not make everyone broader, which would be
# worse than the blank. Narrower researches better: "semiconductors" produced
# this project's best brief and "renewable energy" produced an empty one.


def test_a_number_becomes_the_providers_own_sector_name(answers):
    """Resolved to the wording the company data provider reports, so a sector
    picked here is the same string Agent 3 later sees on a resolved company."""
    answers("1")

    assert cli._ask_sectors() == ["Technology"]


def test_several_numbers_are_all_resolved(answers):
    answers("1, 5")

    assert cli._ask_sectors() == ["Technology", "Utilities"]


def test_typed_text_is_kept_exactly_as_written(answers):
    """Not corrected towards a menu entry. Someone who writes "grid storage"
    has given something better than any option on the list."""
    answers("grid storage")

    assert cli._ask_sectors() == ["grid storage"]


def test_numbers_and_words_can_be_mixed(answers):
    answers("1, grid storage")

    assert cli._ask_sectors() == ["Technology", "grid storage"]


@pytest.mark.parametrize("out_of_range", ["0", "12", "99"])
def test_a_number_outside_the_menu_is_treated_as_text(answers, out_of_range):
    """Silently dropping it would lose the answer; guessing which sector was
    meant would invent one. Passing it through lets Agent 1 see it."""
    answers(out_of_range)

    assert cli._ask_sectors() == [out_of_range]


def test_the_menu_is_printed_with_a_narrower_example_each(answers, capsys):
    answers("1")
    cli._ask_sectors()
    out = capsys.readouterr().out

    for name, example in cli.SECTORS:
        assert name in out
        assert example in out


def test_every_sector_offered_is_one_the_provider_reports():
    """These are Yahoo's names - "Consumer Cyclical", "Financial Services" - and
    not GICS's, because matching the provider means no translation later."""
    names = {name for name, _ in cli.SECTORS}

    assert {"Technology", "Healthcare", "Consumer Cyclical",
            "Financial Services", "Utilities"} <= names
    assert len(cli.SECTORS) == 11
