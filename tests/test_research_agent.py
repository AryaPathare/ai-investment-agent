"""Tests for Agent 2's orchestration: citation validation and assembly.

Both the news API and the LLM are replaced with fakes, so these tests are fast
and deterministic. What is being checked is OUR logic — that invented citations
are discarded, that ungrounded themes are dropped, that caps are recorded rather
than applied silently.

Whether the model picks GOOD themes is model behaviour and belongs in the eval
suite, not here.
"""

import pytest

from agents import research_agent
from agents.research_agent import (
    _format_articles,
    _resolve_citations,
    research_themes,
)
from models.research import (
    Article,
    Evidence,
    ResearchFindings,
    SearchQueries,
    Theme,
    ThemeProposal,
)
from tests.conftest import make_article


def theme(name="A theme", ids=("A1",), confidence="high"):
    return Theme(
        name=name,
        why_it_matters="It matters to this investor.",
        industries=["energy"],
        timeframe="unclear",
        confidence=confidence,
        evidence=[Evidence(article_id=i, stance="supports", relevance="r") for i in ids],
    )


@pytest.fixture
def mapping(articles):
    """The label -> Article mapping the model was shown."""
    return {"A1": articles[0], "A2": articles[1], "A3": articles[2]}


# --- Article formatting ------------------------------------------------------


def test_articles_are_labelled_sequentially(articles):
    rendered, mapping = _format_articles(articles)
    assert list(mapping) == ["A1", "A2", "A3"]
    assert "[A1]" in rendered and "[A3]" in rendered


def test_rendered_articles_include_the_text_the_model_needs(articles):
    rendered, _ = _format_articles(articles)
    for article in articles:
        assert article.title in rendered
        assert article.source in rendered


def test_formatting_no_articles_yields_nothing(articles):
    rendered, mapping = _format_articles([])
    assert rendered == "" and mapping == {}


# --- Citation validation: the core guarantee ---------------------------------


def test_valid_citations_are_rewritten_to_real_uuids(mapping, articles):
    """Agent 3 matches evidence against Article.uuid, so labels must be resolved."""
    kept, problems = _resolve_citations(ThemeProposal(themes=[theme(ids=("A1", "A2"))]), mapping)

    assert problems == []
    assert [e.article_id for e in kept[0].evidence] == [articles[0].uuid, articles[1].uuid]


def test_a_citation_to_an_article_never_retrieved_is_discarded(mapping):
    """The schema cannot catch this: it has no idea what was retrieved."""
    kept, problems = _resolve_citations(
        ThemeProposal(themes=[theme(ids=("A1", "A99"))]), mapping
    )

    assert len(kept) == 1
    assert len(kept[0].evidence) == 1
    assert any("dropped 1 citation" in p for p in problems)


def test_a_theme_whose_every_citation_is_invented_is_dropped(mapping):
    """An ungrounded theme is exactly what searching first was meant to prevent."""
    kept, problems = _resolve_citations(
        ThemeProposal(themes=[theme(name="Invented", ids=("A88", "A99"))]), mapping
    )

    assert kept == []
    assert any("dropped entirely" in p for p in problems)


def test_a_good_theme_survives_alongside_a_fabricated_one(mapping):
    kept, _ = _resolve_citations(
        ThemeProposal(themes=[theme(name="Real", ids=("A1",)),
                              theme(name="Fake", ids=("A77",))]),
        mapping,
    )
    assert [t.name for t in kept] == ["Real"]


def test_dropping_citations_does_not_mutate_the_original(mapping):
    """model_copy, not in-place edits: the proposal stays inspectable."""
    proposal = ThemeProposal(themes=[theme(ids=("A1", "A99"))])
    _resolve_citations(proposal, mapping)
    assert len(proposal.themes[0].evidence) == 2


# --- Full pipeline, with both external calls faked ---------------------------


@pytest.fixture
def fake_pipeline(monkeypatch, articles):
    """Replace query generation, news search and theme synthesis."""

    state = {"queries": ["q1", "q2"], "articles": articles, "proposal": None, "searched": []}

    def fake_queries(profile):
        return SearchQueries(queries=state["queries"])

    def fake_search(queries, **kwargs):
        state["searched"] = list(queries)
        return state["articles"], list(queries)

    def fake_themes(profile, arts):
        _, mapping = _format_articles(arts)
        return state["proposal"], mapping

    monkeypatch.setattr(research_agent, "generate_search_queries", fake_queries)
    monkeypatch.setattr(research_agent, "search_many", fake_search)
    monkeypatch.setattr(research_agent, "synthesise_themes", fake_themes)
    return state


def test_an_unvalidated_profile_is_refused(blocked_profile):
    """Researching contradictory preferences wastes requests on ruled-out areas."""
    with pytest.raises(ValueError, match="unvalidated profile"):
        research_themes(blocked_profile)


def test_happy_path_returns_grounded_findings(fake_pipeline, research_profile, articles):
    fake_pipeline["proposal"] = ThemeProposal(themes=[theme(ids=("A1", "A2"))])
    findings = research_themes(research_profile)

    assert isinstance(findings, ResearchFindings)
    assert len(findings.themes) == 1
    assert findings.articles_retrieved == 3
    assert not findings.found_nothing


def test_only_cited_articles_are_attached(fake_pipeline, research_profile, articles):
    """Agent 3 should receive the evidence, not the whole retrieval pool."""
    fake_pipeline["proposal"] = ThemeProposal(themes=[theme(ids=("A1",))])
    findings = research_themes(research_profile)

    assert [a.uuid for a in findings.articles] == [articles[0].uuid]
    assert findings.articles_retrieved == 3


def test_every_citation_resolves_to_an_attached_article(fake_pipeline, research_profile):
    fake_pipeline["proposal"] = ThemeProposal(themes=[theme(ids=("A1", "A3"))])
    findings = research_themes(research_profile)

    for t in findings.themes:
        for e in t.evidence:
            assert findings.article_by_id(e.article_id) is not None


def test_no_articles_retrieved_returns_empty_findings(fake_pipeline, research_profile):
    fake_pipeline["articles"] = []
    findings = research_themes(research_profile)

    assert findings.found_nothing
    assert findings.themes == []
    assert "No articles were retrieved" in findings.notes


def test_no_themes_found_is_a_legitimate_outcome(fake_pipeline, research_profile):
    """Returning nothing is a designed answer, not a failure."""
    fake_pipeline["proposal"] = ThemeProposal(themes=[], notes="Nothing worth pursuing.")
    findings = research_themes(research_profile)

    assert findings.found_nothing
    assert "Nothing worth pursuing" in findings.notes


def test_too_many_queries_are_capped_and_the_cap_is_recorded(
    fake_pipeline, research_profile
):
    """Silent truncation reads as 'this is everything' when it is not."""
    fake_pipeline["queries"] = [f"q{i}" for i in range(20)]
    fake_pipeline["proposal"] = ThemeProposal(themes=[theme(ids=("A1",))])

    findings = research_themes(research_profile)

    assert len(fake_pipeline["searched"]) == 6
    assert "ran the first 6" in findings.notes


def test_too_many_themes_are_capped_keeping_highest_confidence(
    fake_pipeline, research_profile
):
    fake_pipeline["proposal"] = ThemeProposal(
        themes=[
            theme(name="low1", ids=("A1",), confidence="low"),
            theme(name="high1", ids=("A1",), confidence="high"),
            theme(name="low2", ids=("A2",), confidence="low"),
            theme(name="high2", ids=("A2",), confidence="high"),
            theme(name="med1", ids=("A3",), confidence="medium"),
            theme(name="low3", ids=("A3",), confidence="low"),
        ]
    )
    findings = research_themes(research_profile)

    assert len(findings.themes) == 5
    assert {"high1", "high2"} <= {t.name for t in findings.themes}
    assert "low3" not in {t.name for t in findings.themes}
    assert "Kept the 5 highest-confidence" in findings.notes


def test_failed_searches_are_reported(monkeypatch, fake_pipeline, research_profile):
    """A partial retrieval should say so, not quietly present itself as complete."""
    def partial_search(queries, **kwargs):
        return fake_pipeline["articles"], list(queries)[:1]

    monkeypatch.setattr(research_agent, "search_many", partial_search)
    fake_pipeline["proposal"] = ThemeProposal(themes=[theme(ids=("A1",))])

    findings = research_themes(research_profile)
    assert "searches failed" in findings.notes


def test_fabricated_citations_are_reported_in_notes(fake_pipeline, research_profile):
    fake_pipeline["proposal"] = ThemeProposal(
        themes=[theme(name="Partly made up", ids=("A1", "A404"))]
    )
    findings = research_themes(research_profile)

    assert "dropped 1 citation" in findings.notes
    assert len(findings.themes[0].evidence) == 1
