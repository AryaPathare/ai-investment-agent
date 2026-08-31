"""Shared pytest setup and fixtures.

conftest.py is discovered automatically by pytest — tests never import it.
Anything defined here is available to every test in this directory.

The guiding rule for this suite: NO NETWORK CALLS. These tests must run in
under a second, give the same answer every time, and work on a machine with no
API key. Anything that needs the real model belongs in the eval suite instead,
which measures model behaviour rather than code correctness.
"""

import re
from datetime import datetime, timezone

import pytest

import checkpoints
import config
from clients import news
from models.profile import InvestorProfile, ProfileAssessment
from models.research import Article
from models.user_input import UserInput

DEFAULT_DB_PATH = checkpoints.DB_PATH
"""The real checkpoint path, captured before any test can redirect it.

``isolated_checkpoints`` below points ``checkpoints.DB_PATH`` at a temporary
file for every test, which is what you want everywhere except in the two tests
that are ABOUT the real default. Those read this instead.
"""


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch):
    """Give every test a dummy API key, and never touch the real .env.

    ``autouse=True`` applies this to every test automatically.

    A real environment variable takes priority over the .env file, so this makes
    the suite pass identically on your machine and on a CI runner that has no
    .env at all. The cached settings are cleared before and after so no test
    inherits another test's configuration.

    EVERY credential config.py can read must be set here. One that is missing
    falls through to the developer's real .env and the tests keep passing, right
    up until they run somewhere that has none - which is exactly what CI is for
    and exactly how this was found.
    """
    monkeypatch.setenv("GROQ_API_KEY", "test-key-never-used")
    monkeypatch.setenv("NEWS_API_KEY", "test-news-key-never-used")
    # FMP too. Its absence was invisible on a developer machine, where .env
    # supplies it: five tests in test_company_client.py stubbed the network,
    # expected "Could not reach", and got "FMP_API_KEY is not set" instead the
    # moment they ran anywhere without a .env. The docstring above claimed the
    # suite passed identically on a CI runner with no .env; it did not, and
    # nothing revealed that until one actually ran.
    monkeypatch.setenv("FMP_API_KEY", "test-fmp-key-never-used")
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
        holding_period="5+ years",
        sectors_of_interest=["renewable energy"],
        restrictions=[],
    )


@pytest.fixture
def conflicted_user() -> UserInput:
    """An investor whose sectors_of_interest contradict their restrictions."""
    return UserInput(
        age=20,
        investment_experience="beginner",
        risk_tolerance="moderate",
        investment_amount=1000,
        holding_period="3-5 years",
        sectors_of_interest=["sports", "technology"],
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

    Extended for Agent 3, which reaches two data providers as well as the model.
    Each new agent extends the graph and inherits the same hazard.
    """
    import workflow

    def guard(*args, **kwargs):
        raise AssertionError(
            "This test reached the real research agent, which would call the "
            "news API and the model. Use the `fake_research` fixture to stub it."
        )

    def company_guard(*args, **kwargs):
        raise AssertionError(
            "This test reached the real company agent, which would call FMP, "
            "yfinance and the model. Use the `fake_companies` fixture to stub it."
        )

    monkeypatch.setattr(workflow, "research_themes", guard)
    monkeypatch.setattr(workflow, "analyse_companies", company_guard)


@pytest.fixture(scope="session")
def checkpoint_dir(tmp_path_factory):
    """One throwaway directory for the whole session. See below for why."""
    return tmp_path_factory.mktemp("checkpoints")


@pytest.fixture(autouse=True)
def isolated_checkpoints(checkpoint_dir, request, monkeypatch):
    """Point the checkpoint database at a throwaway file.

    Same reasoning as ``isolated_cache`` above, with more at stake. The real
    database holds RUNS A PERSON HAS NOT FINISHED - a paused clarification is
    exactly what it exists to protect - and a test writing into it could
    resurrect a thread id from a previous test run, or bury a real one.

    ``autouse`` rather than opt-in on purpose: a test that forgets ``--db``
    should get a temporary file, not the user's saved work.

    Uses a single session-scoped directory with one file per test rather than
    ``tmp_path``. ``tmp_path`` is per-test and this fixture applies to ALL of
    them, so requesting it here created a directory for every test in the suite
    - about six seconds of pure filesystem overhead for a guard that most tests
    never trigger. The file itself is only created if something opens it.
    """
    import checkpoints

    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", request.node.nodeid)
    monkeypatch.setattr(checkpoints, "DB_PATH", checkpoint_dir / f"{safe}.sqlite")
