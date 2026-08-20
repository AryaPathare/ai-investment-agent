"""Tests for the LangGraph workflow: routing decisions and loop termination.

The agent is replaced by a fake throughout, which makes these tests fast and
deterministic. That matters most for the loop-bound test: proving the graph
terminates should not depend on an LLM happening to behave a certain way.
"""

import pytest
from langgraph.types import Command

import workflow
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
    always_valid, fake_research, clean_user
):
    """A valid profile now flows on into research, so that must be stubbed too."""
    fake_research()
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


def test_finding_no_themes_is_not_an_error(always_valid, fake_research, clean_user):
    """Returning nothing is a designed outcome, so `error` must stay unset."""
    from models.research import ResearchFindings

    fake_research(ResearchFindings(articles_retrieved=4, notes="Nothing cleared the bar."))
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
