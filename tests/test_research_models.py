"""Tests for the Agent 2 schema — the structural guarantees.

The point of these models is that certain mistakes cannot be expressed. These
tests assert that the fields the model must NOT have really are absent, since
that is the whole anti-fabrication design and a well-meaning future edit could
undo it without anything else complaining.
"""

import pytest
from pydantic import ValidationError

from models.research import (
    Article,
    Evidence,
    ResearchFindings,
    SearchQueries,
    Theme,
    ThemeProposal,
)
from tests.conftest import make_article


def evidence(article_id="A1", stance="supports"):
    return Evidence(article_id=article_id, stance=stance, relevance="r")


def theme(**overrides):
    base = dict(
        name="A theme",
        why_it_matters="Why it matters",
        industries=["energy"],
        timeframe="unclear",
        confidence="high",
        evidence=[evidence()],
    )
    return Theme(**{**base, **overrides})


# --- The anti-fabrication guarantee ------------------------------------------


def test_evidence_has_no_field_for_article_data():
    """A model that cannot write a url cannot invent a source.

    If this test fails, someone has added a field that lets the LLM author
    article data, and the grounding guarantee is gone.
    """
    assert set(Evidence.model_fields) == {"article_id", "stance", "relevance"}


def test_fabricated_article_fields_are_discarded():
    sneaky = Evidence(
        article_id="A1",
        stance="supports",
        relevance="r",
        url="https://invented.example.com/story",
        title="A headline that does not exist",
        published_at="2026-08-18",
    )
    dumped = sneaky.model_dump()
    assert "url" not in dumped
    assert "title" not in dumped
    assert "published_at" not in dumped


def test_a_theme_must_cite_at_least_one_article():
    """A theme citing nothing came from training data, not from the search."""
    with pytest.raises(ValidationError, match="cites no evidence"):
        theme(evidence=[])


def test_theme_proposal_cannot_carry_article_objects():
    """Articles live in their own list, populated by Python from the API."""
    assert set(ThemeProposal.model_fields) == {"themes", "notes"}


# --- Controlled vocabularies -------------------------------------------------


@pytest.mark.parametrize("value", ["very high", "HIGH", "80", ""])
def test_invalid_confidence_is_rejected(value):
    with pytest.raises(ValidationError):
        theme(confidence=value)


@pytest.mark.parametrize("value", ["soon", "next year", "2026", ""])
def test_invalid_timeframe_is_rejected(value):
    with pytest.raises(ValidationError):
        theme(timeframe=value)


@pytest.mark.parametrize("value", ["supports", "weakens", "complicates"])
def test_all_three_stances_are_accepted(value):
    """'weakens' must be expressible, or contradicting evidence gets hidden."""
    assert evidence(stance=value).stance == value


def test_invalid_stance_is_rejected():
    with pytest.raises(ValidationError):
        evidence(stance="proves")


# --- SearchQueries normalisation ---------------------------------------------


def test_queries_are_trimmed_and_collapsed():
    assert SearchQueries(queries=["  solar   power  "]).queries == ["solar power"]


def test_duplicate_queries_are_removed_case_insensitively():
    """A repeated query spends a daily request to fetch what we already have."""
    result = SearchQueries(queries=["AI chips", "ai chips", "AI CHIPS", "grid storage"])
    assert result.queries == ["AI chips", "grid storage"]


def test_blank_queries_are_dropped():
    assert SearchQueries(queries=["", "   ", "solar"]).queries == ["solar"]


def test_all_blank_queries_is_an_error():
    with pytest.raises(ValidationError, match="no usable search queries"):
        SearchQueries(queries=["", "   "])


# --- ResearchFindings --------------------------------------------------------


def test_empty_findings_report_found_nothing():
    assert ResearchFindings().found_nothing is True


def test_findings_with_themes_do_not_report_found_nothing():
    assert ResearchFindings(themes=[theme()]).found_nothing is False


def test_article_lookup_by_uuid():
    article = make_article("uuid-1", "A headline")
    findings = ResearchFindings(articles=[article])

    assert findings.article_by_id("uuid-1") is article
    assert findings.article_by_id("not-there") is None


def test_article_text_concatenates_what_we_know():
    article = make_article(title="T", description="D", snippet="S")
    assert article.text == "T\nD\nS"


def test_article_requires_the_fields_agent_3_will_need():
    with pytest.raises(ValidationError):
        Article(uuid="u", title="t")  # no url, source or published_at
