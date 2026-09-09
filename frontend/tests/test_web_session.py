"""Tests for the cookie that says which runs a visitor may answer.

The clarification interrupt splits one run across two requests, so something has
to carry ownership between them. These are about the property that matters: a
thread id can be READ by anyone - it travels in the stream and the CLI prints it
- but it must not be possible to FORGE membership of somebody else's session.
"""

import base64
import json
from datetime import datetime, timedelta, timezone

import pytest

from backend import config
from frontend import session

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fixed_secret(monkeypatch):
    """A configured secret, so these do not depend on the per-process fallback."""
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret-never-used-anywhere")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def test_a_run_this_visitor_started_comes_back(monkeypatch):
    cookie = session.add(None, "web-abc123")

    assert session.read(cookie) == ["web-abc123"]
    assert session.owns(cookie, "web-abc123")


def test_a_run_somebody_else_started_is_not_theirs():
    assert not session.owns(session.add(None, "web-mine"), "web-theirs")
    assert not session.owns(None, "web-anything")


def test_the_ids_travel_in_the_clear_and_that_is_deliberate():
    """Not a leak. They are already in the stream and printed by the CLI, so
    hiding them buys nothing - being unable to forge one is the point."""
    cookie = session.add(None, "web-abc123")
    payload, _, _ = cookie.partition(".")

    assert "web-abc123" in base64.urlsafe_b64decode(payload).decode("utf-8")


def test_a_forged_cookie_is_refused():
    """The whole reason this is signed. Anyone can write a cookie; only the
    server can sign one."""
    payload = base64.urlsafe_b64encode(
        json.dumps(["web-not-mine"]).encode("utf-8")
    ).decode("ascii")

    assert session.read(f"{payload}.obviouslywrongsignature") == []
    assert session.read(payload) == [], "unsigned is refused too"


def test_a_cookie_signed_with_another_secret_is_refused(monkeypatch):
    cookie = session.add(None, "web-abc123")

    monkeypatch.setenv("WEB_SESSION_SECRET", "a-different-secret")
    config.get_settings.cache_clear()

    assert session.read(cookie) == []


def test_tampering_with_the_payload_invalidates_the_signature():
    cookie = session.add(None, "web-abc123")
    payload, _, signature = cookie.partition(".")
    forged = base64.urlsafe_b64encode(
        json.dumps(["web-abc123", "web-someone-else"]).encode("utf-8")
    ).decode("ascii")

    assert session.read(f"{forged}.{signature}") == []


@pytest.mark.parametrize(
    "cookie", ["", "no-dot-at-all", ".", "not-base64.also-not", "x." + "y" * 44]
)
def test_a_malformed_cookie_is_an_empty_session_not_an_error(cookie):
    """A visitor cannot see or clear a cookie they did not know they had, so a
    page that refuses to load because of one is unfixable from their side."""
    assert session.read(cookie) == []


def test_the_oldest_runs_are_dropped_rather_than_the_whole_cookie():
    """A cookie is capped at about 4KB by every browser. Growing past it loses
    the SESSION; dropping the oldest ids loses only old runs."""
    cookie = None
    for index in range(session.MAX_THREADS + 5):
        cookie = session.add(cookie, f"web-{index:04d}")

    threads = session.read(cookie)
    assert len(threads) == session.MAX_THREADS
    assert threads[-1] == f"web-{session.MAX_THREADS + 4:04d}"
    assert "web-0000" not in threads


def test_restarting_a_run_does_not_duplicate_it():
    cookie = session.add(session.add(None, "web-abc"), "web-abc")

    assert session.read(cookie) == ["web-abc"]


# --- One run per visitor per day ---------------------------------------------
#
# A full run is 25-30k tokens against a ceiling every visitor shares, so one
# person clicking repeatedly empties the site for everybody else.


def test_a_new_visitor_may_start_a_run():
    assert session.may_start(None)
    assert session.runs_in_window(None) == 0


def test_a_visitor_who_has_already_run_today_may_not_start_another():
    cookie = session.add(None, "web-abc123", now=NOW)

    assert session.runs_in_window(cookie, now=NOW + timedelta(minutes=5)) == 1
    assert not session.may_start(cookie, now=NOW + timedelta(minutes=5))


def test_the_allowance_comes_back_after_a_rolling_day():
    """Rolling rather than at midnight, matching the provider's own window."""
    cookie = session.add(None, "web-abc123", now=NOW)

    assert not session.may_start(cookie, now=NOW + timedelta(hours=23))
    assert session.may_start(cookie, now=NOW + timedelta(hours=25))


def test_a_cookie_from_before_run_times_were_recorded_still_works():
    """The payload grew from a bare list to an object. An older cookie keeps
    working and simply has no history, which costs its holder nothing."""
    old_style = session.write(["web-old"])

    assert session.read(old_style) == ["web-old"]
    assert session.owns(old_style, "web-old")
    assert session.may_start(old_style)


def test_an_unreadable_timestamp_does_not_refuse_a_visitor():
    """Erring towards letting somebody run. The queue and the provider's own
    refusal are the gates that matter; this is a speed bump."""
    cookie = session._encode({"threads": ["web-a"], "runs": ["not a timestamp"]})

    assert session.may_start(cookie)
