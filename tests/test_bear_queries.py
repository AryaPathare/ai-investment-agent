"""Tests for bear-case query construction.

Pure string handling, no network. The failure these guard against is quiet:
an over-specified query returns zero articles, the critic reports no risks, and
that reads as "this company is sound" when it means "nothing was searched
properly".
"""

import pytest

from agents.bear_queries import bear_queries, strip_legal_suffix
from models.companies import (
    CompanyCandidate,
    ComparableMetrics,
    CurrencyAmounts,
    Fundamentals,
)


def candidate(name="Acme Motors", themes=()):
    return CompanyCandidate(
        ticker="TST",
        name=name,
        exchange="NMS",
        currency="USD",
        fundamentals=Fundamentals(
            comparable=ComparableMetrics(revenue_growth=0.2, operating_margin=0.1),
            amounts=CurrencyAmounts(currency="USD"),
            source="fmp",
        ),
        exposure="direct",
        exposure_rationale="r",
        themes=list(themes),
        evidence_article_ids=["uuid-1"],
        screen_score=0.5,
    )


# --- Suffix stripping --------------------------------------------------------


@pytest.mark.parametrize(
    "registered,expected",
    [
        ("Taiwan Semiconductor Manufacturing Company Limited", "Taiwan Semiconductor Manufacturing"),
        ("ASML Holding N.V.", "ASML"),
        ("Fujiyama Power Systems Limited", "Fujiyama Power Systems"),
        ("PowerBank Corporation", "PowerBank"),
        ("SK hynix Inc.", "SK hynix"),
        ("Barclays PLC", "Barclays"),
        ("Deutsche Bank AG", "Deutsche Bank"),
        ("Pfizer", "Pfizer"),
    ],
)
def test_registry_suffixes_are_stripped(registered, expected):
    """News copy says "Taiwan Semiconductor", never "…Company Limited". As a
    quoted phrase the registered form matches almost nothing."""
    assert strip_legal_suffix(registered) == expected


def test_stacked_suffixes_are_all_removed():
    """Registry names stack them, so one pass is not enough."""
    assert strip_legal_suffix("Acme Group Holdings Limited") == "Acme"


def test_a_name_is_never_stripped_to_nothing():
    """A company actually called "Holdings" would otherwise reduce to an empty
    phrase, and a query of "" matches everything."""
    assert strip_legal_suffix("Holdings") == "Holdings"
    assert strip_legal_suffix("Limited") == "Limited"


def test_a_suffix_inside_a_name_is_not_touched():
    """Only a trailing suffix is a suffix."""
    assert strip_legal_suffix("Group 1 Automotive") == "Group 1 Automotive"


# --- Query construction ------------------------------------------------------


def test_the_company_name_is_searched_as_a_quoted_phrase():
    """Unquoted, "Advanced Micro Devices" matches three unrelated words in one
    paragraph."""
    for q in bear_queries(candidate(name="Advanced Micro Devices"), limit=4):
        assert '"Advanced Micro Devices"' in q


def test_queries_never_use_the_ticker():
    """A ticker is a terrible search term: "C", "PBK" and "TSM" appear in prose
    constantly with no relation to the company."""
    for q in bear_queries(candidate(name="Citigroup"), limit=4):
        assert "TST" not in q


def test_the_configured_limit_is_respected():
    assert len(bear_queries(candidate(), limit=1)) == 1
    assert len(bear_queries(candidate(), limit=3)) == 3


def test_queries_are_deterministic():
    """The same candidate must search the same way every run, or "found nothing
    twice" means nothing."""
    assert bear_queries(candidate(themes=["Solar Demand"]), limit=3) == \
           bear_queries(candidate(themes=["Solar Demand"]), limit=3)


def test_each_query_asks_a_different_angle():
    """Three phrasings of "problem" return the same three articles and waste
    two of the day's hundred requests."""
    qs = bear_queries(candidate(), limit=4)
    assert len(set(qs)) == len(qs)


def test_price_commentary_is_deliberately_not_searched():
    """"Shares fall" retrieves what the market already thinks, and a risk that
    is already priced in is not a finding."""
    joined = " ".join(bear_queries(candidate(), limit=4)).lower()
    for banned in ("stock falls", "shares drop", "downgrade", "price target"):
        assert banned not in joined


# --- The theme-facing query --------------------------------------------------


def test_a_theme_query_is_included_and_survives_the_default_limit():
    """Without it only the company can be attacked, never the theme it was
    picked for — and thesis_invalidation is exactly what Agent 2 cannot see."""
    qs = bear_queries(candidate(themes=["Solar Irrigation Adoption"]), limit=2)
    assert any("Irrigation" in q for q in qs)


def test_a_theme_contributes_exactly_one_keyword():
    """REGRESSION: the whole theme name ANDs into nothing. Verified live:
    '"Pfizer" Vaccine Demand Shifts' returned ZERO articles; '"Pfizer" vaccine'
    returned plenty. Theme names are written for a human to read, so most of
    their words are there for the prose rather than for a search."""
    qs = bear_queries(candidate(themes=["FDA Approval: Shifts & Delays!"]), limit=2)
    themed = [q for q in qs if "Approval" in q or "Delays" in q][0]
    angle = themed.split('" ', 1)[1]
    assert len(angle.split()) == 1, angle


def test_filler_words_never_become_the_theme_keyword():
    """"Demand", "growth" and "shifts" are connective tissue an LLM writes to
    make a phrase read well; ANDing on them retrieves noise."""
    from agents.bear_queries import _theme_keyword
    assert _theme_keyword("Vaccine Demand Shifts") == "Vaccine"
    assert _theme_keyword("Storage Market Growth") == "Storage"


def test_a_candidate_with_no_themes_still_produces_queries():
    """Themes are optional on the model, so this must not raise."""
    qs = bear_queries(candidate(themes=[]), limit=2)
    assert len(qs) == 2
    assert all('"Acme Motors"' in q for q in qs)


def test_a_theme_of_only_short_words_is_skipped_rather_than_searched_empty():
    """Nothing usable survives, so no theme query is built at all."""
    qs = bear_queries(candidate(themes=["AI"]), limit=2)
    angles = [q.split('" ', 1)[1] for q in qs]
    assert all(len(a.split()) == 1 for a in angles)


def test_co_is_treated_as_a_suffix_like_company():
    """Caught by a badly chosen test fixture: "Acme Co" is "Acme". Pinned here
    so the behaviour is deliberate rather than incidental."""
    assert strip_legal_suffix("Acme Co") == "Acme"
    assert strip_legal_suffix("Coca-Cola Co") == "Coca-Cola"


# --- Provider query syntax ---------------------------------------------------


def test_no_query_uses_the_word_or():
    """REGRESSION: the word OR is not query syntax for this provider. Verified
    live: '"Pfizer" lawsuit OR investigation' returned ZERO articles, so every
    bear-case search came back dry and the model was never even called."""
    for q in bear_queries(candidate(themes=["Solar Demand"]), limit=6):
        assert " OR " not in q
        assert not q.endswith(" OR")


def test_no_query_uses_a_pipe():
    """REGRESSION: the pipe IS syntax, but it ORs across the WHOLE query, so the
    company name stops being required. '"Pfizer" lawsuit | probe' returned an
    article about an Israeli army probe and one about Air India. An off-topic
    article is worse than none: the model is then asked what risk an Air India
    story poses to Pfizer, which is an invitation to invent one."""
    for q in bear_queries(candidate(themes=["Solar Demand"]), limit=6):
        assert "|" not in q


def test_the_company_phrase_is_mandatory_in_every_query():
    """Plain AND is what keeps the company required."""
    for q in bear_queries(candidate(name="Pfizer", themes=["Vaccine Demand"]), limit=6):
        assert q.startswith('"Pfizer" ')


def test_each_angle_is_a_single_term():
    """A third ANDed term reliably drove the result count to zero."""
    for q in bear_queries(candidate(themes=[]), limit=6):
        angle = q.split('" ', 1)[1]
        assert len(angle.split()) == 1, angle
