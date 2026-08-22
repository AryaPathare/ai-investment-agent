"""Tests for Agent 3's assembly: drop accounting, ranking, and the caps.

Both providers and both model calls are faked, so these run offline and
deterministically. What is under test is the bookkeeping - that every mentioned
company ends up either a candidate or a recorded rejection, and that nothing
disappears silently.
"""

from datetime import datetime, timezone

import pytest

from agents import company_agent
from agents.company_agent import analyse_companies
from clients.companies import CompanyDataError, ResolvedCompany
from models.companies import (
    ComparableMetrics,
    CompanyMention,
    CurrencyAmounts,
    ExposureAssessment,
    ExposureVerdict,
    Fundamentals,
    MentionExtraction,
)
from models.research import Article, Evidence, ResearchFindings, Theme


def article(uuid, title="A headline", source="reuters.com", day=18):
    return Article(uuid=uuid, title=title, description="d", snippet="s",
                   url=f"https://{source}/{uuid}", source=source,
                   published_at=datetime(2026, 8, day, tzinfo=timezone.utc))


def theme(name, article_uuids):
    return Theme(
        name=name, why_it_matters="why", industries=["tech"],
        timeframe="already_underway", confidence="high",
        evidence=[Evidence(article_id=u, stance="supports", relevance="r")
                  for u in article_uuids],
    )


def resolved(ticker, name=None, is_us=True):
    return ResolvedCompany(ticker=ticker, name=name or ticker, exchange="NMS",
                           currency="USD", is_us=is_us, industry="Semiconductors",
                           sector="Technology")


def healthy(**overrides):
    base = dict(revenue_growth=0.30, operating_margin=0.20,
                gross_margin=0.55, debt_to_equity=0.3)
    return Fundamentals(
        comparable=ComparableMetrics(**{**base, **overrides}),
        amounts=CurrencyAmounts(currency="USD", net_income=1.0, free_cash_flow=1.0),
        source="fmp",
    )


@pytest.fixture
def research():
    """Two themes over two articles."""
    return ResearchFindings(
        themes=[theme("AI chips", ["u1"]), theme("Banking", ["u2"])],
        articles=[article("u1"), article("u2", source="ft.com")],
        articles_retrieved=2,
    )


@pytest.fixture
def pipeline(monkeypatch):
    """Fake every external call Agent 3 makes."""
    state = {
        "mentions": [],
        "resolve": {},        # name -> ResolvedCompany | None
        "fundamentals": {},   # ticker -> Fundamentals | Exception
        "verdicts": [],
        "search_hits": {},    # name -> raw hits, for drop-reason detail
    }

    def fake_extract(findings):
        _, mapping = company_agent._format_articles(findings.articles)
        return MentionExtraction(mentions=state["mentions"]), mapping

    monkeypatch.setattr(company_agent, "extract_mentions", fake_extract)
    monkeypatch.setattr(company_agent, "resolve_company",
                        lambda name, use_cache=True: state["resolve"].get(name))

    def fake_fetch(company, use_cache=True):
        value = state["fundamentals"].get(company.ticker, healthy())
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(company_agent, "fetch_fundamentals", fake_fetch)
    monkeypatch.setattr(company_agent, "assess_exposure",
                        lambda rows: ExposureAssessment(verdicts=state["verdicts"]))
    monkeypatch.setattr(company_agent, "_search_raw",
                        lambda name, use_cache: state["search_hits"].get(name, []))
    return state


def mention(name, article_id="A1", context="did a thing"):
    return CompanyMention(name=name, article_id=article_id, context=context)


def grade_all(level="direct"):
    """Grade every row the agent produces at the given level."""
    return [ExposureVerdict(company_id=f"C{i}", exposure=level, rationale="r")
            for i in range(1, 20)]


# --- Early exits -------------------------------------------------------------


def test_no_themes_means_no_companies_examined(pipeline):
    findings = analyse_companies(ResearchFindings())
    assert findings.found_nothing
    assert "No research themes" in findings.notes


def test_articles_naming_no_companies(pipeline, research):
    findings = analyse_companies(research)
    assert findings.found_nothing
    assert "named no companies" in findings.notes


# --- Drop accounting ---------------------------------------------------------


def test_an_unresolvable_name_with_no_search_hits(pipeline, research):
    pipeline["mentions"] = [mention("Velaura AI")]
    pipeline["resolve"] = {"Velaura AI": None}

    findings = analyse_companies(research)
    assert findings.drop_summary == {"no_ticker_found": 1}
    assert "no securities matched" in findings.dropped[0].detail


def test_an_unresolvable_name_that_had_candidates(pipeline, research):
    """Kept apart from no_ticker_found because they mean different things:
    one says extraction is producing non-companies, the other says the fund and
    subsidiary filters are working."""
    pipeline["mentions"] = [mention("SpaceX")]
    pipeline["resolve"] = {"SpaceX": None}
    pipeline["search_hits"] = {"SpaceX": [{"symbol": "SPCF"}, {"symbol": "SPCG"}]}

    findings = analyse_companies(research)
    assert findings.drop_summary == {"not_an_operating_company": 1}
    assert "2 matches" in findings.dropped[0].detail


def test_two_names_for_one_company_collapse(pipeline, research):
    pipeline["mentions"] = [mention("AMD"), mention("Advanced Micro Devices")]
    pipeline["resolve"] = {"AMD": resolved("AMD"),
                           "Advanced Micro Devices": resolved("AMD")}
    pipeline["verdicts"] = grade_all()

    findings = analyse_companies(research)
    assert len(findings.candidates) == 1
    assert findings.drop_summary == {"duplicate": 1}


def test_a_provider_failure_drops_only_that_company(pipeline, research):
    pipeline["mentions"] = [mention("Good Co"), mention("Broken Co")]
    pipeline["resolve"] = {"Good Co": resolved("GOOD"), "Broken Co": resolved("BROK")}
    pipeline["fundamentals"] = {"BROK": CompanyDataError("provider down")}
    pipeline["verdicts"] = grade_all()

    findings = analyse_companies(research)
    assert [c.ticker for c in findings.candidates] == ["GOOD"]
    assert findings.drop_summary == {"no_fundamentals": 1}


def test_incidental_companies_are_dropped(pipeline, research):
    pipeline["mentions"] = [mention("Tesla")]
    pipeline["resolve"] = {"Tesla": resolved("TSLA")}
    pipeline["verdicts"] = grade_all("incidental")

    findings = analyse_companies(research)
    assert findings.found_nothing
    assert findings.drop_summary == {"incidental_mention": 1}


def test_screen_failures_are_recorded(pipeline, research):
    pipeline["mentions"] = [mention("Failing Co")]
    pipeline["resolve"] = {"Failing Co": resolved("FAIL")}
    pipeline["fundamentals"] = {
        "FAIL": healthy(revenue_growth=-0.2, operating_margin=-0.1)
    }
    pipeline["verdicts"] = grade_all()

    findings = analyse_companies(research)
    assert findings.drop_summary == {"failed_screen": 1}


def test_every_mention_is_accounted_for(pipeline, research):
    """Nothing may vanish: each mentioned company is a candidate or a drop."""
    pipeline["mentions"] = [mention(n) for n in ("A Co", "B Co", "C Co", "D Co")]
    pipeline["resolve"] = {
        "A Co": resolved("AAA"), "B Co": resolved("BBB"),
        "C Co": None, "D Co": resolved("DDD"),
    }
    pipeline["fundamentals"] = {"DDD": CompanyDataError("down")}
    pipeline["verdicts"] = grade_all()

    findings = analyse_companies(research)
    assert len(findings.candidates) + len(findings.dropped) == 4


# --- Exposure ----------------------------------------------------------------


def test_an_ungraded_pair_is_treated_as_incidental(pipeline, research):
    """The conservative default: an ungraded company must not be promoted."""
    pipeline["mentions"] = [mention("Ghost Co")]
    pipeline["resolve"] = {"Ghost Co": resolved("GHST")}
    pipeline["verdicts"] = []

    findings = analyse_companies(research)
    assert findings.drop_summary == {"incidental_mention": 1}
    assert "not graded" in findings.notes


def test_the_best_exposure_across_themes_wins(pipeline, research):
    """A company incidental to one theme and direct to another is worth
    considering; the direct link is the reason it is here."""
    pipeline["mentions"] = [mention("Multi Co", "A1"), mention("Multi Co", "A2")]
    pipeline["resolve"] = {"Multi Co": resolved("MULT")}
    pipeline["verdicts"] = [
        ExposureVerdict(company_id="C1", exposure="incidental", rationale="no"),
        ExposureVerdict(company_id="C2", exposure="direct", rationale="yes"),
    ]

    findings = analyse_companies(research)
    assert len(findings.candidates) == 1
    assert findings.candidates[0].exposure == "direct"


def test_verdicts_for_unknown_labels_are_ignored(pipeline, research):
    pipeline["mentions"] = [mention("Real Co")]
    pipeline["resolve"] = {"Real Co": resolved("REAL")}
    pipeline["verdicts"] = [
        ExposureVerdict(company_id="C99", exposure="direct", rationale="invented"),
    ]

    findings = analyse_companies(research)
    assert findings.found_nothing


# --- Ranking and caps --------------------------------------------------------


def test_candidates_are_ranked_by_score(pipeline, research):
    pipeline["mentions"] = [mention("Weak Co"), mention("Strong Co")]
    pipeline["resolve"] = {"Weak Co": resolved("WEAK"), "Strong Co": resolved("STRG")}
    pipeline["fundamentals"] = {
        "WEAK": healthy(revenue_growth=0.02, operating_margin=0.02,
                        gross_margin=0.25, debt_to_equity=2.5),
        "STRG": healthy(revenue_growth=0.40, operating_margin=0.30,
                        gross_margin=0.65, debt_to_equity=0.1),
    }
    pipeline["verdicts"] = grade_all()

    findings = analyse_companies(research)
    scores = [c.screen_score for c in findings.candidates]
    assert scores == sorted(scores, reverse=True)
    assert findings.candidates[0].ticker == "STRG"


def test_a_zero_scoring_company_is_dropped_rather_than_recommended(pipeline, research):
    """REGRESSION: a live run returned two pre-revenue biotechs scoring 0.000 to
    a 66-year-old with low risk tolerance. Ranking them last still recommends
    them; a zero is the ranking's own verdict that nothing supports the pick."""
    pipeline["mentions"] = [mention("Zero Co"), mention("Good Co")]
    pipeline["resolve"] = {"Zero Co": resolved("ZERO"), "Good Co": resolved("GOOD")}
    pipeline["fundamentals"] = {
        # Passes screening, but every available component scores zero.
        "ZERO": healthy(revenue_growth=0.0, operating_margin=None,
                        gross_margin=0.20, debt_to_equity=3.0),
        "GOOD": healthy(),
    }
    pipeline["verdicts"] = grade_all()

    findings = analyse_companies(research)

    assert [c.ticker for c in findings.candidates] == ["GOOD"]
    assert [d.reason for d in findings.dropped] == ["failed_screen"]
    assert "scored 0.000" in findings.dropped[0].detail


def test_the_candidate_cap_is_applied_and_recorded(pipeline, research):
    """Silent truncation reads as "this is everything" when it is not."""
    names = [f"Co {i}" for i in range(12)]
    pipeline["mentions"] = [mention(n) for n in names]
    pipeline["resolve"] = {n: resolved(f"T{i}") for i, n in enumerate(names)}
    pipeline["verdicts"] = grade_all()

    findings = analyse_companies(research)
    assert len(findings.candidates) == 8
    assert "Kept the 8 highest-ranked of 12" in findings.notes


def test_the_examination_cap_limits_provider_calls(pipeline, research, monkeypatch):
    """A cost control: each US company costs four of FMP's 250 daily requests."""
    looked_up = []
    names = [f"Co {i}" for i in range(40)]
    pipeline["mentions"] = [mention(n) for n in names]

    def track(name, use_cache=True):
        looked_up.append(name)
        return resolved(f"T{len(looked_up)}")

    monkeypatch.setattr(company_agent, "resolve_company", track)
    pipeline["verdicts"] = grade_all()

    findings = analyse_companies(research)
    assert len(looked_up) == 25
    assert "40 companies were named" in findings.notes


def test_the_most_mentioned_companies_are_examined_first(pipeline, research, monkeypatch):
    looked_up = []
    pipeline["mentions"] = (
        [mention("Rare Co")] + [mention("Common Co", "A1"), mention("Common Co", "A2")]
    )

    def track(name, use_cache=True):
        looked_up.append(name)
        return None

    monkeypatch.setattr(company_agent, "resolve_company", track)
    analyse_companies(research)
    assert looked_up[0] == "Common Co"


# --- Traceability ------------------------------------------------------------


def test_candidates_carry_real_article_uuids(pipeline, research):
    """Not the "A1" labels shown to the model - the ids Agent 4 can match."""
    pipeline["mentions"] = [mention("Real Co", "A1")]
    pipeline["resolve"] = {"Real Co": resolved("REAL")}
    pipeline["verdicts"] = grade_all()

    findings = analyse_companies(research)
    assert findings.candidates[0].evidence_article_ids == ["u1"]


def test_mentions_citing_an_unknown_article_are_ignored(pipeline, research):
    pipeline["mentions"] = [mention("Real Co", "A1"), mention("Ghost Co", "A99")]
    pipeline["resolve"] = {"Real Co": resolved("REAL")}
    pipeline["verdicts"] = grade_all()

    findings = analyse_companies(research)
    assert findings.mentions_extracted == 1
    assert "unknown article" in findings.notes


def test_candidates_record_the_themes_they_relate_to(pipeline, research):
    pipeline["mentions"] = [mention("Real Co", "A1")]
    pipeline["resolve"] = {"Real Co": resolved("REAL")}
    pipeline["verdicts"] = grade_all()

    findings = analyse_companies(research)
    assert findings.candidates[0].themes == ["AI chips"]
