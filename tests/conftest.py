"""Shared pytest setup and fixtures.

conftest.py is discovered automatically by pytest — tests never import it.
Anything defined here is available to every test in this directory.

The guiding rule for this suite: NO NETWORK CALLS. These tests must run in
under a second, give the same answer every time, and work on a machine with no
API key. Anything that needs the real model belongs in the eval suite instead,
which measures model behaviour rather than code correctness.
"""

from datetime import datetime, timezone

import pytest

import config
from clients import news
from models.profile import InvestorProfile, ProfileAssessment
from models.research import Article
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
    monkeypatch.setenv("NEWS_API_KEY", "test-news-key-never-used")
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


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Point the news cache at a throwaway directory.

    Without this, tests would read and write the developer's real .cache/news,
    so a cached response could make a test pass that should fail, and a test run
    could evict entries a real run needed. Each test gets an empty cache.
    """
    monkeypatch.setattr(news, "CACHE_DIR", tmp_path / "news-cache")


@pytest.fixture
def research_profile(clean_user) -> InvestorProfile:
    """A validated profile suitable for Agent 2."""
    return InvestorProfile(**clean_user.model_dump(), status="valid")


def make_article(uuid="a1", title="A headline", url=None, source="example.com",
                 day=18, description="desc", snippet="snip") -> Article:
    """Build an Article for tests. Only the fields a test cares about vary."""
    return Article(
        uuid=uuid,
        title=title,
        description=description,
        snippet=snippet,
        url=url or f"https://{source}/{uuid}",
        source=source,
        published_at=datetime(2026, 8, day, tzinfo=timezone.utc),
    )


@pytest.fixture
def articles() -> list[Article]:
    """Three unrelated articles from different sources."""
    return [
        make_article("u1", "Battery order won by Waaree", source="reuters.com", day=17),
        make_article("u2", "Solar financing secured in Italy", source="ft.com", day=18),
        make_article("u3", "Hydrogen project stalls in Uruguay", source="bbc.com", day=19),
    ]


@pytest.fixture(autouse=True)
def no_accidental_research(monkeypatch):
    """Make it impossible for a test to reach the real research agent.

    Wiring Agent 2 into the graph meant any test producing a VALID profile
    suddenly continued into research — and one existing test did exactly that,
    firing a live news search and a live model call with a dummy key.

    A test that silently reaches the network is slow, flaky, spends API quota,
    and passes or fails for reasons unrelated to the code under test. So the
    default is an immediate, explanatory failure. Tests that legitimately run
    the research node override this with the `fake_research` fixture.

    This guard will matter more as Agents 3-5 arrive: each one extends the graph
    and inherits the same hazard.
    """
    import workflow

    def guard(*args, **kwargs):
        raise AssertionError(
            "This test reached the real research agent, which would call the "
            "news API and the model. Use the `fake_research` fixture to stub it."
        )

    monkeypatch.setattr(workflow, "research_themes", guard)
