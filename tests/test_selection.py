"""Tests for Agent 5's selection: tiering, gates, and the accounting.

No model, no network. What is under test is that every candidate ends as either
a selection or a recorded exclusion, that a candidate nobody examined is never
promoted on an unearned verdict, and that "nothing" says which kind of nothing.
"""

import pytest

from agents.selection import restriction_terms, select
from models.companies import (
    CompanyCandidate,
    CompanyFindings,
    ComparableMetrics,
    CurrencyAmounts,
    Fundamentals,
)
from models.profile import InvestorProfile
from models.risk import CandidateCritique, Risk, RiskFindings


def profile(restrictions=()):
    return InvestorProfile(
        age=40, investment_experience="intermediate", risk_tolerance="moderate",
        investment_amount=5000.0, investment_window="within 3 months",
        holding_period="3-5 years", sectors_of_interest=["technology"],
        restrictions=list(restrictions), status="valid",
    )


def candidate(ticker="AAA", name=None, score=0.7, rationale="builds the thing",
              themes=("Some Theme",)):
    return CompanyCandidate(
        ticker=ticker, name=name or ticker, exchange="NMS", currency="USD",
        fundamentals=Fundamentals(
            comparable=ComparableMetrics(revenue_growth=0.2, operating_margin=0.1),
            amounts=CurrencyAmounts(currency="USD"), source="fmp",
        ),
        exposure="direct", exposure_rationale=rationale, themes=list(themes),
        evidence_article_ids=["u-1"], screen_score=score,
    )


def critique(ticker="AAA", severities=(), skipped=None):
    risks = [
        Risk(ticker=ticker, risk_type="regulatory", severity=s,
             claim=f"A {s} problem was reported.", article_ids=[f"u-{i}"])
        for i, s in enumerate(severities)
    ]
    return CandidateCritique(
        ticker=ticker, name=ticker, risks=risks,
        articles_reviewed=0 if skipped else 3, skipped_reason=skipped,
    )


def run(cands, crits, restrictions=()):
    return select(
        CompanyFindings(candidates=cands, companies_examined=len(cands)),
        RiskFindings(critiques=crits),
        profile(restrictions),
    )


# --- Nothing says which kind of nothing --------------------------------------


def test_no_candidates_at_all_is_reported_as_such():
    got = run([], [])
    assert got.selected == []
    assert "found no investable company" in got.no_recommendation_reason


def test_every_candidate_disqualified_says_so():
    got = run([candidate()], [critique(severities=["critical"])])
    assert got.selected == []
    assert "critical risk" in got.no_recommendation_reason


def test_every_candidate_unexamined_says_something_different():
    """"All were disqualified" and "none were examined" call for completely
    different responses from a reader."""
    got = run([candidate()], [critique(skipped="outside the cap")])
    assert got.selected == []
    assert "never examined" in got.no_recommendation_reason


def test_a_successful_selection_carries_no_reason():
    got = run([candidate()], [critique()])
    assert len(got.selected) == 1
    assert got.no_recommendation_reason is None


# --- An unearned "survives" is not selectable --------------------------------


def test_a_candidate_the_critic_skipped_is_never_recommended():
    """THE trap in Agent 4's schema: an unexamined candidate reports "survives"
    identically to one that was attacked and held up. Selecting on the verdict
    alone would promote exactly what the critique cap left out."""
    got = run(
        [candidate("SKIPPED", score=0.99), candidate("REAL", score=0.30)],
        [critique("SKIPPED", skipped="outside the cap"), critique("REAL")],
    )

    assert [c.ticker for c, _ in got.selected] == ["REAL"]
    assert [(e.ticker, e.reason) for e in got.excluded] == [("SKIPPED", "not_critiqued")]


def test_a_candidate_with_no_critique_at_all_is_treated_the_same_way():
    """Neither tells us anything about its risks."""
    got = run([candidate("GHOST")], [])
    assert got.selected == []
    assert got.excluded[0].reason == "not_critiqued"


# --- Tiering -----------------------------------------------------------------


def test_a_survivor_outranks_a_weakened_candidate_with_a_better_score():
    """Verdict tiers; score only orders within a tier. Prefer what withstood
    criticism, and among equals prefer the stronger business."""
    got = run(
        [candidate("WEAK", score=0.95), candidate("SOUND", score=0.40)],
        [critique("WEAK", severities=["material", "material"]), critique("SOUND")],
    )
    assert [c.ticker for c, _ in got.selected] == ["SOUND", "WEAK"]


def test_score_orders_within_a_tier():
    got = run(
        [candidate("LOW", score=0.30), candidate("HIGH", score=0.80)],
        [critique("LOW"), critique("HIGH")],
    )
    assert [c.ticker for c, _ in got.selected] == ["HIGH", "LOW"]


def test_a_weakened_candidate_is_still_selectable():
    """It ranks below a survivor; it is not excluded."""
    got = run([candidate("W")], [critique("W", severities=["material", "material"])])
    assert [c.ticker for c, _ in got.selected] == ["W"]


def test_a_disqualified_candidate_never_reaches_the_ranking():
    got = run([candidate("D")], [critique("D", severities=["critical"])])
    assert got.selected == []
    assert got.excluded[0].reason == "disqualified_by_risk"
    assert "critical problem" in got.excluded[0].detail


# --- Restrictions are checked first ------------------------------------------


def test_a_restricted_company_is_excluded_before_quality_is_considered():
    """A company the investor ruled out is not a close call to be weighed
    against a good score, and "outside the top three" would imply it was in
    the running."""
    got = run(
        [candidate("OIL", name="Fossil Fuel Energy", score=0.99)],
        [critique("OIL")],
        restrictions=["No fossil fuel companies"],
    )
    assert got.selected == []
    assert got.excluded[0].reason == "restriction_violation"


def test_a_restriction_is_matched_against_themes_and_rationale_too():
    got = run(
        [candidate("X", rationale="a major coal producer")],
        [critique("X")],
        restrictions=["No coal, oil or gas"],
    )
    assert got.excluded[0].reason == "restriction_violation"


def test_generic_words_in_a_restriction_never_exclude_everything():
    """"No fossil fuel companies" must not match on "companies"."""
    assert set(restriction_terms(["No fossil fuel companies"])) == {"fossil", "fuel"}
    assert restriction_terms(["No cryptocurrency or digital asset companies"]) == [
        "cryptocurrency", "digital", "asset"
    ]


def test_an_investor_with_no_restrictions_excludes_nothing():
    got = run([candidate("A")], [critique("A")])
    assert got.excluded == []


# --- The cap and the accounting ----------------------------------------------


def test_at_most_three_are_selected_and_the_rest_are_recorded():
    cands = [candidate(f"T{i}", score=0.9 - i / 100) for i in range(5)]
    crits = [critique(f"T{i}") for i in range(5)]

    got = run(cands, crits)

    assert len(got.selected) == 3
    beyond = [e for e in got.excluded if e.reason == "outside_top_three"]
    assert len(beyond) == 2
    assert "ranked 4 of 5 eligible" in beyond[0].detail


def test_every_candidate_ends_as_a_selection_or_a_recorded_exclusion():
    """A company that vanished between the ranking and the output would be the
    one failure a reader could never detect."""
    cands = [candidate(f"T{i}", score=0.9 - i / 100) for i in range(6)]
    crits = [
        critique("T0"),
        critique("T1", severities=["critical"]),
        critique("T2", skipped="cap"),
        critique("T3"),
        critique("T4"),
        critique("T5"),
    ]

    got = run(cands, crits)
    accounted = {c.ticker for c, _ in got.selected} | {e.ticker for e in got.excluded}
    assert accounted == {f"T{i}" for i in range(6)}
