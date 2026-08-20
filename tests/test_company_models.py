"""Tests for the Agent 3 schema — the structural guarantees.

These assert that certain mistakes cannot be EXPRESSED. They look trivial, and
that is the point: each one guards a design decision that a well-meaning future
edit could undo without anything else complaining.
"""

import pytest
from pydantic import ValidationError

from models.companies import (
    ComparableMetrics,
    CompanyCandidate,
    CompanyFindings,
    CompanyMention,
    CurrencyAmounts,
    DroppedCompany,
    ExposureVerdict,
    Fundamentals,
    MentionExtraction,
)


def fundamentals(**overrides):
    base = dict(revenue_growth=0.3, operating_margin=0.2,
                gross_margin=0.5, debt_to_equity=0.4)
    return Fundamentals(
        comparable=ComparableMetrics(**{**base, **overrides}),
        amounts=CurrencyAmounts(currency="USD", net_income=1.0, free_cash_flow=2.0),
        source="fmp",
    )


def candidate(**overrides):
    base = dict(
        ticker="NVDA", name="Nvidia", exchange="NMS", currency="USD",
        fundamentals=fundamentals(), exposure="direct",
        exposure_rationale="drives revenue", evidence_article_ids=["uuid-1"],
    )
    return CompanyCandidate(**{**base, **overrides})


# --- The model cannot write a ticker -----------------------------------------


def test_a_mention_has_no_ticker_field():
    """A guessed ticker does not look wrong. NVDA, NVDA.NE and NVD.DE are all
    real symbols for Nvidia, and the wrong one silently returns different
    financials. If this test fails, that protection is gone."""
    assert set(CompanyMention.model_fields) == {"name", "article_id", "context"}


def test_ticker_fields_passed_to_a_mention_are_discarded():
    sneaky = CompanyMention(name="Nvidia", article_id="A1", context="c",
                            ticker="NVDA", symbol="NVDA", exchange="NMS")
    dumped = sneaky.model_dump()
    assert "ticker" not in dumped
    assert "symbol" not in dumped


def test_extraction_carries_only_mentions():
    assert set(MentionExtraction.model_fields) == {"mentions"}


# --- Comparable ratios and currency amounts stay apart -----------------------


def test_ranking_metrics_and_currency_amounts_are_separate_types():
    """Ranking touches ComparableMetrics; CurrencyAmounts is display only.

    Kept as distinct types rather than a comment, because reaching the wrong one
    should require crossing a type boundary rather than reading a docstring.
    """
    assert set(ComparableMetrics.model_fields) == {
        "revenue_growth", "operating_margin", "gross_margin", "debt_to_equity",
    }
    assert set(CurrencyAmounts.model_fields) == {
        "currency", "net_income", "free_cash_flow",
    }


def test_no_absolute_amount_leaks_into_the_comparable_metrics():
    metrics = ComparableMetrics(revenue_growth=0.1, net_income=5.0,
                                free_cash_flow=3.0, currency="GBp")
    dumped = metrics.model_dump()
    assert "net_income" not in dumped
    assert "currency" not in dumped


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        (dict(revenue_growth=0.1, operating_margin=0.1,
              gross_margin=0.1, debt_to_equity=0.1), 1.0),
        (dict(revenue_growth=0.1, operating_margin=0.1), 0.5),
        (dict(revenue_growth=0.1), 0.25),
        (dict(), 0.0),
    ],
)
def test_completeness_counts_available_metrics(kwargs, expected):
    assert ComparableMetrics(**kwargs).completeness == expected


# --- Candidates must trace to evidence ---------------------------------------


def test_a_candidate_with_no_article_is_rejected():
    """Agent 3 analyses companies that Agent 2's articles surfaced. One tracing
    to nothing arrived some other way, which means the pipeline leaked."""
    with pytest.raises(ValidationError, match="cites no article"):
        candidate(evidence_article_ids=[])


def test_a_candidate_with_evidence_is_accepted():
    assert candidate().ticker == "NVDA"


# --- Controlled vocabularies -------------------------------------------------


@pytest.mark.parametrize("value", ["high", "strong", "DIRECT", "", "0.8"])
def test_invalid_exposure_levels_are_rejected(value):
    with pytest.raises(ValidationError):
        ExposureVerdict(company_id="C1", exposure=value, rationale="r")


@pytest.mark.parametrize("value", ["direct", "partial", "incidental"])
def test_the_three_exposure_levels_are_accepted(value):
    assert ExposureVerdict(company_id="C1", exposure=value, rationale="r").exposure == value


def test_invalid_drop_reasons_are_rejected():
    with pytest.raises(ValidationError):
        DroppedCompany(name="X", reason="i_didnt_like_it")


def test_invalid_data_sources_are_rejected():
    with pytest.raises(ValidationError):
        Fundamentals(comparable=ComparableMetrics(),
                     amounts=CurrencyAmounts(currency="USD"), source="bloomberg")


# --- CompanyFindings ---------------------------------------------------------


def test_empty_findings_report_found_nothing():
    assert CompanyFindings().found_nothing is True


def test_findings_with_candidates_do_not_report_found_nothing():
    assert CompanyFindings(candidates=[candidate()]).found_nothing is False


def test_drop_summary_counts_reasons_most_common_first():
    """The most useful debugging view in this agent: mostly no_ticker_found
    means the resolver is broken; mostly incidental_mention means extraction is
    too eager. Both look identical without it."""
    findings = CompanyFindings(dropped=[
        DroppedCompany(name="a", reason="incidental_mention"),
        DroppedCompany(name="b", reason="no_ticker_found"),
        DroppedCompany(name="c", reason="incidental_mention"),
        DroppedCompany(name="d", reason="incidental_mention"),
        DroppedCompany(name="e", reason="no_ticker_found"),
        DroppedCompany(name="f", reason="duplicate"),
    ])
    assert findings.drop_summary == {
        "incidental_mention": 3, "no_ticker_found": 2, "duplicate": 1,
    }
    assert list(findings.drop_summary)[0] == "incidental_mention"


def test_drop_summary_of_nothing_is_empty():
    assert CompanyFindings().drop_summary == {}
