"""Tests for the runs-left estimate.

The number this produces goes on a public page, so the tests are as much about
what it CLAIMS as what it counts: it must say it is an estimate, it must never
be the thing that refuses a visitor, and it must not quietly reset.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from frontend import quota

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    """A throwaway ledger. The autouse fixture in conftest does this too; this
    one names the path so a test can write to it directly."""
    path = tmp_path / "runs_served.json"
    monkeypatch.setattr(quota, "LEDGER", path)
    return path


def test_a_fresh_day_has_the_whole_allowance():
    described = quota.describe(now=NOW)

    assert described["runs_used"] == 0
    assert described["runs_remaining"] == quota.RUNS_PER_DAY


def test_each_run_started_is_counted():
    quota.record(now=NOW)
    quota.record(now=NOW + timedelta(minutes=5))

    described = quota.describe(now=NOW + timedelta(minutes=10))
    assert described["runs_used"] == 2
    assert described["runs_remaining"] == quota.RUNS_PER_DAY - 2


def test_the_window_rolls_rather_than_resetting_at_midnight(ledger):
    """The provider's limit is a rolling 24 hours. Its own console buckets by
    calendar day and therefore disagrees with the limit being enforced."""
    ledger.write_text(
        json.dumps(
            [
                (NOW - timedelta(hours=25)).isoformat(),  # dropped
                (NOW - timedelta(hours=23)).isoformat(),  # still counts
            ]
        ),
        encoding="utf-8",
    )

    assert quota.describe(now=NOW)["runs_used"] == 1


def test_it_survives_a_process_restart(ledger):
    """In-process counting would let a deploy hand the day's budget back.

    Named carefully. This proves the count is on DISK rather than in memory,
    which is all a file can prove. It does not prove the count survives a
    deploy: on Render's free plan the container is replaced on every push and
    on every spin-up after fifteen minutes idle, and the file goes with it.
    That happened on 2026-09-09 and is why the note now says so - see the
    module docstring, and `render.yaml`, which predicted it.
    """
    quota.record(now=NOW)

    assert json.loads(ledger.read_text(encoding="utf-8"))
    assert quota.describe(now=NOW)["runs_used"] == 1


def test_the_estimate_never_goes_negative():
    for index in range(quota.RUNS_PER_DAY + 3):
        quota.record(now=NOW + timedelta(minutes=index))

    described = quota.describe(now=NOW + timedelta(hours=1))
    assert described["runs_remaining"] == 0
    assert described["runs_used"] == quota.RUNS_PER_DAY + 3


@pytest.mark.parametrize("content", ["", "not json", '{"not": "a list"}', "[1, 2, 3]"])
def test_an_unreadable_ledger_is_no_runs_rather_than_an_error(ledger, content):
    """Failing a visitor's run over the bookkeeping would be worse than
    over-serving by one."""
    ledger.write_text(content, encoding="utf-8")

    assert quota.describe(now=NOW)["runs_used"] == 0


def test_it_says_out_loud_that_it_is_an_estimate():
    """The one thing this module must not do is sound certain.

    Groq does not report the daily budget, so the only real signal is the
    refusal - which costs nothing and states Limit, Used and Requested exactly.
    A reader told "4 runs left" will believe it.
    """
    described = quota.describe(now=NOW)

    assert described["estimate"] is True
    assert "estimate" in described["note"]
    assert "refusal" in described["note"]


def test_the_note_admits_the_count_can_read_high():
    """The failure a visitor actually met.

    Three people ran the deployed site and it still offered a full allowance,
    because three deploys that afternoon had each thrown the ledger away. The
    number was not fixable on a free plan - Render puts persistent disks behind
    a paid instance type - so the sentence had to stop implying a figure that
    is carried across the whole day.

    Asserted on the note rather than on the number because the number is
    correct for what it counts. It was the CLAIM that was wrong.
    """
    described = quota.describe(now=NOW)

    assert "restarts" in described["note"]
    assert "read high" in described["note"]


def test_the_ceiling_is_the_lower_of_the_two_measured_ones():
    """Counted from the cache provenance across 16 full runs on disk: news at
    ~13 requests a run against 100/day, tokens at 25-30k against 200k. They land
    within one run of each other, so neither is THE constraint and the floor of
    both is what the counter uses."""
    assert quota.RUNS_PER_DAY == 7
