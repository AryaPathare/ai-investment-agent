"""Tests for the LangGraph workflow: routing decisions and loop termination.

The agent is replaced by a fake throughout, which makes these tests fast and
deterministic. That matters most for the loop-bound test: proving the graph
terminates should not depend on an LLM happening to behave a certain way.
"""

import pytest
from langgraph.types import Command

import workflow
from models.decision import Decision
from models.risk import RiskFindings
from models.profile import InvestorProfile
from workflow import investment_graph, profile_node, route_profile

# --- route_profile: a pure function, so it can be tested directly -----------


def test_routes_valid_profile_to_the_end(valid_profile):
    assert route_profile({"investor_profile": valid_profile}) == "valid"


def test_routes_to_clarification_on_first_conflict(blocked_profile):
    state = {"investor_profile": blocked_profile}
    assert route_profile(state) == "clarification"


def test_keeps_asking_while_under_the_limit(blocked_profile):
    state = {"investor_profile": blocked_profile, "clarification_attempts": 2}
    assert route_profile(state) == "clarification"


def test_gives_up_once_the_limit_is_reached(blocked_profile):
    """The termination guarantee, checked directly."""
    state = {"investor_profile": blocked_profile, "clarification_attempts": 3}
    assert route_profile(state) == "exhausted"


def test_gives_up_beyond_the_limit(blocked_profile):
    state = {"investor_profile": blocked_profile, "clarification_attempts": 99}
    assert route_profile(state) == "exhausted"


def test_errors_are_checked_before_anything_else(blocked_profile):
    """An error short-circuits: no profile lookup, no clarification loop."""
    assert route_profile({"error": "boom"}) == "failed"


# --- profile_node: failure handling -----------------------------------------


def test_profile_node_records_errors_instead_of_raising(monkeypatch, clean_user):
    def boom(*args, **kwargs):
        raise ConnectionError("Groq unreachable after 3 retries")

    monkeypatch.setattr(workflow, "create_investor_profile", boom)
    result = profile_node({"user_input": clean_user})

    assert "investor_profile" not in result
    assert "ConnectionError" in result["error"]
    assert "Groq unreachable" in result["error"]


def test_profile_node_passes_the_whole_clarification_history(monkeypatch, clean_user):
    seen = {}

    def capture(user_input, clarifications):
        seen["clarifications"] = clarifications
        return InvestorProfile(**user_input.model_dump(), status="valid")

    monkeypatch.setattr(workflow, "create_investor_profile", capture)
    profile_node({"user_input": clean_user, "clarification_responses": ["a", "b"]})

    assert seen["clarifications"] == ["a", "b"]


# --- The full graph ----------------------------------------------------------


@pytest.fixture
def always_blocked(monkeypatch, blocked_profile):
    """An agent that never accepts the profile, however the user replies."""
    monkeypatch.setattr(
        workflow, "create_investor_profile", lambda *a, **k: blocked_profile
    )


@pytest.fixture
def always_valid(monkeypatch):
    def _valid(user_input, clarifications=None):
        return InvestorProfile(**user_input.model_dump(), status="valid")

    monkeypatch.setattr(workflow, "create_investor_profile", _valid)


def _run(user, thread_id):
    return investment_graph.invoke(
        {"user_input": user}, {"configurable": {"thread_id": thread_id}}
    )


def test_clean_profile_completes_without_interruption(
    always_valid, fake_research, fake_companies, clean_user
):
    """A valid profile flows on through research AND company analysis, so both
    must be stubbed. Each agent added to the graph extends this reach."""
    fake_research()
    fake_companies()
    result = _run(clean_user, "t-clean")
    assert "__interrupt__" not in result
    assert result["investor_profile"].status == "valid"
    assert "error" not in result


def test_loop_terminates_when_clarification_never_succeeds(always_blocked, conflicted_user):
    """THE critical test: an uncooperative model must not loop forever.

    Before the fix this ran until the API budget was exhausted. The safety valve
    below fails the test rather than hanging CI if the bound ever regresses.
    """
    config_ = {"configurable": {"thread_id": "t-loop"}}
    result = investment_graph.invoke({"user_input": conflicted_user}, config_)

    rounds = 0
    while "__interrupt__" in result:
        rounds += 1
        assert rounds <= 10, "clarification loop did not terminate"
        result = investment_graph.invoke(Command(resume="I don't know"), config_)

    assert rounds == 3, f"expected 3 attempts, got {rounds}"
    assert "Could not resolve the profile after 3" in result["error"]


def test_every_clarification_is_retained(always_blocked, conflicted_user):
    """The reducer must accumulate; a plain field would keep only the last."""
    config_ = {"configurable": {"thread_id": "t-accumulate"}}
    result = investment_graph.invoke({"user_input": conflicted_user}, config_)

    replies = ["first reply", "second reply", "third reply"]
    for reply in replies:
        if "__interrupt__" not in result:
            break
        result = investment_graph.invoke(Command(resume=reply), config_)

    assert result["clarification_responses"] == replies
    assert result["clarification_attempts"] == 3


def test_the_user_is_told_which_attempt_they_are_on(always_blocked, conflicted_user):
    config_ = {"configurable": {"thread_id": "t-progress"}}
    result = investment_graph.invoke({"user_input": conflicted_user}, config_)

    payload = result["__interrupt__"][0].value
    assert payload["attempt"] == 1
    assert payload["max_attempts"] == 3
    assert payload["reason"]


def test_graph_ends_cleanly_when_the_model_is_down(monkeypatch, clean_user):
    monkeypatch.setattr(
        workflow,
        "create_investor_profile",
        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("down")),
    )
    result = _run(clean_user, "t-down")

    assert "__interrupt__" not in result
    assert "investor_profile" not in result
    assert "ConnectionError" in result["error"]


# --- Agent 2 in the graph ----------------------------------------------------


@pytest.fixture
def fake_research(monkeypatch):
    """Replace Agent 2 with a fake that records whether it ran."""
    from models.research import ResearchFindings

    calls = []

    def _install(findings=None, error=None):
        def fake(profile, **kwargs):
            calls.append(profile)
            if error is not None:
                raise error
            return findings if findings is not None else ResearchFindings(
                articles_retrieved=7, notes="ok"
            )

        monkeypatch.setattr(workflow, "research_themes", fake)
        return calls

    return _install


def test_a_valid_profile_flows_into_research(always_valid, fake_research, clean_user):
    calls = fake_research()
    result = _run(clean_user, "t-research")

    assert len(calls) == 1, "research should have run exactly once"
    assert "research_findings" in result
    assert result["research_findings"].articles_retrieved == 7


def test_research_does_not_run_while_clarification_is_pending(
    always_blocked, fake_research, conflicted_user
):
    """Researching a contradictory profile would spend requests on ruled-out areas."""
    calls = fake_research()
    result = investment_graph.invoke(
        {"user_input": conflicted_user},
        {"configurable": {"thread_id": "t-no-research-yet"}},
    )

    assert "__interrupt__" in result
    assert calls == [], "research must wait for a valid profile"


def test_research_never_runs_when_clarification_is_exhausted(
    always_blocked, fake_research, conflicted_user
):
    calls = fake_research()
    config_ = {"configurable": {"thread_id": "t-exhausted-no-research"}}
    result = investment_graph.invoke({"user_input": conflicted_user}, config_)

    while "__interrupt__" in result:
        result = investment_graph.invoke(Command(resume="no idea"), config_)

    assert calls == []
    assert "research_findings" not in result
    assert "error" in result


def test_research_never_runs_when_the_profile_agent_failed(monkeypatch, fake_research, clean_user):
    calls = fake_research()
    monkeypatch.setattr(
        workflow, "create_investor_profile",
        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("down")),
    )
    result = _run(clean_user, "t-profile-down")

    assert calls == []
    assert "ConnectionError" in result["error"]


def test_a_research_failure_ends_the_graph_cleanly(always_valid, fake_research, clean_user):
    """The news API being down should not produce a traceback."""
    fake_research(error=ConnectionError("news API unreachable"))
    result = _run(clean_user, "t-research-down")

    assert "research_findings" not in result
    assert "Research failed" in result["error"]
    assert "ConnectionError" in result["error"]


def test_finding_no_themes_is_not_an_error(
    always_valid, fake_research, fake_companies, clean_user
):
    """Returning nothing is a designed outcome, so `error` must stay unset."""
    from models.research import ResearchFindings

    fake_research(ResearchFindings(articles_retrieved=4, notes="Nothing cleared the bar."))
    fake_companies()
    result = _run(clean_user, "t-nothing-found")

    assert result["research_findings"].found_nothing is True
    assert "error" not in result


def test_research_receives_the_clarified_profile(
    monkeypatch, fake_research, conflicted_user
):
    """Agent 2 must see the profile AFTER clarification, not the original input."""
    from models.profile import InvestorProfile

    resolved = InvestorProfile(
        **{**conflicted_user.model_dump(), "restrictions": []}, status="valid"
    )
    monkeypatch.setattr(workflow, "create_investor_profile", lambda *a, **k: resolved)
    calls = fake_research()

    _run(conflicted_user, "t-clarified-profile")

    assert calls[0].restrictions == [], "research got the pre-clarification profile"


# --- Agent 3 in the graph ----------------------------------------------------


@pytest.fixture
def fake_companies(monkeypatch):
    """Replace Agent 3 with a fake that records whether it ran."""
    from models.companies import CompanyFindings

    calls = []

    def _install(findings=None, error=None):
        def fake(research, **kwargs):
            calls.append(research)
            if error is not None:
                raise error
            return findings if findings is not None else CompanyFindings(
                mentions_extracted=5, companies_examined=3
            )

        monkeypatch.setattr(workflow, "analyse_companies", fake)
        return calls

    return _install


def test_research_flows_into_company_analysis(
    always_valid, fake_research, fake_companies, clean_user
):
    company_calls = fake_companies()
    fake_research()
    result = _run(clean_user, "t-companies")

    assert len(company_calls) == 1
    assert "company_findings" in result
    assert "error" not in result


def test_company_analysis_receives_the_research_findings(
    always_valid, fake_research, fake_companies, clean_user
):
    """Agent 3 must see what Agent 2 produced, not the raw profile."""
    from models.research import ResearchFindings

    research = ResearchFindings(articles_retrieved=11, notes="from agent 2")
    fake_research(research)
    company_calls = fake_companies()

    _run(clean_user, "t-handoff")
    assert company_calls[0].articles_retrieved == 11


def test_company_analysis_does_not_run_when_research_failed(
    always_valid, fake_research, fake_companies, clean_user
):
    """No point looking up companies from research that never happened."""
    company_calls = fake_companies()
    fake_research(error=ConnectionError("news API down"))

    result = _run(clean_user, "t-research-failed")
    assert company_calls == []
    assert "company_findings" not in result
    assert "Research failed" in result["error"]


def test_company_analysis_does_not_run_without_a_valid_profile(
    always_blocked, fake_research, fake_companies, conflicted_user
):
    company_calls = fake_companies()
    fake_research()
    result = investment_graph.invoke(
        {"user_input": conflicted_user},
        {"configurable": {"thread_id": "t-blocked-no-companies"}},
    )
    assert "__interrupt__" in result
    assert company_calls == []


def test_finding_no_themes_still_runs_company_analysis(
    always_valid, fake_research, fake_companies, clean_user
):
    """Empty research is a real result, and Agent 3 reports why it found nothing
    rather than the key being silently absent from state."""
    from models.companies import CompanyFindings
    from models.research import ResearchFindings

    fake_research(ResearchFindings(notes="nothing cleared the bar"))
    company_calls = fake_companies(
        CompanyFindings(notes="No research themes to analyse.")
    )

    result = _run(clean_user, "t-empty-research")
    assert len(company_calls) == 1
    assert result["company_findings"].found_nothing
    assert "error" not in result


def test_a_company_analysis_failure_ends_the_graph_cleanly(
    always_valid, fake_research, fake_companies, clean_user
):
    """Two providers and a model call sit behind this node; any can be down."""
    fake_research()
    fake_companies(error=ConnectionError("FMP unreachable"))

    result = _run(clean_user, "t-companies-down")
    assert "company_findings" not in result
    assert "Company analysis failed" in result["error"]
    assert "__interrupt__" not in result


def test_finding_no_companies_is_not_an_error(
    always_valid, fake_research, fake_companies, clean_user
):
    """Themes can be real while no company alongside them is investable."""
    from models.companies import CompanyFindings

    fake_research()
    fake_companies(CompanyFindings(mentions_extracted=6, companies_examined=4,
                                   notes="none were investable"))

    result = _run(clean_user, "t-no-companies")
    assert result["company_findings"].found_nothing
    assert "error" not in result


def test_the_full_chain_runs_in_order(
    always_valid, fake_research, fake_companies, clean_user
):
    """Profile -> research -> companies, all three landing in state."""
    fake_research()
    fake_companies()
    result = _run(clean_user, "t-full-chain")

    assert result["investor_profile"].status == "valid"
    assert "research_findings" in result
    assert "company_findings" in result
    assert "error" not in result


# --- Agent 4: the risk critic ------------------------------------------------


@pytest.fixture
def fake_critic(monkeypatch):
    calls = []

    def _install(findings=None, error=None):
        def fake(company_findings, **kwargs):
            calls.append(company_findings)
            if error is not None:
                raise error
            return findings if findings is not None else RiskFindings(
                articles_retrieved=4
            )

        monkeypatch.setattr(workflow, "critique_companies", fake)
        return calls

    return _install


def test_company_analysis_flows_into_the_risk_critic(
    always_valid, fake_research, fake_companies, fake_critic, clean_user
):
    fake_research()
    fake_companies()
    critic_calls = fake_critic()

    result = _run(clean_user, "t-critic")

    assert len(critic_calls) == 1
    assert "risk_findings" in result
    assert "error" not in result


def test_the_critic_receives_the_company_findings(
    always_valid, fake_research, fake_companies, fake_critic, clean_user
):
    """Agent 4 must see what Agent 3 produced, not the research."""
    from models.companies import CompanyFindings

    fake_research()
    fake_companies(CompanyFindings(mentions_extracted=9, companies_examined=7))
    critic_calls = fake_critic()

    _run(clean_user, "t-critic-handoff")
    assert critic_calls[0].companies_examined == 7


def test_the_critic_does_not_run_when_company_analysis_failed(
    always_valid, fake_research, fake_companies, fake_critic, clean_user
):
    fake_research()
    fake_companies(error=ConnectionError("FMP unreachable"))
    critic_calls = fake_critic()

    result = _run(clean_user, "t-critic-skipped")

    assert critic_calls == []
    assert "risk_findings" not in result
    assert "Company analysis failed" in result["error"]


def test_finding_no_companies_still_runs_the_critic(
    always_valid, fake_research, fake_companies, fake_critic, clean_user
):
    """The critic records that there was nothing to criticise. Skipping the
    node would leave the key missing, which Agent 5 cannot tell apart from
    "the critic has not run yet"."""
    from models.companies import CompanyFindings

    fake_research()
    fake_companies(CompanyFindings(mentions_extracted=6, companies_examined=4))
    critic_calls = fake_critic()

    result = _run(clean_user, "t-critic-nothing")

    assert len(critic_calls) == 1
    assert "risk_findings" in result
    assert "error" not in result


def test_a_critic_failure_ends_the_graph_cleanly(
    always_valid, fake_research, fake_companies, fake_critic, clean_user
):
    """A news provider and one model call per candidate sit behind this node."""
    fake_research()
    fake_companies()
    fake_critic(error=ConnectionError("news provider unreachable"))

    result = _run(clean_user, "t-critic-down")

    assert "risk_findings" not in result
    assert "Risk critique failed" in result["error"]
    assert "__interrupt__" not in result


def test_finding_no_risks_is_not_an_error(
    always_valid, fake_research, fake_companies, fake_critic, clean_user
):
    """Every candidate withstanding criticism is a legitimate outcome."""
    fake_research()
    fake_companies()
    fake_critic(RiskFindings(critiques=[], notes="nothing to criticise"))

    result = _run(clean_user, "t-no-risks")
    assert result["risk_findings"].found_nothing
    assert "error" not in result


# --- Agent 5: the decision ---------------------------------------------------


@pytest.fixture
def fake_decider(monkeypatch):
    calls = []

    def _install(decision=None, error=None):
        def fake(companies, risks, profile):
            calls.append((companies, risks, profile))
            if error is not None:
                raise error
            return decision if decision is not None else Decision(
                no_recommendation_reason="nothing cleared the bar"
            )

        monkeypatch.setattr(workflow, "decide", fake)
        return calls

    return _install


def test_the_critic_flows_into_the_decision(
    always_valid, fake_research, fake_companies, fake_critic, fake_decider, clean_user
):
    fake_research()
    fake_companies()
    fake_critic()
    decide_calls = fake_decider()

    result = _run(clean_user, "t-decide")

    assert len(decide_calls) == 1
    assert "decision" in result
    assert "error" not in result


def test_the_decision_receives_candidates_criticism_and_the_profile(
    always_valid, fake_research, fake_companies, fake_critic, fake_decider, clean_user
):
    """The only node needing three pieces of state. The profile matters: the
    investor's restrictions are re-checked at this last gate."""
    from models.companies import CompanyFindings
    from models.risk import RiskFindings

    fake_research()
    fake_companies(CompanyFindings(companies_examined=7))
    fake_critic(RiskFindings(articles_retrieved=11))
    decide_calls = fake_decider()

    _run(clean_user, "t-decide-handoff")
    companies, risks, profile = decide_calls[0]

    assert companies.companies_examined == 7
    assert risks.articles_retrieved == 11
    assert profile.status == "valid"


def test_the_decision_does_not_run_when_the_critic_failed(
    always_valid, fake_research, fake_companies, fake_critic, fake_decider, clean_user
):
    fake_research()
    fake_companies()
    fake_critic(error=ConnectionError("news provider unreachable"))
    decide_calls = fake_decider()

    result = _run(clean_user, "t-decide-skipped")

    assert decide_calls == []
    assert "decision" not in result
    assert "Risk critique failed" in result["error"]


def test_a_decision_failure_ends_the_graph_cleanly(
    always_valid, fake_research, fake_companies, fake_critic, fake_decider, clean_user
):
    """Up to three model calls sit behind this node."""
    fake_research()
    fake_companies()
    fake_critic()
    fake_decider(error=ConnectionError("model unreachable"))

    result = _run(clean_user, "t-decide-down")

    assert "decision" not in result
    assert "Decision failed" in result["error"]
    assert "__interrupt__" not in result


def test_recommending_nothing_is_a_result_not_an_error(
    always_valid, fake_research, fake_companies, fake_critic, fake_decider, clean_user
):
    """The outcome the whole design exists to make possible."""
    fake_research()
    fake_companies()
    fake_critic()
    fake_decider(Decision(no_recommendation_reason="every candidate was disqualified"))

    result = _run(clean_user, "t-nothing")

    assert result["decision"].recommended_nothing
    assert result["decision"].no_recommendation_reason
    assert "error" not in result


# --- The checkpointer's type registry ----------------------------------------


def _models_reachable_from(annotation, seen: set) -> set:
    """Every BaseModel class reachable from a type annotation, recursively.

    Walks through list[...], X | None, Annotated[...] and nested model fields,
    which is how the types actually appear: RiskFindings holds
    list[CandidateCritique], which holds list[Risk].
    """
    from typing import get_args

    from pydantic import BaseModel

    found = set()
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation in seen:
            return found
        seen.add(annotation)
        found.add(annotation)
        for field in annotation.model_fields.values():
            found |= _models_reachable_from(field.annotation, seen)
        return found

    for arg in get_args(annotation):
        found |= _models_reachable_from(arg, seen)
    return found


def test_every_type_that_reaches_state_is_registered_with_the_checkpointer():
    """The bug this exists to prevent, stated once so it cannot come back.

    An unregistered Pydantic type does not raise. It round-trips through the
    checkpointer as a plain dict and fails later, somewhere else, on the first
    property access - which is how Agents 4 and 5 shipped unregistered and the
    whole suite stayed green: nothing read state back out until the CLI did.

    Every future agent adds types to InvestmentState. This is what makes
    forgetting them a red test instead of an AttributeError in front of a user.
    """
    from typing import get_type_hints

    from models.state import InvestmentState
    from workflow import CHECKPOINTED_TYPES

    seen: set = set()
    required: set = set()
    for annotation in get_type_hints(InvestmentState, include_extras=True).values():
        required |= _models_reachable_from(annotation, seen)

    missing = sorted(cls.__name__ for cls in required - set(CHECKPOINTED_TYPES))
    assert not missing, (
        f"these types reach graph state but are not in CHECKPOINTED_TYPES: "
        f"{missing}. They will come back from the checkpointer as dicts."
    )


def test_the_registry_has_no_types_that_cannot_reach_state():
    """The other direction: a registered type that nothing uses is dead weight,
    and usually means a model was renamed and the old name left behind."""
    from typing import get_type_hints

    from models.state import InvestmentState
    from workflow import CHECKPOINTED_TYPES

    seen: set = set()
    reachable: set = set()
    for annotation in get_type_hints(InvestmentState, include_extras=True).values():
        reachable |= _models_reachable_from(annotation, seen)

    extra = sorted(cls.__name__ for cls in set(CHECKPOINTED_TYPES) - reachable)
    assert not extra, f"registered but unreachable from state: {extra}"
