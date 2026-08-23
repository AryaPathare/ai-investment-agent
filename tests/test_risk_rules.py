"""Tests for the deterministic fundamental risk rules.

No model, no network. These assert that a threshold fires when it should, stays
quiet when it should not, and always records the metric that produced it — the
last being what separates a checkable finding from an assertion.
"""

import pytest

from agents.risk_rules import (
    ELEVATED_LEVERAGE,
    HIGH_LEVERAGE,
    THIN_GROSS_MARGIN,
    fundamental_risks,
)
from models.companies import (
    CompanyCandidate,
    ComparableMetrics,
    CurrencyAmounts,
    Fundamentals,
)


def candidate(*, net_income=5.0, free_cash_flow=5.0, **metrics):
    base = dict(revenue_growth=0.20, operating_margin=0.15,
                gross_margin=0.45, debt_to_equity=0.4)
    return CompanyCandidate(
        ticker="TST",
        name="Test Co",
        exchange="NMS",
        currency="USD",
        fundamentals=Fundamentals(
            comparable=ComparableMetrics(**{**base, **metrics}),
            amounts=CurrencyAmounts(currency="USD", net_income=net_income,
                                    free_cash_flow=free_cash_flow),
            source="fmp",
        ),
        exposure="direct",
        exposure_rationale="builds the thing the theme is about",
        evidence_article_ids=["uuid-1"],
        screen_score=0.6,
    )


def types_and_severities(risks):
    return {(r.risk_type, r.severity) for r in risks}


# --- Silence is a valid answer -----------------------------------------------


def test_an_unremarkable_company_produces_no_fundamental_risks():
    """These rules catch the specific and checkable. They are not there to
    guarantee that criticism was produced."""
    assert fundamental_risks(candidate()) == []


# --- Every risk is grounded --------------------------------------------------


def test_every_fundamental_risk_records_the_metric_that_produced_it():
    """Grounding is the whole point. A rule that fires without naming its
    metric is indistinguishable from an opinion."""
    risks = fundamental_risks(candidate(revenue_growth=-0.1, debt_to_equity=4.0))
    assert risks
    for r in risks:
        assert r.is_fundamental
        assert r.metric
        assert r.metric_value is not None
        assert r.article_ids == []


def test_risks_carry_the_candidates_ticker():
    risks = fundamental_risks(candidate(revenue_growth=-0.1))
    assert all(r.ticker == "TST" for r in risks)


# --- Individual rules --------------------------------------------------------


def test_shrinking_revenue_is_filed_as_thesis_invalidation():
    """Not merely 'financial'. The company was picked because a theme was
    supposed to be driving it; revenue going backwards is evidence against
    that, which is a different claim from a weak balance sheet."""
    risks = fundamental_risks(candidate(revenue_growth=-0.05))
    assert ("thesis_invalidation", "material") in types_and_severities(risks)


def test_flat_revenue_does_not_fire():
    assert fundamental_risks(candidate(revenue_growth=0.0)) == []


def test_an_operating_loss_is_material():
    risks = fundamental_risks(candidate(operating_margin=-0.2))
    assert ("financial", "material") in types_and_severities(risks)


def test_high_leverage_is_material_and_moderate_leverage_is_minor():
    high = fundamental_risks(candidate(debt_to_equity=HIGH_LEVERAGE + 0.1))
    mid = fundamental_risks(candidate(debt_to_equity=ELEVATED_LEVERAGE + 0.1))

    assert [r.severity for r in high] == ["material"]
    assert [r.severity for r in mid] == ["minor"]


def test_leverage_never_reaches_critical():
    """A critical leverage rule would silently condemn every bank and utility,
    which is exactly the blanket threshold the screening code refuses to use.
    Sector is not available here, so the rule states the fact without
    pretending to know the context."""
    risks = fundamental_risks(candidate(debt_to_equity=50.0))
    assert all(r.severity != "critical" for r in risks)


def test_negative_free_cash_flow_is_only_minor():
    """The normal condition of a company investing ahead of revenue, which is
    frequently the thesis itself."""
    risks = fundamental_risks(candidate(free_cash_flow=-3.0))
    assert [r.severity for r in risks] == ["minor"]


def test_a_thin_gross_margin_is_a_competitive_risk():
    risks = fundamental_risks(candidate(gross_margin=THIN_GROSS_MARGIN - 0.01))
    assert ("competitive", "minor") in types_and_severities(risks)


# --- No double counting ------------------------------------------------------


def test_an_operating_loss_does_not_also_fire_the_net_income_rule():
    """Both would be true at once and would report the same problem twice,
    inflating the severity count that the verdict is computed from."""
    risks = fundamental_risks(candidate(operating_margin=-0.2, net_income=-10.0))
    metrics = [r.metric for r in risks]
    assert "operating_margin" in metrics
    assert "net_income_is_negative" not in metrics


def test_profitable_operations_with_an_overall_loss_is_its_own_signal():
    """A distinct and informative case: the operations work and something below
    them — interest, write-downs, tax — does not."""
    risks = fundamental_risks(candidate(operating_margin=0.15, net_income=-10.0))
    assert [r.metric for r in risks] == ["net_income_is_negative"]
    assert risks[0].severity == "minor"


# --- Currency safety ---------------------------------------------------------


def test_only_the_sign_of_a_cash_figure_is_used_never_its_magnitude():
    """net_income and free_cash_flow arrive in local currency. A threshold on
    magnitude would compare 162 trillion won against 8 billion dollars. Two
    companies differing only in scale must produce identical risks."""
    small = fundamental_risks(candidate(net_income=-1.0, operating_margin=0.15))
    huge = fundamental_risks(candidate(net_income=-1.62e14, operating_margin=0.15))

    assert [r.metric for r in small] == [r.metric for r in huge]
    assert [r.severity for r in small] == [r.severity for r in huge]


def test_a_large_positive_cash_figure_never_fires_anything():
    assert fundamental_risks(candidate(net_income=1.62e14, free_cash_flow=5.5e13)) == []


# --- Missing data ------------------------------------------------------------


def test_a_missing_metric_never_fires_a_rule():
    """Unknown is not bad — the same rule the scoring code is built on. A
    company with unreported leverage must not be flagged as leveraged."""
    bare = ComparableMetrics(revenue_growth=0.2, operating_margin=0.1)
    c = candidate()
    c.fundamentals.comparable = bare
    c.fundamentals.amounts = CurrencyAmounts(currency="USD")

    assert fundamental_risks(c) == []


# --- Combination -------------------------------------------------------------


def test_several_thresholds_can_fire_at_once():
    risks = fundamental_risks(
        candidate(revenue_growth=-0.1, debt_to_equity=4.0,
                  gross_margin=0.05, free_cash_flow=-2.0)
    )
    assert len(risks) == 4
    assert sum(1 for r in risks if r.severity == "material") == 2
