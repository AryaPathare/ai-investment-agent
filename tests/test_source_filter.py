"""Tests for Agent 4's source filter.

It had none. The filter decides which evidence a risk critique is allowed to
rest on, and it is the last thing standing between a commentary blog and a
sentence a person reads as a reason not to invest.

The list itself is an editorial judgement and cannot be unit tested — whether
zerohedge.com does reporting a business decision could rest on is an argument,
not an assertion. What CAN be tested is everything around it: that entries are
written in a form the matcher can actually match, that dropping is reported
rather than silent, and that the filter does not quietly widen.
"""

import pytest

from clients.news import LOW_QUALITY_SOURCES, drop_low_quality
from tests.conftest import make_article


def test_a_listed_source_is_dropped():
    kept, dropped = drop_low_quality([make_article("u1", source="zerohedge.com")])
    assert kept == []
    assert dropped == ["zerohedge.com"]


def test_an_unlisted_source_is_kept():
    articles = [make_article("u1", source="reuters.com")]
    kept, dropped = drop_low_quality(articles)
    assert kept == articles
    assert dropped == []


def test_the_dropped_sources_are_returned_not_silently_discarded():
    """A filter that removes evidence without saying so is its own kind of
    unreliable narrator - the function's own docstring makes that argument."""
    _, dropped = drop_low_quality([
        make_article("u1", source="reuters.com"),
        make_article("u2", source="naturalnews.com"),
        make_article("u3", source="revolver.news"),
    ])
    assert sorted(dropped) == ["naturalnews.com", "revolver.news"]


def test_matching_is_case_insensitive():
    """Providers are not consistent about casing, and a source that slipped
    through on a capital letter would be invisible."""
    kept, dropped = drop_low_quality([make_article("u1", source="ZeroHedge.com")])
    assert kept == []
    assert dropped == ["ZeroHedge.com"], "the ORIGINAL casing should be reported"


def test_order_is_preserved_among_kept_articles():
    articles = [
        make_article("u1", source="reuters.com"),
        make_article("u2", source="zerohedge.com"),
        make_article("u3", source="ft.com"),
    ]
    kept, _ = drop_low_quality(articles)
    assert [a.uuid for a in kept] == ["u1", "u3"]


def test_an_empty_input_is_not_an_error():
    assert drop_low_quality([]) == ([], [])


@pytest.mark.parametrize("source", sorted(LOW_QUALITY_SOURCES))
def test_every_entry_is_written_in_a_form_the_matcher_can_match(source):
    """A real bug class, and a silent one.

    Matching is `article.source.lower() in LOW_QUALITY_SOURCES`, so an entry
    containing an uppercase letter or stray whitespace can NEVER match. The
    list would look longer while doing nothing, and nothing else would reveal
    it - the filter would simply keep passing the source it was added to block.
    """
    assert source == source.lower(), "entry must be lowercase to ever match"
    assert source == source.strip(), "entry must not carry whitespace"
    assert source, "entry must not be empty"


@pytest.mark.parametrize("source", sorted(LOW_QUALITY_SOURCES))
def test_every_entry_is_a_bare_host(source):
    """`article.source` is a host like "reuters.com", so an entry written as a
    URL or with a path would never match what it was added to block."""
    assert "/" not in source, "entry should be a host, not a URL"
    assert not source.startswith(("http:", "https:", "www.")), source
    assert "." in source, "entry should look like a hostname"


def test_the_filter_still_blocks_the_originally_listed_sources():
    """The seven the list started with. Widening it must not lose any.

    Not a style rule: these were chosen deliberately, and an accidental
    deletion during an edit would show up as nothing at all - the corpus would
    simply start containing them again.
    """
    original = {
        "joemygod.com",
        "thegatewaypundit.com",
        "zerohedge.com",
        "steynonline.com",
        "app.buzzsumo.com",
        "beforeitsnews.com",
        "naturalnews.com",
    }
    assert original <= LOW_QUALITY_SOURCES


def test_a_legitimate_publisher_is_not_caught_by_a_similar_name():
    """Matching is exact, not substring. "news.ycombinator.com" is blocked and
    must not take every host containing "news" with it."""
    for source in ("bbc.com", "hydrogenfuelnews.com", "medcitynews.com",
                   "cnbc.com", "finance.yahoo.com"):
        kept, dropped = drop_low_quality([make_article("u1", source=source)])
        assert dropped == [], f"{source} should not be filtered"
        assert len(kept) == 1


# --- What the filter withheld must reach the reader --------------------------
#
# drop_low_quality returns the dropped sources and its docstring argues why:
# "a filter that silently removes evidence is its own kind of unreliable
# narrator." For three sessions risk_agent assigned them to `_dropped` and threw
# them away, one line below that warning. These hold the chain together from the
# filter, through state, to the screen.


def _candidate():
    from models.companies import (
        CompanyCandidate, ComparableMetrics, CurrencyAmounts, Fundamentals,
    )

    return CompanyCandidate(
        ticker="WAAREE", name="Waaree Energies", exchange="NSE", currency="INR",
        exposure="direct", exposure_rationale="Makes the modules.",
        themes=["solar"], evidence_article_ids=["a1"], screen_score=0.7,
        fundamentals=Fundamentals(
            comparable=ComparableMetrics(operating_margin=0.14),
            amounts=CurrencyAmounts(currency="INR"),
            source="fmp",
        ),
    )


def test_the_critique_records_which_publishers_were_withheld(monkeypatch):
    """The end of the chain that used to stop at `_dropped`."""
    from agents import risk_agent
    from models.risk import NewsRiskAssessment

    articles = [
        make_article("u1", "Real reporting on a probe", source="reuters.com"),
        make_article("u2", "Commentary", source="zerohedge.com"),
        make_article("u3", "More commentary", source="revolver.news"),
    ]
    monkeypatch.setattr(risk_agent, "search_many", lambda q, **k: (articles, list(q)))
    monkeypatch.setattr(
        risk_agent, "assess_news_risks",
        lambda c, a: (NewsRiskAssessment(risks=[]), {}),
    )

    critique, _discarded, _cited = risk_agent.critique_candidate(_candidate())

    assert sorted(critique.sources_withheld) == ["revolver.news", "zerohedge.com"]
    assert critique.articles_reviewed == 1, "only the kept article was reviewed"


def test_nothing_withheld_records_nothing(monkeypatch):
    """An empty list, not a missing field - "none withheld" is information."""
    from agents import risk_agent
    from models.risk import NewsRiskAssessment

    articles = [make_article("u1", source="reuters.com")]
    monkeypatch.setattr(risk_agent, "search_many", lambda q, **k: (articles, list(q)))
    monkeypatch.setattr(
        risk_agent, "assess_news_risks",
        lambda c, a: (NewsRiskAssessment(risks=[]), {}),
    )

    critique, _, _ = risk_agent.critique_candidate(_candidate())
    assert critique.sources_withheld == []


def test_a_provider_failure_withholds_nothing_rather_than_crashing(monkeypatch):
    from agents import risk_agent
    from clients.news import NewsAPIError

    def boom(*a, **k):
        raise NewsAPIError("provider down")

    monkeypatch.setattr(risk_agent, "search_many", boom)
    result = risk_agent._retrieve_bear_case(_candidate(), True)

    assert result == ([], [], [], 0)


def test_the_cli_prints_what_was_withheld(capsys):
    """Recording it in state and not showing it would move the silence rather
    than end it."""
    import cli
    from models.risk import CandidateCritique, RiskFindings

    update = {
        "risk_findings": RiskFindings(
            critiques=[
                CandidateCritique(
                    ticker="WAAREE", name="Waaree Energies", risks=[],
                    queries_used=["q"], articles_reviewed=1,
                    sources_withheld=["zerohedge.com", "zerohedge.com", "revolver.news"],
                )
            ]
        )
    }
    cli._report(cli.Progress(), "risk_critic", update)
    out = capsys.readouterr().out

    assert "withheld 3 article(s)" in out
    assert "revolver.news" in out and "zerohedge.com" in out
    assert out.count("zerohedge.com") == 1, "publishers listed once, count separate"
