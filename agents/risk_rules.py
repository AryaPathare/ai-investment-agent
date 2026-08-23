"""Fundamental risks, derived in Python from numbers Agent 3 already measured.

WHY THESE ARE NOT PRODUCED BY THE MODEL

The same argument as the ranking code: a model handed a balance sheet and asked
"what could go wrong financially" writes fluent sentences whose relationship to
the numbers is unverifiable. It will say leverage is elevated whether the ratio
is 0.4 or 4.0, because that sentence is always plausible.

Every risk below is a comparison against a stated threshold, applied identically
to every company. The same inputs always produce the same risks, and a reader
can check any of them against the metric recorded alongside it.

This also gives Agent 4 a FLOOR. News retrieval can return nothing — a small
company in a quiet week produces no bear-case articles at all — and without
these rules the critic would then report "no risks found", which reads as
reassurance when it only means nothing was published.

ONLY SIGNS AND RATIOS, NEVER MAGNITUDES

``net_income`` and ``free_cash_flow`` arrive in whatever currency the company
reports in — won, rupees, dollars. So these rules test only whether such a
figure is NEGATIVE, never how large it is. A threshold on the magnitude would
compare 162 trillion won against 8 billion dollars and conclude something
absurd. The four ComparableMetrics are ratios and are safe to threshold.

WHAT IS DELIBERATELY ABSENT

Nothing here is ``critical``. Agent 3's screen already rejects the genuinely
disqualifying cases - catastrophic losses, companies both shrinking and
unprofitable, companies with too little data to judge - so anything reaching
Agent 4 has passed that bar. A fundamental rule issuing a critical verdict here
would be re-litigating a decision already made, on the same numbers.

Leverage in particular is capped at ``material`` on purpose. The screening code
explains why a blanket leverage threshold is wrong: banks, insurers and
utilities carry ratios that would look alarming in a semiconductor company and
are entirely normal for them. Sector is not available on a candidate, so a
critical leverage rule would silently condemn every financial company. Flagging
it as material states the fact without pretending to know the context.
"""

from __future__ import annotations

from models.companies import CompanyCandidate
from models.risk import Risk

# Above this, leverage is high enough to matter to the decision in any sector.
HIGH_LEVERAGE = 3.0

# Between this and HIGH_LEVERAGE, worth recording but not worth weighing much.
ELEVATED_LEVERAGE = 1.5

# Below this, the company keeps little of each unit of revenue after the direct
# cost of producing it, which is the usual signature of an absent moat. Normal
# for distribution and retail, hence minor rather than material.
THIN_GROSS_MARGIN = 0.15


def _risk(candidate: CompanyCandidate, *, risk_type, severity, claim, metric, value) -> Risk:
    """One fundamental risk, grounded in the metric that produced it."""
    return Risk(
        ticker=candidate.ticker,
        risk_type=risk_type,
        severity=severity,
        claim=claim,
        article_ids=[],
        metric=metric,
        metric_value=value,
    )


def fundamental_risks(candidate: CompanyCandidate) -> list[Risk]:
    """Every threshold this candidate's numbers cross, as grounded risks.

    Returns an empty list for a company whose fundamentals are unremarkable,
    which is the correct and common answer. These rules are meant to catch the
    specific and the checkable, not to guarantee that criticism was produced.
    """
    metrics = candidate.fundamentals.comparable
    amounts = candidate.fundamentals.amounts
    risks: list[Risk] = []

    # --- The growth story is not in the numbers ------------------------------
    # Filed as thesis_invalidation rather than financial: the company was
    # selected because a theme was supposed to be driving it, and revenue going
    # backwards is direct evidence against that, not merely a weak quarter.
    if metrics.revenue_growth is not None and metrics.revenue_growth < 0:
        risks.append(_risk(
            candidate,
            risk_type="thesis_invalidation",
            severity="material",
            claim=(
                "Revenue is shrinking, so the theme this company was selected "
                "for is not yet showing up in what it sells."
            ),
            metric="revenue_growth",
            value=metrics.revenue_growth,
        ))

    # --- Loss-making before financing and one-offs ---------------------------
    if metrics.operating_margin is not None and metrics.operating_margin < 0:
        risks.append(_risk(
            candidate,
            risk_type="financial",
            severity="material",
            claim=(
                "The core business loses money before financing and one-off "
                "items, so scale alone does not fix it."
            ),
            metric="operating_margin",
            value=metrics.operating_margin,
        ))

    # --- Profitable operationally, loss-making overall -----------------------
    # Only when the operating line is healthy, so this never double-counts the
    # rule above. A distinct and genuinely informative signal: the operations
    # work and something below them - interest, write-downs, tax - does not.
    elif (
        amounts.net_income is not None
        and amounts.net_income < 0
        and metrics.operating_margin is not None
    ):
        risks.append(_risk(
            candidate,
            risk_type="financial",
            severity="minor",
            claim=(
                "Operations are profitable but the company still loses money "
                "overall, so the cost sits below the operating line."
            ),
            metric="net_income_is_negative",
            value=-1.0,
        ))

    # --- Leverage ------------------------------------------------------------
    debt = metrics.debt_to_equity
    if debt is not None and debt > HIGH_LEVERAGE:
        risks.append(_risk(
            candidate,
            risk_type="financial",
            severity="material",
            claim=(
                "Debt is large relative to equity, so a downturn is absorbed by "
                "creditors' terms before shareholders get a say."
            ),
            metric="debt_to_equity",
            value=debt,
        ))
    elif debt is not None and debt > ELEVATED_LEVERAGE:
        risks.append(_risk(
            candidate,
            risk_type="financial",
            severity="minor",
            claim="Leverage is above the level at which it starts to constrain choices.",
            metric="debt_to_equity",
            value=debt,
        ))

    # --- Cash burn -----------------------------------------------------------
    # Minor, not material: negative free cash flow is the normal condition of a
    # company investing ahead of revenue, which is often exactly the thesis.
    if amounts.free_cash_flow is not None and amounts.free_cash_flow < 0:
        risks.append(_risk(
            candidate,
            risk_type="financial",
            severity="minor",
            claim=(
                "Free cash flow is negative, so growth is being funded from the "
                "balance sheet rather than from the business."
            ),
            metric="free_cash_flow_is_negative",
            value=-1.0,
        ))

    # --- Little pricing power ------------------------------------------------
    if metrics.gross_margin is not None and metrics.gross_margin < THIN_GROSS_MARGIN:
        risks.append(_risk(
            candidate,
            risk_type="competitive",
            severity="minor",
            claim=(
                "Gross margin is thin, which usually means the product competes "
                "on price and has little room to absorb cost increases."
            ),
            metric="gross_margin",
            value=metrics.gross_margin,
        ))

    return risks
