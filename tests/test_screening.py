"""Tests for financial screening and ranking.

Pure arithmetic, no model and no network. These are the tests that make the
"compute the score in Python" argument real: every case here has one correct
answer, which is exactly what a model-generated score could never offer.
"""

import pytest

from agents.screening import (
    EXPOSURE_WEIGHTS,
    MIN_COMPLETENESS,
    component_scores,
    score,
    screen,
)
from models.companies import ComparableMetrics


def metrics(**overrides) -> ComparableMetrics:
    base = dict(
        revenue_growth=0.20,
        operating_margin=0.15,
        gross_margin=0.45,
        debt_to_equity=0.5,
    )
    return ComparableMetrics(**{**base, **overrides})


# --- Screening ---------------------------------------------------------------


def test_a_healthy_company_passes():
    assert screen(metrics()) == (True, None)


def test_shrinking_but_profitable_passes():
    """One soft quarter must not disqualify a working business."""
    passed, _ = screen(metrics(revenue_growth=-0.05, operating_margin=0.18))
    assert passed


def test_growing_but_not_yet_profitable_passes():
    """Investing ahead of profit is a strategy, not a disqualification."""
    passed, _ = screen(metrics(revenue_growth=0.40, operating_margin=-0.10))
    assert passed


def test_shrinking_and_unprofitable_together_fails():
    """Both at once is a different situation from either alone."""
    passed, reason = screen(metrics(revenue_growth=-0.15, operating_margin=-0.08))
    assert not passed
    assert reason == "failed_screen"


def test_high_leverage_alone_does_not_disqualify():
    """THE rule that protects every bank, insurer and utility.

    A blanket debt-to-equity threshold would silently exclude every financial
    company from a system that is supposed to research banking themes.
    """
    passed, _ = screen(metrics(debt_to_equity=4.5))
    assert passed


def test_too_few_metrics_is_not_ranked():
    passed, reason = screen(ComparableMetrics(revenue_growth=0.2))
    assert not passed
    assert reason == "no_fundamentals"


def test_exactly_half_the_metrics_is_enough():
    """MIN_COMPLETENESS is inclusive; the boundary must not drift silently."""
    half = ComparableMetrics(revenue_growth=0.2, operating_margin=0.1)
    assert half.completeness == MIN_COMPLETENESS
    assert screen(half)[0]


def test_no_metrics_at_all_fails():
    assert screen(ComparableMetrics())[1] == "no_fundamentals"


# --- Component scoring -------------------------------------------------------


def test_missing_metrics_are_omitted_not_zeroed():
    """A missing metric is unknown, not bad. Conflating them ranks a company
    with unreported margins below one with genuinely terrible margins."""
    components = component_scores(ComparableMetrics(revenue_growth=0.30))
    assert set(components) == {"revenue_growth"}


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("revenue_growth", -0.50, 0.0),   # shrinking
        ("revenue_growth", 0.0, 0.0),     # flat
        ("revenue_growth", 0.15, 0.5),    # halfway
        ("revenue_growth", 0.30, 1.0),    # target
        ("revenue_growth", 2.00, 1.0),    # clamped, not extrapolated
        ("operating_margin", -0.20, 0.0),
        ("operating_margin", 0.25, 1.0),
        ("gross_margin", 0.20, 0.0),
        ("gross_margin", 0.60, 1.0),
    ],
)
def test_ramps_map_onto_zero_to_one(field, value, expected):
    got = component_scores(ComparableMetrics(**{field: value}))[field]
    assert got == pytest.approx(expected, abs=1e-9)


@pytest.mark.parametrize(
    "value,expected",
    [(0.0, 1.0), (0.5, 1.0), (1.75, 0.5), (3.0, 0.0), (10.0, 0.0)],
)
def test_leverage_scores_inversely(value, expected):
    """Lower debt is better, and the scale is a RATIO, not a percentage."""
    got = component_scores(ComparableMetrics(debt_to_equity=value))["debt_to_equity"]
    assert got == pytest.approx(expected, abs=1e-9)


# --- Total score -------------------------------------------------------------


def test_incidental_exposure_scores_zero_however_good_the_financials():
    """The reason the company is in the list does not hold, so nothing else
    about it matters."""
    perfect = metrics(revenue_growth=1.0, operating_margin=0.9, gross_margin=0.9,
                      debt_to_equity=0.0)
    assert score(perfect, "incidental").total == 0.0


def test_exposure_scales_the_whole_score():
    perfect = metrics(revenue_growth=1.0, operating_margin=0.9, gross_margin=0.9,
                      debt_to_equity=0.0)
    direct = score(perfect, "direct").total
    partial = score(perfect, "partial").total
    assert direct == pytest.approx(1.0)
    assert partial == pytest.approx(EXPOSURE_WEIGHTS["partial"])


def test_incomplete_data_ranks_below_equally_good_complete_data():
    """Less evidence must mean less confidence, and rank is where that shows."""
    complete = metrics(revenue_growth=0.30, operating_margin=0.25,
                       gross_margin=0.60, debt_to_equity=0.0)
    partial_data = ComparableMetrics(revenue_growth=0.30, operating_margin=0.25)

    assert score(partial_data, "direct").base == pytest.approx(
        score(complete, "direct").base
    )
    assert score(partial_data, "direct").total < score(complete, "direct").total


def test_unknown_metrics_beat_terrible_metrics_on_base_score():
    unknown = ComparableMetrics(revenue_growth=0.30, operating_margin=0.20)
    terrible = metrics(revenue_growth=0.30, operating_margin=0.20,
                       gross_margin=0.0, debt_to_equity=5.0)
    assert score(unknown, "direct").base > score(terrible, "direct").base


def test_breakdown_exposes_every_term():
    """A single number says a company ranked third; this says why."""
    breakdown = score(metrics(), "partial")
    assert set(breakdown.components) == {
        "revenue_growth", "operating_margin", "gross_margin", "debt_to_equity",
    }
    assert breakdown.exposure == "partial"
    assert breakdown.exposure_weight == EXPOSURE_WEIGHTS["partial"]
    assert breakdown.completeness == 1.0
    assert breakdown.total == pytest.approx(
        breakdown.base * breakdown.exposure_weight, abs=1e-4
    )


def test_scoring_is_deterministic():
    """The whole argument for computing this in Python rather than asking a
    model: the same inputs always give the same answer."""
    m = metrics()
    assert score(m, "direct").total == score(m, "direct").total


def test_a_company_with_no_usable_metrics_scores_zero():
    assert score(ComparableMetrics(), "direct").total == 0.0
