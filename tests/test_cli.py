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
    assert cli._grounds(condition, {}).strip() == "grounds: metric debt_to_equity"


def test_a_citation_lines_up_under_itself():
    """A source runs to three lines - headline, publisher, link - and they have
    to align or the citation stops reading as one thing."""
    article = make_article("u9", "Regulator opens probe", source="reuters.com")
    condition = ExitCondition(condition="the probe results in a fine", article_ids=["u9"])

    lines = cli._grounds(condition, {"risk_findings": RiskFindings(articles=[article])})
    indents = {len(ln) - len(ln.lstrip()) for ln in lines.split("\n")[1:]}
    assert len(indents) == 1, "continuation lines must share one indent"
    assert indents.pop() == lines.index("grounds:") + len("grounds: ")


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
    assert "source not retained" in grounds


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
    assert "debt_to_equity rises above 3.0" in out
    assert "metric debt_to_equity" in out
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

    assert "ADANI" in out and "disqualified_by_risk" in out
    assert "governance risk" in out
    assert "TSLA" in out and "outside_top_three" in out


def test_discarded_conditions_are_reported(capsys):
    """A number climbing here means the briefs are being written from memory,
    and the prose above would still read perfectly well."""
    decision = Decision(recommendations=[_recommendation()], conditions_discarded=4)
    cli.print_decision(decision, {})
    assert "4 exit condition(s) discarded" in capsys.readouterr().out


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
            lambda companies, risks, profile: decision
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

    state = cli.run(clean_user, "cli-clean")

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

    state = cli.run(conflicted_user, "cli-clarify")

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

    state = cli.run(conflicted_user, "cli-blank")

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

    state = cli.run(conflicted_user, "cli-exhausted")

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

    state = cli.run(clean_user, "cli-node-failure")
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
