"""Tests for the Agent 4 schema — the structural guarantees.

These assert that certain mistakes cannot be EXPRESSED. They look trivial, and
that is the point: each one guards a design decision that a well-meaning future
edit could undo without anything else complaining.

The one that matters most is ``must_be_grounded``. Without it, this agent's
output is indistinguishable from fluent guessing.
"""

import pytest
from pydantic import ValidationError

from models.risk import (
    CandidateCritique,
    NewsRiskAssessment,
    Risk,
    RiskFindings,
)


def risk(**overrides):
    base = dict(
        ticker="TSM",
        risk_type="competitive",
        severity="material",
        claim="A rival's new capacity lands in the segment carrying the margin.",
        article_ids=["uuid-1"],
    )
    return Risk(**{**base, **overrides})


# --- Grounding ---------------------------------------------------------------


def test_a_risk_citing_nothing_is_rejected():
    """THE central guarantee. A model asked to criticise will always produce
    something; only grounding separates a finding from a fluent sentence."""
    with pytest.raises(ValidationError, match="cites neither an article nor a metric"):
        Risk(
            ticker="TSM",
            risk_type="competitive",
            severity="material",
            claim="Competition is intense and margins may compress.",
        )


def test_an_article_alone_grounds_a_risk():
    assert risk(article_ids=["uuid-1"]).article_ids == ["uuid-1"]


def test_a_metric_alone_grounds_a_risk():
    """Fundamental risks have no article to cite — the number IS the evidence."""
    got = risk(article_ids=[], metric="debt_to_equity", metric_value=4.2)
    assert got.is_fundamental
    assert got.metric_value == pytest.approx(4.2)


def test_a_news_risk_is_not_marked_fundamental():
    assert not risk().is_fundamental


# --- Verdict is arithmetic, not opinion --------------------------------------


def critique(risks, **overrides):
    base = dict(ticker="TSM", name="TSMC", risks=risks, articles_reviewed=3)
    return CandidateCritique(**{**base, **overrides})


def test_one_critical_risk_disqualifies():
    """'The reason to hold this no longer holds' is not something two material
    risks add up to, so it is not modelled as a threshold on a total."""
    assert critique([risk(severity="critical")]).verdict == "disqualified"


def test_two_material_risks_weaken():
    assert critique([risk(severity="material"), risk(severity="material")]).verdict == "weakened"


def test_a_single_material_risk_does_not_weaken():
    """One material risk is the normal condition of every real company.
    Demoting on it would demote everything, which distinguishes nothing."""
    assert critique([risk(severity="material")]).verdict == "survives"


def test_minor_risks_never_accumulate_into_a_downgrade():
    assert critique([risk(severity="minor") for _ in range(5)]).verdict == "survives"


def test_severity_counts_are_reported_for_every_level():
    got = critique([risk(severity="critical"), risk(severity="minor")]).severity_counts
    assert got == {"critical": 1, "material": 0, "minor": 1}


# --- Effort is recorded, so silence is distinguishable from safety -----------


def test_a_skipped_candidate_is_marked_not_merely_empty():
    """An empty risk list means two very different things. Without the reason
    recorded, "no risks found" reads as reassurance when it may be silence."""
    got = critique([], skipped_reason="outside the per-run critique cap")
    assert not got.was_critiqued
    assert got.risks == []


def test_a_critiqued_candidate_with_no_risks_is_distinguishable_from_a_skipped_one():
    examined = critique([], queries_used=["TSM lawsuit"], articles_reviewed=4)
    skipped = critique([], skipped_reason="cap")

    assert examined.was_critiqued
    assert not skipped.was_critiqued
    # Both report the same verdict, which is exactly why was_critiqued exists.
    assert examined.verdict == skipped.verdict == "survives"


# --- Findings ----------------------------------------------------------------


def test_found_nothing_is_true_only_when_no_candidate_has_a_risk():
    empty = RiskFindings(critiques=[critique([]), critique([])])
    assert empty.found_nothing

    some = RiskFindings(critiques=[critique([]), critique([risk()])])
    assert not some.found_nothing


def test_disqualified_lists_the_tickers_a_critical_risk_ruled_out():
    findings = RiskFindings(
        critiques=[
            critique([risk(severity="critical")], ticker="AAA"),
            critique([risk(severity="minor")], ticker="BBB"),
        ]
    )
    assert findings.disqualified == ["AAA"]


def test_a_critique_can_be_looked_up_by_ticker():
    findings = RiskFindings(critiques=[critique([], ticker="AAA")])
    assert findings.critique_for("AAA").ticker == "AAA"
    assert findings.critique_for("ZZZ") is None


def test_discarded_risks_are_counted_not_hidden():
    """A number climbing here is the early warning that the model is inventing
    sources — invisible otherwise, because the output still looks clean."""
    assert RiskFindings(risks_discarded=3).risks_discarded == 3


# --- What the model is allowed to return -------------------------------------


def test_the_model_may_return_no_risks():
    """An empty list is a real finding: the articles showed nothing. Making
    this invalid would pressure the model into manufacturing something."""
    assert NewsRiskAssessment(risks=[]).risks == []


def test_the_model_cannot_return_an_ungrounded_risk_either():
    """The guarantee has to hold on the model's own envelope, not only after
    Python has assembled the output."""
    with pytest.raises(ValidationError):
        NewsRiskAssessment(
            risks=[{"ticker": "TSM", "risk_type": "competitive",
                    "severity": "material", "claim": "Vague worry."}]
        )


# --- The envelope, not the answer --------------------------------------------


def test_null_article_ids_is_treated_as_none_cited():
    """REGRESSION, found in Agent 5 and fixed here too: the model writes
    "article_ids": null when a risk is grounded in a metric rather than an
    article. That is correct, and it threw away the whole object."""
    got = Risk(ticker="TSM", risk_type="financial", severity="minor",
               claim="Leverage is elevated.", article_ids=None,
               metric="debt_to_equity", metric_value=2.7)
    assert got.article_ids == []
    assert got.is_fundamental


def test_null_article_ids_still_needs_a_metric_to_be_valid():
    """The transport is loosened; the contract is not."""
    with pytest.raises(ValidationError, match="cites neither an article nor a metric"):
        Risk(ticker="TSM", risk_type="financial", severity="minor",
             claim="Vague worry.", article_ids=None)
