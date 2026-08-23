"""Tests for Agent 4's assembly: grounding, accounting, and the critique cap.

The news client and the model call are both faked, so these run offline and
deterministically. What is under test is that a risk the model invented cannot
survive, that a skipped candidate is never silently missing, and that the two
risk sources are combined without double-counting.
"""

from datetime import datetime, timezone

import pytest

from agents import risk_agent
from agents.risk_agent import critique_companies
from clients.news import NewsAPIError
from models.companies import (
    CompanyCandidate,
    CompanyFindings,
    ComparableMetrics,
    CurrencyAmounts,
    Fundamentals,
)
from models.research import Article
from models.risk import NewsRiskAssessment, Risk


def article(uuid, title="Regulator opens probe"):
    return Article(uuid=uuid, title=title, description="d", snippet="s",
                   url=f"https://reuters.com/{uuid}", source="reuters.com",
                   published_at=datetime(2026, 8, 20, tzinfo=timezone.utc))


def candidate(ticker="AAA", name="Acme Motors", score=0.8, **metrics):
    base = dict(revenue_growth=0.20, operating_margin=0.15,
                gross_margin=0.45, debt_to_equity=0.4)
    return CompanyCandidate(
        ticker=ticker, name=name, exchange="NMS", currency="USD",
        fundamentals=Fundamentals(
            comparable=ComparableMetrics(**{**base, **metrics}),
            amounts=CurrencyAmounts(currency="USD", net_income=5.0,
                                    free_cash_flow=5.0),
            source="fmp",
        ),
        exposure="direct", exposure_rationale="builds the thing",
        themes=["Some Theme"], evidence_article_ids=["u-orig"],
        screen_score=score,
    )


def news_risk(label="A1", severity="material", ticker="AAA"):
    return Risk(ticker=ticker, risk_type="regulatory", severity=severity,
                claim="A regulator opened a probe into the main product line.",
                article_ids=[label])


@pytest.fixture
def critic(monkeypatch):
    """Fake the news client and the model call."""
    state = {"articles": [article("u-1")], "risks": [], "raise_news": False}

    def fake_search(queries, use_cache=True, **kw):
        if state["raise_news"]:
            raise NewsAPIError("provider down")
        return list(state["articles"]), list(queries)

    monkeypatch.setattr(risk_agent, "search_many", fake_search)
    monkeypatch.setattr(
        risk_agent, "assess_news_risks",
        lambda cand, arts: (
            NewsRiskAssessment(risks=list(state["risks"])),
            {f"A{i}": a for i, a in enumerate(arts, start=1)},
        ),
    )
    return state


# --- Grounding: the guarantee this agent rests on ----------------------------


def test_a_risk_citing_an_article_that_was_never_retrieved_is_discarded(critic):
    """The model inventing a source is the failure this agent exists to avoid.
    An [A9] that was never shown must not reach Agent 5."""
    critic["risks"] = [news_risk(label="A9")]

    findings = critique_companies(CompanyFindings(candidates=[candidate()]))

    assert findings.critiques[0].risks == []
    assert findings.risks_discarded == 1


def test_discarded_risks_are_counted_not_silently_dropped(critic):
    """Otherwise the output still looks clean while the model fabricates."""
    critic["risks"] = [news_risk(label="A9"), news_risk(label="A8")]

    findings = critique_companies(CompanyFindings(candidates=[candidate()]))
    assert findings.risks_discarded == 2


def test_a_valid_label_is_rewritten_to_the_real_uuid(critic):
    """Agent 5 needs a uuid it can look up, not a prompt-local label."""
    critic["articles"] = [article("real-uuid-1")]
    critic["risks"] = [news_risk(label="A1")]

    findings = critique_companies(CompanyFindings(candidates=[candidate()]))
    assert findings.critiques[0].risks[0].article_ids == ["real-uuid-1"]


def test_only_the_invented_labels_are_stripped_from_a_partly_valid_risk(critic):
    critic["articles"] = [article("real-1")]
    critic["risks"] = [
        Risk(ticker="AAA", risk_type="regulatory", severity="minor",
             claim="c", article_ids=["A1", "A7"])
    ]

    findings = critique_companies(CompanyFindings(candidates=[candidate()]))
    assert findings.critiques[0].risks[0].article_ids == ["real-1"]
    assert findings.risks_discarded == 0


def test_a_risk_filed_against_the_wrong_ticker_is_reattributed(critic):
    """A risk attached to a company nobody examined would be criticism from
    nowhere. The ticker is overwritten rather than trusted."""
    critic["risks"] = [news_risk(ticker="WRONG")]

    findings = critique_companies(CompanyFindings(candidates=[candidate("AAA")]))
    assert findings.critiques[0].risks[0].ticker == "AAA"


# --- The two risk sources ----------------------------------------------------


def test_fundamental_risks_are_added_to_news_risks(critic):
    critic["risks"] = [news_risk()]
    weak = candidate(debt_to_equity=4.0)

    findings = critique_companies(CompanyFindings(candidates=[weak]))
    risks = findings.critiques[0].risks

    assert [r.is_fundamental for r in risks] == [False, True]


def test_fundamental_risks_survive_even_when_no_article_is_retrieved(critic):
    """The floor. A quiet week produces no bear-case articles, and without the
    computed risks the critic would report nothing and read as reassurance."""
    critic["articles"] = []
    critic["risks"] = []

    findings = critique_companies(
        CompanyFindings(candidates=[candidate(debt_to_equity=4.0)])
    )
    assert len(findings.critiques[0].risks) == 1
    assert findings.critiques[0].risks[0].is_fundamental


def test_a_clean_company_with_no_bad_news_yields_no_risks(critic):
    """An empty list is a real finding. Making it impossible would pressure the
    agent into manufacturing something."""
    critic["risks"] = []

    findings = critique_companies(CompanyFindings(candidates=[candidate()]))
    assert findings.critiques[0].risks == []
    assert findings.found_nothing


# --- Effort is recorded ------------------------------------------------------


def test_the_queries_and_article_count_are_recorded(critic):
    """So "no risks" can be told apart from "nothing was looked at"."""
    critic["articles"] = [article("u-1"), article("u-2")]

    findings = critique_companies(CompanyFindings(candidates=[candidate()]))
    critique = findings.critiques[0]

    assert critique.articles_reviewed == 2
    assert critique.queries_used
    assert critique.was_critiqued


def test_a_news_provider_failure_does_not_end_the_run(critic):
    """One company retrieving nothing beats the whole pipeline failing."""
    critic["raise_news"] = True

    findings = critique_companies(
        CompanyFindings(candidates=[candidate(debt_to_equity=4.0)])
    )
    critique = findings.critiques[0]

    assert critique.articles_reviewed == 0
    assert critique.queries_used == []
    # The fundamentals still produced a risk, so the critique is not empty.
    assert len(critique.risks) == 1


# --- The cap -----------------------------------------------------------------


def test_candidates_beyond_the_cap_are_recorded_as_skipped(critic, monkeypatch):
    """A candidate silently missing would reach Agent 5 looking uncriticised
    rather than unexamined."""
    monkeypatch.setattr(
        risk_agent.get_settings(), "max_critique_candidates", 2, raising=False
    )
    cands = [candidate(ticker=f"T{i}", score=1.0 - i / 10) for i in range(5)]

    findings = critique_companies(CompanyFindings(candidates=cands))

    assert len(findings.critiques) == 5
    critiqued = [c for c in findings.critiques if c.was_critiqued]
    skipped = [c for c in findings.critiques if not c.was_critiqued]

    assert len(critiqued) == 2
    assert len(skipped) == 3
    assert all(c.skipped_reason for c in skipped)
    assert "2 highest-ranked of 5" in findings.notes


def test_the_best_ranked_candidates_are_the_ones_critiqued(critic, monkeypatch):
    monkeypatch.setattr(
        risk_agent.get_settings(), "max_critique_candidates", 1, raising=False
    )
    cands = [candidate(ticker="LOW", score=0.2), candidate(ticker="HIGH", score=0.9)]

    findings = critique_companies(CompanyFindings(candidates=cands))
    critiqued = [c.ticker for c in findings.critiques if c.was_critiqued]

    assert critiqued == ["HIGH"]


# --- Nothing to criticise ----------------------------------------------------


def test_no_candidates_is_handled_with_a_reason_not_an_empty_result(critic):
    findings = critique_companies(CompanyFindings(candidates=[]))

    assert findings.critiques == []
    assert "nothing to criticise" in findings.notes


# --- Verdicts flow through ---------------------------------------------------


def test_a_critical_news_risk_disqualifies_the_candidate(critic):
    critic["risks"] = [news_risk(severity="critical")]

    findings = critique_companies(CompanyFindings(candidates=[candidate("AAA")]))
    assert findings.disqualified == ["AAA"]


# --- Source quality ----------------------------------------------------------


def test_commentary_sources_never_reach_the_model(critic, monkeypatch):
    """REGRESSION: Agent 4 graded two MATERIAL risks against Pfizer from two
    joemygod.com pieces - one reporting that the underlying claim was a lie,
    the other an advocacy group soliciting donations for lawsuits premised on
    it. Both were specific and correctly cited, and together they tipped the
    verdict from survives to weakened. A real citation to a worthless article
    still produces a worthless risk."""
    seen = {}

    def capture(cand, arts):
        seen["articles"] = list(arts)
        return NewsRiskAssessment(risks=[]), {}

    monkeypatch.setattr(risk_agent, "assess_news_risks", capture)
    critic["articles"] = [
        article("good", title="Regulator opens probe"),
        Article(uuid="junk", title="Blog opinion", description="d", snippet="s",
                url="https://joemygod.com/x", source="joemygod.com",
                published_at=datetime(2026, 8, 20, tzinfo=timezone.utc)),
    ]

    critique_companies(CompanyFindings(candidates=[candidate()]))
    assert [a.uuid for a in seen["articles"]] == ["good"]


# --- De-duplication ----------------------------------------------------------


def test_two_risks_resting_on_the_same_article_count_once(critic):
    """The verdict is arithmetic over severity COUNTS, so one story described
    twice can cross the "two material risks" threshold on its own."""
    critic["articles"] = [article("shared")]
    critic["risks"] = [
        Risk(ticker="AAA", risk_type="regulatory", severity="material",
             claim="A probe was opened.", article_ids=["A1"]),
        Risk(ticker="AAA", risk_type="execution", severity="material",
             claim="The same probe, described differently.", article_ids=["A1"]),
    ]

    findings = critique_companies(CompanyFindings(candidates=[candidate()]))
    critique = findings.critiques[0]

    assert len(critique.risks) == 1
    assert critique.verdict == "survives"


def test_the_most_severe_of_a_duplicated_pair_is_the_one_kept(critic):
    """A story reported as material in one risk and minor in another is
    material, so keeping the first would understate it."""
    critic["articles"] = [article("shared")]
    critic["risks"] = [
        Risk(ticker="AAA", risk_type="regulatory", severity="minor",
             claim="Minor framing.", article_ids=["A1"]),
        Risk(ticker="AAA", risk_type="regulatory", severity="critical",
             claim="Critical framing.", article_ids=["A1"]),
    ]

    findings = critique_companies(CompanyFindings(candidates=[candidate()]))
    assert [r.severity for r in findings.critiques[0].risks] == ["critical"]


def test_risks_on_different_articles_are_both_kept(critic):
    """Independent evidence must still count independently, or the verdict
    stops being able to weaken anything."""
    critic["articles"] = [article("one"), article("two")]
    critic["risks"] = [
        Risk(ticker="AAA", risk_type="regulatory", severity="material",
             claim="First problem.", article_ids=["A1"]),
        Risk(ticker="AAA", risk_type="competitive", severity="material",
             claim="Unrelated second problem.", article_ids=["A2"]),
    ]

    findings = critique_companies(CompanyFindings(candidates=[candidate()]))
    assert len(findings.critiques[0].risks) == 2
    assert findings.critiques[0].verdict == "weakened"


def test_fundamental_risks_are_never_collapsed_into_each_other(critic):
    """Each names a different metric, so they are independent by construction
    and share no article ids to collide on."""
    critic["risks"] = []
    weak = candidate(revenue_growth=-0.1, debt_to_equity=4.0)

    findings = critique_companies(CompanyFindings(candidates=[weak]))
    assert len(findings.critiques[0].risks) == 2
