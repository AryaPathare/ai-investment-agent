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
