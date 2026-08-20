"""Shared pytest setup and fixtures.

conftest.py is discovered automatically by pytest — tests never import it.
Anything defined here is available to every test in this directory.

The guiding rule for this suite: NO NETWORK CALLS. These tests must run in
under a second, give the same answer every time, and work on a machine with no
API key. Anything that needs the real model belongs in the eval suite instead,
which measures model behaviour rather than code correctness.
"""

import pytest

import config
from models.profile import InvestorProfile, ProfileAssessment
from models.user_input import UserInput


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch):
    """Give every test a dummy API key, and never touch the real .env.

    ``autouse=True`` applies this to every test automatically.

    A real environment variable takes priority over the .env file, so this makes
    the suite pass identically on your machine and on a CI runner that has no
    .env at all. The cached settings are cleared before and after so no test
    inherits another test's configuration.
    """
    monkeypatch.setenv("GROQ_API_KEY", "test-key-never-used")
    config.get_settings.cache_clear()
    config.get_llm.cache_clear()
    yield
    config.get_settings.cache_clear()
    config.get_llm.cache_clear()


@pytest.fixture
def clean_user() -> UserInput:
    """An investor profile with no internal conflicts."""
    return UserInput(
        age=35,
        investment_experience="intermediate",
        risk_tolerance="moderate",
        investment_amount=5000,
        investment_window="within 3 months",
        holding_period="5+ years",
        interests=["renewable energy"],
        restrictions=[],
    )


@pytest.fixture
def conflicted_user() -> UserInput:
    """An investor whose interests contradict their restrictions."""
    return UserInput(
        age=20,
        investment_experience="beginner",
        risk_tolerance="moderate",
        investment_amount=1000,
        investment_window="within 1 month",
        holding_period="3-5 years",
        interests=["sports", "technology"],
        restrictions=["Do not invest in technology companies"],
    )


@pytest.fixture
def valid_profile(clean_user) -> InvestorProfile:
    """A profile that passed validation."""
    return InvestorProfile(**clean_user.model_dump(), status="valid")


@pytest.fixture
def blocked_profile(conflicted_user) -> InvestorProfile:
    """A profile waiting on the user to resolve a conflict."""
    return InvestorProfile(
        **conflicted_user.model_dump(),
        status="needs_clarification",
        clarification_reason="Interests include technology but restrictions forbid it.",
    )


@pytest.fixture
def assessment_valid() -> ProfileAssessment:
    return ProfileAssessment(status="valid")
