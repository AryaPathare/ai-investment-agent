"""Financial screening and ranking. Pure Python, no model involved.

WHY THERE IS NO LLM IN THIS FILE
--------------------------------
It would be easy to hand the fundamentals to a model and ask for a score out of
100. It would also be worthless. Asked to score a company 0-100 on its
financials, a model returns 72 or 80 with nothing behind it - not reproducible
between runs, not comparable between companies, and impossible to explain.

Everything here is arithmetic over numbers that came from a financial data
provider. The same inputs always give the same score, every component can be
inspected, and when a ranking looks wrong you can find out exactly which term
caused it.

The model contributes exactly ONE input: whether the company is directly,
partially, or incidentally exposed to the theme. That is a judgement about prose,
which is what models are for. The arithmetic is not.

ABOUT THE THRESHOLDS
--------------------
The numbers below are deliberate judgement calls, not empirical findings. A 30%
revenue growth rate scoring full marks is a choice, and a defensible different
choice exists.

The difference from a model-generated score is not that these are objectively
right - it is that they are VISIBLE, CONSISTENT and CHANGEABLE. They sit in one
file, apply identically to every company, and can be adjusted deliberately with
the effect measured. A model's internal 0-100 scale has none of those
properties.
"""

from __future__ import annotations

from dataclasses import dataclass

from models.companies import ComparableMetrics, ExposureLevel

# Below this share of available metrics a company is not ranked at all. Scoring
# a company on one number and presenting it beside one scored on four would be
# false confidence dressed as a comparison.
MIN_COMPLETENESS = 0.5

# How much a theme connection counts. Incidental is zero: a company that merely
# appeared in the same article as a theme has no business being recommended
# because of it, however good its balance sheet.
EXPOSURE_WEIGHTS: dict[ExposureLevel, float] = {
    "direct": 1.0,
    "partial": 0.6,
    "incidental": 0.0,
}

# Relative importance of each metric. Growth and profitability lead because they
# describe whether the business is working; leverage is a risk qualifier, and
# gross margin is a proxy for pricing power.
METRIC_WEIGHTS = {
    "revenue_growth": 0.30,
    "operating_margin": 0.30,
    "gross_margin": 0.20,
    "debt_to_equity": 0.20,
}


@dataclass(frozen=True)
class ScoreBreakdown:
    """Every term that produced a score, kept for inspection.

    A single number tells you a company ranked third. This tells you why, which
    is what makes a surprising ranking debuggable instead of mysterious.
    """

    components: dict[str, float]
    base: float
    exposure: ExposureLevel
    exposure_weight: float
    completeness: float
    total: float


def _ramp(value: float | None, low: float, high: float) -> float | None:
    """Map a value onto 0-1, flat outside the range. None stays None.

    ``None`` is never treated as zero. A missing metric is unknown, not bad, and
    conflating the two would rank a company with unreported margins below one
    with genuinely terrible margins.
    """
    if value is None:
        return None
    if high == low:
        return 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


def _inverse_ramp(value: float | None, good: float, bad: float) -> float | None:
    """Like ``_ramp`` but lower is better, e.g. leverage."""
    if value is None:
        return None
    if bad == good:
        return 0.0
    return max(0.0, min(1.0, (bad - value) / (bad - good)))


def component_scores(metrics: ComparableMetrics) -> dict[str, float]:
    """Score each available metric on 0-1. Missing metrics are omitted."""
    raw = {
        # Flat revenue scores zero; 30% growth or better scores full marks.
        "revenue_growth": _ramp(metrics.revenue_growth, 0.0, 0.30),
        # Break-even scores zero; a 25% operating margin scores full marks.
        "operating_margin": _ramp(metrics.operating_margin, 0.0, 0.25),
        # Below 20% gross margin scores zero; 60% or better scores full marks.
        "gross_margin": _ramp(metrics.gross_margin, 0.20, 0.60),
        # Debt/equity of 0.5 or less is unpenalised; 3.0 or more scores zero.
        # Note this is a RATIO - the client normalises yfinance's percentage.
        "debt_to_equity": _inverse_ramp(metrics.debt_to_equity, 0.5, 3.0),
    }
    return {name: value for name, value in raw.items() if value is not None}


def screen(metrics: ComparableMetrics) -> tuple[bool, str | None]:
    """Decide whether a company is worth ranking at all.

    Rejection is reserved for cases that are genuinely disqualifying. Screening
    a company out on one weak metric would discard good businesses for a single
    soft quarter, which is why leverage and margin pressure are handled as score
    PENALTIES rather than rejections.

    Note what is deliberately NOT a rejection rule: high debt-to-equity on its
    own. Banks, insurers and utilities carry leverage that would look alarming
    in a semiconductor company and is entirely normal for them. A blanket
    threshold would silently exclude every financial company from a system that
    is supposed to research banking themes.

    Returns:
        (passed, reason). ``reason`` matches a DropReason when passed is False.
    """
    if metrics.completeness < MIN_COMPLETENESS:
        return False, "no_fundamentals"

    shrinking = metrics.revenue_growth is not None and metrics.revenue_growth < 0
    unprofitable = metrics.operating_margin is not None and metrics.operating_margin < 0

    # Both together, not either alone. A profitable company can have a flat year,
    # and a fast-growing one can still be investing ahead of profit. Shrinking
    # AND losing money at the same time is a different situation.
    if shrinking and unprofitable:
        return False, "failed_screen"

    return True, None


def score(metrics: ComparableMetrics, exposure: ExposureLevel) -> ScoreBreakdown:
    """Rank a company from its fundamentals and its link to the theme.

    The base score averages the available metric scores, weighted by importance
    and renormalised over what is present, so a missing metric neither counts as
    zero nor silently inflates the others.

    That base is then multiplied by two factors:

    * ``exposure_weight`` - an incidental company scores zero no matter how good
      its financials, because the reason it is here does not hold.
    * ``completeness`` - a company judged on two metrics ranks below an equally
      good one judged on four. Less evidence should mean less confidence, and
      the ranking is the only place that can be expressed.
    """
    components = component_scores(metrics)

    available_weight = sum(METRIC_WEIGHTS[name] for name in components)
    if available_weight == 0:
        base = 0.0
    else:
        base = (
            sum(METRIC_WEIGHTS[name] * value for name, value in components.items())
            / available_weight
        )

    exposure_weight = EXPOSURE_WEIGHTS[exposure]
    completeness = metrics.completeness
    total = base * exposure_weight * completeness

    return ScoreBreakdown(
        components=components,
        base=round(base, 4),
        exposure=exposure,
        exposure_weight=exposure_weight,
        completeness=completeness,
        total=round(total, 4),
    )
