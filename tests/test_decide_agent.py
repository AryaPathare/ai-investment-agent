"""Tests for Agent 5's assembly: grounding, provenance, and the fallback.

The model call is faked, so these run offline and deterministically. What is
under test is that an exit condition the model invented cannot survive, that
scores and verdicts are carried through rather than restated, and that a company
is never lost because the prose came back unusable.
"""

from datetime import datetime, timezone

import pytest

from agents import decide_agent
from agents.decide_agent import decide
from models.companies import (
    CompanyCandidate,
    CompanyFindings,
    ComparableMetrics,
    CurrencyAmounts,
    Fundamentals,
)
from models.decision import CompanyBrief, ExitCondition
from models.profile import InvestorProfile
from models.research import Article, ResearchFindings
from models.risk import CandidateCritique, Risk, RiskFindings


def article(uuid):
    return Article(uuid=uuid, title="Regulator opens probe", description="d",
                   snippet="s", url=f"https://reuters.com/{uuid}",
                   source="reuters.com",
                   published_at=datetime(2026, 8, 20, tzinfo=timezone.utc))


def profile(**overrides):
    base = dict(age=40, investment_experience="intermediate",
                risk_tolerance="moderate", investment_amount=5000.0,
                investment_window="within 3 months", holding_period="3-5 years",
                sectors_of_interest=["technology"], restrictions=[], status="valid")
    return InvestorProfile(**{**base, **overrides})


def candidate(ticker="AAA", score=0.7, **metrics):
    base = dict(revenue_growth=0.2, operating_margin=0.1,
                gross_margin=0.5, debt_to_equity=0.4)
    return CompanyCandidate(
        ticker=ticker, name=f"{ticker} Motors", exchange="NMS", currency="USD",
        fundamentals=Fundamentals(
            comparable=ComparableMetrics(**{**base, **metrics}),
            amounts=CurrencyAmounts(currency="USD"), source="fmp"),
        exposure="direct", exposure_rationale="builds the thing",
        themes=["Some Theme"], evidence_article_ids=["u-orig"],
        screen_score=score,
    )


def critique(ticker="AAA", risks=None, skipped=None):
    return CandidateCritique(
        ticker=ticker, name=f"{ticker} Motors", risks=risks or [],
        articles_reviewed=0 if skipped else 3, skipped_reason=skipped,
    )


def risk(ticker="AAA", severity="material", uuids=("u-1",), metric=None):
    return Risk(ticker=ticker, risk_type="regulatory", severity=severity,
                claim="A regulator opened a probe.",
                article_ids=list(uuids) if metric is None else [],
                metric=metric, metric_value=1.0 if metric else None)


@pytest.fixture
def writer(monkeypatch):
    """Fake the model call, returning whatever brief the test asks for."""
    state = {"brief": CompanyBrief(
        thesis="It makes the thing the theme needs.",
        exit_conditions=[ExitCondition(condition="The probe results in a fine.",
                                       article_ids=["A1"])],
    )}

    def fake(cand, crit, prof, arts):
        state.setdefault("given", []).append(list(arts))
        return state["brief"], {f"A{i}": a for i, a in enumerate(arts, start=1)}

    monkeypatch.setattr(decide_agent, "write_brief", fake)
    return state


def run(cands, crits, articles=(), prof=None, research=None):
    return decide(
        CompanyFindings(candidates=cands, companies_examined=len(cands)),
        RiskFindings(critiques=crits, articles=list(articles)),
        prof or profile(),
        research,
    )


# --- Grounding ---------------------------------------------------------------


def test_a_condition_citing_an_article_never_retrieved_is_discarded(writer):
    """"Monitor the competitive landscape" is what a model reaches for when it
    has nothing, and it survives review because it sounds like prudence."""
    writer["brief"] = CompanyBrief(
        thesis="t",
        exit_conditions=[
            ExitCondition(condition="Something from [A9].", article_ids=["A9"]),
            ExitCondition(condition="The probe results in a fine.",
                          article_ids=["A1"]),
        ],
    )
    got = run([candidate()], [critique(risks=[risk()])], [article("u-1")])

    assert len(got.recommendations[0].exit_conditions) == 1
    assert got.conditions_discarded == 1


def test_a_valid_label_is_rewritten_to_the_real_uuid(writer):
    got = run([candidate()], [critique(risks=[risk(uuids=("real-1",))])],
              [article("real-1")])
    assert got.recommendations[0].exit_conditions[0].article_ids == ["real-1"]


def test_an_invented_metric_is_stripped(writer):
    """A condition on a number nobody measures cannot be monitored any more
    than one citing no source at all."""
    writer["brief"] = CompanyBrief(
        thesis="t",
        exit_conditions=[ExitCondition(condition="If the moat narrows.",
                                       metric="moat_width")],
    )
    got = run([candidate()], [critique(risks=[risk()])], [article("u-1")])

    # Nothing survived, so the deterministic fallback filled the gap.
    assert got.conditions_discarded == 1
    assert got.recommendations[0].exit_conditions[0].metric or \
           got.recommendations[0].exit_conditions[0].article_ids


def test_a_known_metric_survives(writer):
    writer["brief"] = CompanyBrief(
        thesis="t",
        exit_conditions=[ExitCondition(condition="debt_to_equity rises above 3.",
                                       metric="debt_to_equity")],
    )
    got = run([candidate()], [critique(risks=[risk()])], [article("u-1")])
    assert got.recommendations[0].exit_conditions[0].metric == "debt_to_equity"
    assert got.conditions_discarded == 0


# --- The fallback ------------------------------------------------------------


def test_a_company_is_not_lost_because_the_prose_came_back_unusable(writer):
    """The schema refuses a recommendation with no way out of it. Dropping an
    otherwise sound company would let a writing failure change the answer."""
    writer["brief"] = CompanyBrief(thesis="t", exit_conditions=[])

    got = run([candidate()], [critique(risks=[risk()])], [article("u-1")])

    assert len(got.recommendations) == 1
    assert got.recommendations[0].exit_conditions


def test_the_fallback_is_grounded_like_everything_else(writer):
    writer["brief"] = CompanyBrief(thesis="t", exit_conditions=[])
    got = run([candidate()], [critique(risks=[risk()])], [article("u-1")])

    condition = got.recommendations[0].exit_conditions[0]
    assert condition.article_ids or condition.metric


def test_the_fallback_works_for_a_company_with_no_risks_at_all(writer):
    writer["brief"] = CompanyBrief(thesis="t", exit_conditions=[])
    got = run([candidate()], [critique(risks=[])])

    assert got.recommendations[0].exit_conditions[0].metric == "revenue_growth"


# --- Provenance is carried, not restated -------------------------------------


def test_score_and_verdict_come_from_the_earlier_agents(writer):
    """So Agent 5 cannot quietly disagree with the stages that produced them."""
    got = run(
        [candidate(score=0.83)],
        [critique(risks=[risk(severity="material"), risk(severity="material")])],
        [article("u-1")],
    )
    rec = got.recommendations[0]

    assert rec.screen_score == pytest.approx(0.83)
    assert rec.verdict == "weakened"
    assert len(rec.known_risks) == 2


# --- Nothing -----------------------------------------------------------------


def test_no_model_call_is_made_when_nothing_is_selected(writer, monkeypatch):
    """Selection happens first and in Python, so the model cannot talk a
    rejected candidate back in - and a pointless call is not paid for."""
    def boom(*a, **k):
        pytest.fail("the model must not be called when nothing was selected")

    monkeypatch.setattr(decide_agent, "write_brief", boom)
    got = run([candidate()], [critique(risks=[risk(severity="critical")])])

    assert got.recommended_nothing
    assert "critical risk" in got.no_recommendation_reason


def test_excluded_candidates_are_reported_alongside_recommendations(writer):
    got = run(
        [candidate("GOOD"), candidate("SKIPPED")],
        [critique("GOOD", risks=[risk("GOOD")]),
         critique("SKIPPED", skipped="outside the cap")],
        [article("u-1")],
    )

    assert [r.ticker for r in got.recommendations] == ["GOOD"]
    assert got.exclusion_summary == {"not_critiqued": 1}
    assert "1 of 2 candidates considered" in got.notes


# --- A condition that has already happened -----------------------------------


def test_a_condition_on_an_already_crossed_metric_is_discarded(writer):
    """REGRESSION: PowerBank was recommended with "free_cash_flow_is_negative"
    as the thing to watch for, while its free cash flow was already
    -28,367,000. Perfectly checkable and immediately true, so it carried no
    information — the mirror image of the unfalsifiable conditions the prompt
    already bans, and invisible to every check that looks for vagueness."""
    writer["brief"] = CompanyBrief(
        thesis="t",
        exit_conditions=[
            ExitCondition(condition="free_cash_flow_is_negative",
                          metric="free_cash_flow_is_negative"),
            ExitCondition(condition="revenue_growth turns negative",
                          metric="revenue_growth"),
        ],
    )
    already = risk(metric="free_cash_flow_is_negative")

    got = run([candidate()], [critique(risks=[already])])
    kept = got.recommendations[0].exit_conditions

    assert [c.metric for c in kept] == ["revenue_growth"]
    assert got.conditions_discarded == 1


def test_a_metric_not_yet_crossed_is_still_allowed(writer):
    """Only the ones that have ALREADY fired are spent."""
    writer["brief"] = CompanyBrief(
        thesis="t",
        exit_conditions=[ExitCondition(condition="debt_to_equity rises above 3.0",
                                       metric="debt_to_equity")],
    )
    already = risk(metric="revenue_growth")

    got = run([candidate()], [critique(risks=[already])])
    assert got.recommendations[0].exit_conditions[0].metric == "debt_to_equity"


def test_an_already_crossed_metric_survives_if_the_condition_also_cites_an_article(writer):
    """The article is still checkable, so only the spent metric is stripped."""
    writer["brief"] = CompanyBrief(
        thesis="t",
        exit_conditions=[ExitCondition(
            condition="The cash burn reported in the article continues.",
            article_ids=["A1"], metric="free_cash_flow_is_negative")],
    )
    already = risk(metric="free_cash_flow_is_negative")

    got = run([candidate()], [critique(risks=[already, risk()])], [article("u-1")])
    kept = got.recommendations[0].exit_conditions[0]

    assert kept.article_ids == ["u-1"]
    assert kept.metric is None


def test_the_fallback_never_reintroduces_an_already_met_condition(writer):
    """It says "deteriorates FURTHER from" for exactly this reason."""
    writer["brief"] = CompanyBrief(thesis="t", exit_conditions=[])
    already = risk(metric="debt_to_equity")

    got = run([candidate()], [critique(risks=[already])])
    condition = got.recommendations[0].exit_conditions[0]

    assert "further" in condition.condition.lower()


# --- What Agent 5 is allowed to cite -----------------------------------------
#
# The 1-of-8 citation rate was read for weeks as the model taking the cheap
# option. It was not. ``RiskFindings.articles`` holds only the articles a risk
# CITED, and ``risk_rules`` produces metric-derived risks that cite nothing, so
# most candidates reached Agent 5 with an empty list and satisfied the
# citation rule vacuously. These tests pin the other source shut.


def test_a_candidate_whose_risks_are_all_metrics_still_gets_its_theme_article(
    writer,
):
    """The 2.6 defect exactly: every risk is a metric threshold, so nothing
    reaches ``RiskFindings.articles`` and the old code handed the model an
    empty list - then the prompt's citation rule had nothing to bind to."""
    crit = critique(risks=[risk(metric="operating_margin")])
    research = ResearchFindings(articles=[article("u-orig")], articles_retrieved=1)

    run([candidate()], [crit], articles=(), research=research)

    given = writer["given"][0]
    assert [a.uuid for a in given] == ["u-orig"], (
        "the article that put this company in the theme never reached Agent 5"
    )


def test_the_bear_case_is_offered_before_the_theme_article(writer):
    """An exit condition is a bear-case question, so the article a critic cited
    AGAINST the company is listed first. A theme article is bullish: available
    to cite, but not the first thing the model reads."""
    crit = critique(risks=[risk(uuids=("u-1",))])
    research = ResearchFindings(articles=[article("u-orig")], articles_retrieved=1)

    run([candidate()], [crit], articles=[article("u-1")], research=research)

    assert [a.uuid for a in writer["given"][0]] == ["u-1", "u-orig"]


def test_an_article_serving_as_both_risk_and_theme_evidence_is_offered_once(
    writer,
):
    """Agent 4 retrieves adversarially but can land on the same article Agent 2
    already cited. Two [A]-labels for one article invites two conditions that
    are the same condition."""
    crit = critique(risks=[risk(uuids=("u-orig",))])
    research = ResearchFindings(articles=[article("u-orig")], articles_retrieved=1)

    run([candidate()], [crit], articles=[article("u-orig")], research=research)

    assert [a.uuid for a in writer["given"][0]] == ["u-orig"]


def test_a_caller_with_no_research_still_gets_the_risk_articles(writer):
    """``research`` is optional, and omitting it must degrade to the old
    behaviour rather than raise - the eval runners and any caller that has only
    the critic's output still work."""
    crit = critique(risks=[risk(uuids=("u-1",))])

    run([candidate()], [crit], articles=[article("u-1")])

    assert [a.uuid for a in writer["given"][0]] == ["u-1"]
