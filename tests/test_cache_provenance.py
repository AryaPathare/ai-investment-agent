"""Tests for what the news cache records about its own contents.

The cache used to store the provider's reply and nothing else, which made it a
corpus of articles with no record of the questions that produced them. The cost
appeared the first time anyone tried to learn from it: an audit could see that
6% of cached articles were press releases and could NOT tell whether they
reached Agent 2 or Agent 4 — two agents for whom that content means completely
different things. The finding had to be recorded as unproven.

These tests cover the three ways the fix could go wrong quietly:

* the token ending up on disk
* the provenance block colliding with the provider's own fields, or leaking
  into the articles parsed out of the payload
* entries written before the change becoming unreadable
"""

import json

import pytest

from clients import news
from clients.news import PROVENANCE_KEY, _write_cache


@pytest.fixture
def cache_file(tmp_path):
    return tmp_path / "entry.json"


def _payload():
    return {"meta": {"found": 2}, "data": [{"uuid": "u1"}, {"uuid": "u2"}]}


def _written(path):
    return json.loads(path.read_text(encoding="utf-8"))


# --- What gets recorded ------------------------------------------------------


def test_the_query_is_recorded_beside_the_response(cache_file):
    _write_cache(cache_file, _payload(), provenance={"query": "solar tariffs"})
    assert _written(cache_file)[PROVENANCE_KEY]["query"] == "solar tariffs"


def test_the_asking_agent_is_recorded(cache_file):
    """THE point of the change. Which agent asked decides what the article is
    worth: a press release is ordinary input for theme research and close to
    worthless to a risk critic."""
    _write_cache(cache_file, _payload(), provenance={"asked_by": "risk_critic"})
    assert _written(cache_file)[PROVENANCE_KEY]["asked_by"] == "risk_critic"


def test_the_providers_own_payload_is_left_untouched(cache_file):
    original = _payload()
    _write_cache(cache_file, original, provenance={"query": "x"})
    written = _written(cache_file)

    assert written["meta"] == original["meta"]
    assert written["data"] == original["data"]


def test_the_caller_s_payload_is_not_mutated(cache_file):
    """The same dict is parsed into Articles by the caller. Adding a key to it
    as a side effect of caching would be a surprising thing for a cache to do."""
    payload = _payload()
    _write_cache(cache_file, payload, provenance={"query": "x"})
    assert PROVENANCE_KEY not in payload


def test_the_provenance_key_cannot_collide_with_a_provider_field():
    """Everything TheNewsAPI returns is a bare name ("meta", "data"). The
    leading underscore keeps this out of that namespace even if the provider
    adds fields later."""
    assert PROVENANCE_KEY.startswith("_")


# --- What must never be recorded ---------------------------------------------


def test_no_api_token_reaches_the_cache_file(cache_file, monkeypatch):
    """The cache key already excludes the token for this reason. Writing it
    into the VALUE instead would put a live credential in a file the whole
    point of which is to be kept around and inspected later."""
    _write_cache(
        cache_file,
        _payload(),
        provenance={"query": "solar", "asked_by": "research"},
    )
    text = cache_file.read_text(encoding="utf-8")
    assert "api_token" not in text
    assert "test-news-key-never-used" not in text


# --- Backwards and forwards compatibility ------------------------------------


def test_writing_without_provenance_still_works(cache_file):
    """Nothing should be forced to supply it."""
    _write_cache(cache_file, _payload())
    written = _written(cache_file)
    assert PROVENANCE_KEY not in written
    assert written["data"] == _payload()["data"]


def test_entries_written_before_this_change_stay_readable(cache_file):
    """224 of them exist. A cache format change that stranded them would throw
    away the corpus this feature was built to make useful."""
    cache_file.write_text(json.dumps(_payload()), encoding="utf-8")
    payload = news._read_cache(cache_file, ttl_hours=99999)

    assert payload is not None
    assert payload.get(PROVENANCE_KEY) is None, "absent, not invented"
    assert len(payload["data"]) == 2


def test_a_cached_entry_with_provenance_parses_into_the_same_articles(cache_file):
    """The provenance block must not become an article, and must not stop the
    real ones being read."""
    raw = {
        "uuid": "u1",
        "title": "Solar tariffs raised",
        "url": "https://reuters.com/a",
        "source": "reuters.com",
        "published_at": "2026-08-18T00:00:00Z",
    }
    _write_cache(
        cache_file, {"meta": {}, "data": [raw]}, provenance={"query": "solar"}
    )
    payload = json.loads(cache_file.read_text(encoding="utf-8"))

    articles = [a for a in map(news._to_article, payload.get("data", [])) if a]
    assert [a.uuid for a in articles] == ["u1"]


def test_a_write_failure_is_not_an_error(tmp_path):
    """Caching is an optimisation. A read-only disk must not break a real run,
    and adding provenance must not change that."""
    unwritable = tmp_path / "nope" / "nested"
    unwritable.mkdir(parents=True)
    _write_cache(unwritable, _payload(), provenance={"query": "x"})  # a directory


# --- The wiring --------------------------------------------------------------


def test_a_real_search_records_the_query_and_the_asker(tmp_path, monkeypatch):
    """End to end through search_news with the HTTP call stubbed.

    The unit tests above prove _write_cache records what it is given. This
    proves anything is actually given to it - the wiring is where a feature
    like this quietly does nothing.
    """
    monkeypatch.setattr(news, "CACHE_DIR", tmp_path)

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"meta": {"found": 0}, "data": []}

    monkeypatch.setattr(news.requests, "get", lambda *a, **k: FakeResponse())

    news.search_news("solar tariff ruling", asked_by="risk_critic")

    written = [json.loads(p.read_text(encoding="utf-8")) for p in tmp_path.glob("*.json")]
    assert len(written) == 1, "exactly one cache entry should have been written"

    provenance = written[0][PROVENANCE_KEY]
    assert provenance["query"] == "solar tariff ruling"
    assert provenance["asked_by"] == "risk_critic"
    assert provenance["fetched_at"].startswith("20")
    assert "api_token" not in json.dumps(written[0])


def test_both_agents_tag_themselves_distinctly():
    """The whole feature is worthless if both callers report the same thing.

    Read out of the source rather than by running the agents, which would need
    a model and a news key.
    """
    from config import PROJECT_ROOT

    research = (PROJECT_ROOT / "agents" / "research_agent.py").read_text(encoding="utf-8")
    risk = (PROJECT_ROOT / "agents" / "risk_agent.py").read_text(encoding="utf-8")

    assert 'asked_by="research"' in research
    assert 'asked_by="risk_critic"' in risk


def test_a_cache_hit_records_the_second_agent_too(tmp_path, monkeypatch):
    """Found by review. A cache HIT writes nothing, so the entry kept only
    whichever agent asked FIRST - and the two agents share a cache key on
    purpose, since splitting it would double requests against a 100/day ceiling.
    Attributing a shared article to one agent is the exact question this block
    was added to answer."""
    monkeypatch.setattr(news, "CACHE_DIR", tmp_path)

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"meta": {}, "data": []}

    monkeypatch.setattr(news.requests, "get", lambda *a, **k: FakeResponse())

    news.search_news("solar tariffs", asked_by="research")     # miss: writes
    news.search_news("solar tariffs", asked_by="risk_critic")  # hit: must append

    written = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    block = written[PROVENANCE_KEY]

    assert block["asked_by"] == "research"
    assert block["also_asked_by"] == ["risk_critic"]


def test_the_same_agent_is_not_recorded_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "CACHE_DIR", tmp_path)

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"meta": {}, "data": []}

    monkeypatch.setattr(news.requests, "get", lambda *a, **k: FakeResponse())

    for _ in range(3):
        news.search_news("solar tariffs", asked_by="research")

    block = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))[PROVENANCE_KEY]
    assert block.get("also_asked_by", []) == []


def test_an_entry_written_before_provenance_is_left_alone(tmp_path, monkeypatch):
    """The 224 older entries genuinely have no provenance. Inventing one on a
    cache hit would claim an attribution nobody recorded."""
    monkeypatch.setattr(news, "CACHE_DIR", tmp_path)
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"meta": {}, "data": []}), encoding="utf-8")

    news._record_asker(path, "risk_critic")

    assert PROVENANCE_KEY not in json.loads(path.read_text(encoding="utf-8"))


def test_recording_an_asker_does_not_reset_the_cache_age(cache_file):
    """A bug introduced by the provenance fix itself, caught on a second pass.

    _read_cache measures staleness from the file's MTIME, and _record_asker
    rewrites the file. So a query both agents ask was refreshed on every run
    and could never expire - stale news served indefinitely to the one agent
    whose job is finding out what has gone wrong.
    """
    import os
    import time

    _write_cache(cache_file, _payload(), provenance={"query": "s", "asked_by": "research"})
    aged = time.time() - 10 * 3600
    os.utime(cache_file, (aged, aged))

    news._record_asker(cache_file, "risk_critic")

    age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
    assert 9.5 < age_hours < 10.5, "the entry must keep its original age"
    # ...and the recording must still have happened.
    block = _written(cache_file)[PROVENANCE_KEY]
    assert block["also_asked_by"] == ["risk_critic"]


def test_an_expired_entry_stays_expired_after_a_second_agent_asks(cache_file):
    """The consequence, stated directly."""
    import os
    import time

    _write_cache(cache_file, _payload(), provenance={"query": "s", "asked_by": "research"})
    aged = time.time() - 48 * 3600
    os.utime(cache_file, (aged, aged))

    news._record_asker(cache_file, "risk_critic")

    assert news._read_cache(cache_file, ttl_hours=24) is None
