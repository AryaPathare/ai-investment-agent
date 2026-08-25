"""Tests for Agent 1's orchestration logic — with the LLM replaced by a fake.

What is tested here is OUR code: is the prompt assembled correctly, is the full
clarification history passed along, is the result composed from trusted input.

What is NOT tested here is whether the model gives good answers. That is model
behaviour, it is not deterministic, and it belongs in the eval suite.

These tests are only possible because config.py made the LLM lazy — importing
this agent no longer requires an API key.
"""

import pytest

from agents import profile_agent
from models.profile import InvestorProfile, ProfileAssessment


class FakeStructuredLLM:
    """Stands in for the model. Records what it was asked, returns a fixed answer."""

    def __init__(self, assessment: ProfileAssessment):
        self._assessment = assessment
        self.received_messages = None

    def invoke(self, messages):
        self.received_messages = messages
        return self._assessment


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace the real model with a fake that returns 'valid'."""

    def _install(assessment=None):
        fake = FakeStructuredLLM(assessment or ProfileAssessment(status="valid"))
        monkeypatch.setattr(profile_agent, "_structured_llm", lambda: fake)
        return fake

    return _install


def _human_message(fake) -> str:
    """The text actually sent to the model as the human turn."""
    return dict(fake.received_messages)["human"]


def test_returns_a_profile_built_from_the_user_input(fake_llm, clean_user):
    fake_llm()
    profile = profile_agent.create_investor_profile(clean_user)

    assert isinstance(profile, InvestorProfile)
    assert profile.status == "valid"
    assert profile.age == clean_user.age
    assert profile.sectors_of_interest == clean_user.sectors_of_interest


def test_sends_the_user_data_to_the_model(fake_llm, clean_user):
    fake = fake_llm()
    profile_agent.create_investor_profile(clean_user)

    message = _human_message(fake)
    assert "renewable energy" in message
    assert str(clean_user.age) in message


def test_system_prompt_is_sent_first(fake_llm, clean_user):
    fake = fake_llm()
    profile_agent.create_investor_profile(clean_user)

    role, content = fake.received_messages[0]
    assert role == "system"
    assert content == profile_agent.SYSTEM_PROMPT


def test_no_clarification_section_when_there_are_none(fake_llm, clean_user):
    fake = fake_llm()
    profile_agent.create_investor_profile(clean_user)
    assert "clarification request" not in _human_message(fake)


@pytest.mark.parametrize("empty", [None, [], ()])
def test_empty_clarifications_are_treated_as_none(fake_llm, clean_user, empty):
    fake = fake_llm()
    profile_agent.create_investor_profile(clean_user, empty)
    assert "clarification request" not in _human_message(fake)


def test_every_clarification_is_sent_not_just_the_latest(fake_llm, conflicted_user):
    """The bug this guards against: the agent forgetting earlier answers.

    If only the most recent reply were sent, the model could re-raise a conflict
    the user already resolved — which is what fed the unbounded loop.
    """
    fake = fake_llm()
    history = ["Keep technology", "Actually drop the restriction", "Yes, confirmed"]
    profile_agent.create_investor_profile(conflicted_user, history)

    message = _human_message(fake)
    for reply in history:
        assert reply in message


def test_clarifications_are_numbered_in_order(fake_llm, conflicted_user):
    fake = fake_llm()
    profile_agent.create_investor_profile(conflicted_user, ["first", "second"])

    message = _human_message(fake)
    assert "1. first" in message
    assert "2. second" in message
    assert message.index("1. first") < message.index("2. second")


def test_model_revisions_are_applied_to_the_profile(fake_llm, conflicted_user):
    fake_llm(ProfileAssessment(status="valid", revised_restrictions=[]))
    # The reply has to name what is being withdrawn. "drop it" stood here until
    # 2026-08-24 and no longer authorises anything, which is the point of the
    # guard: a reply that identifies no subject cannot delete a restriction.
    profile = profile_agent.create_investor_profile(
        conflicted_user, ["I don't mind technology after all"]
    )
    assert profile.restrictions == []


def test_the_agent_passes_the_users_replies_to_the_guard(fake_llm, conflicted_user):
    """The seam that made the bug reachable.

    build_profile can only refuse an unauthorised removal if the agent hands it
    the clarifications. It did not until 2026-08-24, so there was nothing to
    check against.
    """
    fake_llm(ProfileAssessment(status="valid", revised_restrictions=[]))
    profile = profile_agent.create_investor_profile(
        conflicted_user, ["Either way is fine, you choose."]
    )
    assert profile.restrictions == conflicted_user.restrictions


def test_clarification_verdict_is_passed_through(fake_llm, conflicted_user):
    fake_llm(
        ProfileAssessment(
            status="needs_clarification",
            clarification_reason="Interests conflict with restrictions.",
        )
    )
    profile = profile_agent.create_investor_profile(conflicted_user)

    assert profile.needs_clarification is True
    assert "conflict" in profile.clarification_reason


def test_model_failure_propagates_for_the_workflow_to_handle(fake_llm, clean_user, monkeypatch):
    """The agent does not swallow errors; profile_node decides what to do."""

    class Broken:
        def invoke(self, messages):
            raise ConnectionError("Groq unreachable")

    monkeypatch.setattr(profile_agent, "_structured_llm", lambda: Broken())

    with pytest.raises(ConnectionError):
        profile_agent.create_investor_profile(clean_user)
