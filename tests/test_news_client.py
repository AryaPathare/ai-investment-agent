"""Tests for the news client: parsing, deduplication, caching, error handling.

No test here touches the network. ``requests.get`` is replaced with a fake, which
is the whole reason the client was wrapped behind our own interface in the first
place.
"""

import pytest
import requests

from clients import news
from clients.news import (
    NewsAPIError,
    _normalise_title,
    _normalise_url,
    _to_article,
    deduplicate,
    search_many,
    search_news,
)
from tests.conftest import make_article


class FakeResponse:
    """Stands in for a requests.Response."""

    def __init__(self, status_code=200, payload=None, text="", valid_json=True):
        self.status_code = status_code
        self._payload = {"data": []} if payload is None else payload
        self.text = text
        self._valid_json = valid_json

    def json(self):
        if not self._valid_json:
            raise ValueError("not json")
        return self._payload


def raw(uuid="x1", title="Title", url="https://example.com/x1", published="2026-08-18T10:00:00.000000Z"):
    return {
        "uuid": uuid,
        "title": title,
        "description": "A description",
        "snippet": "A snippet",
        "url": url,
        "source": "example.com",
        "published_at": published,
        "categories": ["business"],
    }


@pytest.fixture
def fake_get(monkeypatch):
    """Install a fake requests.get and record the calls it receives."""
    calls = []

    def _install(response=None, error=None):
        def fake(url, params=None, timeout=None, headers=None):
            calls.append({"url": url, "params": params, "headers": headers})
            if error is not None:
                raise error
            return response if response is not None else FakeResponse()

        monkeypatch.setattr(news.requests, "get", fake)
        return calls

    return _install


# --- URL and title normalisation --------------------------------------------


@pytest.mark.parametrize(
    "a,b",
    [
        ("https://www.wsj.com/x", "http://wsj.com/x"),
        ("https://wsj.com/x/", "https://wsj.com/x"),
        ("https://wsj.com/x?utm_source=twitter", "https://wsj.com/x"),
        ("https://WSJ.com/X#section", "https://wsj.com/X"),
    ],
)
def test_urls_that_point_at_the_same_article_normalise_equal(a, b):
    assert _normalise_url(a) == _normalise_url(b)


def test_different_articles_do_not_normalise_equal():
    assert _normalise_url("https://wsj.com/a") != _normalise_url("https://wsj.com/b")


def test_title_normalisation_ignores_case_and_punctuation():
    assert _normalise_title("Nvidia Beats Earnings -- Again!") == _normalise_title(
        "nvidia beats earnings   again"
    )


# --- Deduplication -----------------------------------------------------------


def test_syndicated_copies_collapse_to_one():
    """One wire story on three sites is one source, not three."""
    pool = [
        make_article("1", "Nvidia beats earnings on AI chip demand", source="reuters.com", day=18),
        make_article("2", "Nvidia beats earnings on AI chip demand", source="yahoo.com", day=19),
        make_article("3", "Nvidia Beats Earnings on A.I. Chip Demand!", source="msn.com", day=19),
    ]
    assert len(deduplicate(pool)) == 1


def test_deduplication_keeps_the_earliest_publication():
    """Syndicated copies come after the original, so earliest is the primary source."""
    pool = [
        make_article("late", "Same story here", source="aggregator.com", day=20),
        make_article("early", "Same story here", source="reuters.com", day=17),
    ]
    kept = deduplicate(pool)
    assert [a.uuid for a in kept] == ["early"]


def test_same_url_reached_twice_collapses():
    pool = [
        make_article("1", "A", url="https://wsj.com/piece?utm_source=x", day=17),
        make_article("2", "A", url="https://www.wsj.com/piece/", day=17),
    ]
    assert len(deduplicate(pool)) == 1


def test_genuinely_different_stories_survive():
    """The dangerous failure: over-merging silently destroys evidence."""
    pool = [
        make_article("1", "Nvidia beats earnings on AI chip demand", day=18),
        make_article("2", "Nvidia announces data centre partnership in Japan", day=19),
    ]
    assert len(deduplicate(pool)) == 2


def test_deduplicating_an_empty_list_is_fine():
    assert deduplicate([]) == []


# --- Parsing -----------------------------------------------------------------


def test_parses_a_well_formed_record():
    article = _to_article(raw())
    assert article is not None
    assert article.uuid == "x1"
    assert article.published_at.year == 2026


@pytest.mark.parametrize("missing", ["uuid", "title", "url", "published_at"])
def test_records_missing_a_required_field_are_skipped(missing):
    """One bad record should cost that record, not the whole search."""
    record = raw()
    del record[missing]
    assert _to_article(record) is None


def test_unparseable_date_is_skipped_not_raised():
    assert _to_article(raw(published="not a date")) is None


def test_missing_optional_fields_default_to_empty():
    record = raw()
    del record["description"]
    del record["snippet"]
    article = _to_article(record)
    assert article.description == ""
    assert article.snippet == ""


# --- Request construction ----------------------------------------------------


def test_recency_filter_and_sort_are_always_applied(fake_get):
    """Without published_after the API returns articles from years ago."""
    calls = fake_get(FakeResponse(payload={"data": [raw()]}))
    search_news("semiconductors")

    params = calls[0]["params"]
    assert "published_after" in params
    assert params["sort"] == "relevance_score"


def test_an_explicit_user_agent_is_sent(fake_get):
    """Cloudflare rejects Python's default user-agent with 403 error 1010."""
    calls = fake_get(FakeResponse(payload={"data": []}))
    search_news("anything")
    assert "ai-investment-agent" in calls[0]["headers"]["User-Agent"]


def test_days_back_can_be_overridden(fake_get):
    calls = fake_get(FakeResponse(payload={"data": []}))
    search_news("x", days_back=1)
    search_news("y", days_back=365)
    assert calls[0]["params"]["published_after"] != calls[1]["params"]["published_after"]


# --- Error handling ----------------------------------------------------------


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "token"),
        (429, "rate limit"),
        (500, "HTTP 500"),
    ],
)
def test_http_errors_become_actionable_messages(fake_get, status, expected):
    fake_get(FakeResponse(status_code=status, text="server said no"))
    with pytest.raises(NewsAPIError, match=expected):
        search_news("x")


def test_network_failure_becomes_a_news_api_error(fake_get):
    fake_get(error=requests.ConnectionError("no route to host"))
    with pytest.raises(NewsAPIError, match="Could not reach"):
        search_news("x")


def test_non_json_response_becomes_a_news_api_error(fake_get):
    fake_get(FakeResponse(valid_json=False))
    with pytest.raises(NewsAPIError, match="non-JSON"):
        search_news("x")


def test_missing_api_key_is_reported_clearly(fake_get, monkeypatch):
    # Deleting the env var is not enough: get_settings() calls load_dotenv(),
    # which would read the real .env straight back in. Override the settings
    # object the client actually uses instead.
    import config

    without_key = config.get_settings().model_copy(update={"news_api_key": None})
    monkeypatch.setattr(news, "get_settings", lambda: without_key)
    fake_get(FakeResponse())

    with pytest.raises(NewsAPIError, match="NEWS_API_KEY"):
        search_news("x")


# --- Caching -----------------------------------------------------------------


def test_a_repeated_query_does_not_call_the_api_twice(fake_get):
    calls = fake_get(FakeResponse(payload={"data": [raw()]}))

    first = search_news("semiconductors")
    second = search_news("semiconductors")

    assert len(calls) == 1, "second call should have been served from cache"
    assert [a.uuid for a in first] == [a.uuid for a in second]


def test_different_queries_are_cached_separately(fake_get):
    calls = fake_get(FakeResponse(payload={"data": [raw()]}))
    search_news("solar")
    search_news("wind")
    assert len(calls) == 2


def test_cache_can_be_bypassed(fake_get):
    calls = fake_get(FakeResponse(payload={"data": [raw()]}))
    search_news("solar")
    search_news("solar", use_cache=False)
    assert len(calls) == 2


def test_the_api_token_never_reaches_a_cache_filename(fake_get):
    """A secret has no business in a filename, and it does not identify a query."""
    fake_get(FakeResponse(payload={"data": [raw()]}))
    search_news("solar")

    files = list(news.CACHE_DIR.glob("*.json"))
    assert files, "expected a cache entry to be written"
    assert all("test-news-key" not in f.name for f in files)


def test_a_corrupt_cache_entry_falls_back_to_the_api(fake_get):
    calls = fake_get(FakeResponse(payload={"data": [raw()]}))
    search_news("solar")

    for path in news.CACHE_DIR.glob("*.json"):
        path.write_text("{ this is not valid json", encoding="utf-8")

    search_news("solar")
    assert len(calls) == 2, "a corrupt entry should not break a real run"


# --- search_many -------------------------------------------------------------


def test_search_many_merges_and_deduplicates(fake_get):
    """Two queries returning the same story should yield one article."""
    fake_get(FakeResponse(payload={"data": [raw(uuid="dup", url="https://a.com/1")]}))
    articles, ok = search_many(["solar", "wind"])

    assert len(ok) == 2
    assert len(articles) == 1


def test_one_failing_query_does_not_abandon_the_others(monkeypatch):
    """Partial results beat none."""
    titles = {
        "solar": "Regulator approves rooftop tariff reform",
        "wind": "Offshore turbine maker wins Baltic contract",
    }

    def flaky(query, **kwargs):
        if query == "broken":
            raise NewsAPIError("boom")
        return [make_article(uuid=query, title=titles[query])]

    monkeypatch.setattr(news, "search_news", flaky)
    articles, ok = search_many(["solar", "broken", "wind"])

    assert ok == ["solar", "wind"]
    assert len(articles) == 2


def test_search_many_with_no_queries_returns_nothing(fake_get):
    fake_get(FakeResponse())
    assert search_many([]) == ([], [])


def test_headlines_differing_only_by_a_number_are_kept_apart():
    """Financial headlines are formulaic; the number is what distinguishes them.

    "Tesla Q2 earnings beat" and "Tesla Q3 earnings beat" are ~0.97 similar as
    strings but are different stories. Merging them would destroy evidence
    silently, so numbers must match before similarity is even considered.
    """
    pool = [
        make_article("q2", "Tesla Q2 earnings beat expectations", day=17),
        make_article("q3", "Tesla Q3 earnings beat expectations", day=18),
    ]
    assert len(deduplicate(pool)) == 2


def test_amounts_that_differ_keep_stories_apart():
    pool = [
        make_article("a", "Solar developer secures 695 million in financing", day=17),
        make_article("b", "Solar developer secures 234 million in financing", day=18),
    ]
    assert len(deduplicate(pool)) == 2


def test_syndication_with_matching_numbers_still_collapses():
    """The number guard must not break the case dedup exists for."""
    pool = [
        make_article("orig", "Recurrent Energy secures 695 million for solar", source="reuters.com", day=17),
        make_article("synd", "Recurrent Energy Secures 695 Million For Solar!", source="yahoo.com", day=19),
    ]
    kept = deduplicate(pool)
    assert len(kept) == 1
    assert kept[0].uuid == "orig"
