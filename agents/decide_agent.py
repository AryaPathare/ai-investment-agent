"""Agent 5 — writes the final brief for companies Python has already chosen.

THE SHAPE

    Python   selects and orders the candidates      (agents/selection.py)
    for each selected company:
        LLM      writes the thesis and exit conditions
        Python   discards any condition citing nothing checkable
        Python   supplies a fallback condition if none survived
    Python   assembles the Decision, carrying scores and verdicts through

One model call per recommended company - at most three. The model never sees the
other candidates, never orders anything, and never learns what was excluded,
because none of that is its job and everything it cannot see is something it
cannot get wrong.

WHY THE MODEL IS USED AT ALL HERE

Everywhere else in this project the argument has been for keeping models out.
This is the one stage where the output is meant to be READ, and turning a score,
a verdict, an exposure grade and four risk claims into two paragraphs a person
can act on is exactly what a language model is for. The facts are all fixed
before it is called; it is arranging them, not deciding them.

THE FAILURE TO GUARD AGAINST

Not a wrong recommendation - the recommendation is already made. It is a brief
that READS well and says nothing checkable. "Monitor the competitive landscape"
is the sentence a model reaches for when it has nothing, and it survives every
review because it sounds like prudence. So an exit condition must cite a
retrieved article or a named metric, and one that cites neither is discarded and
counted.
"""

from __future__ import annotations

from typing import Sequence

from agents.selection import Selection, select
from agents.structured import invoke_structured
from config import get_llm
from models.companies import CompanyCandidate, CompanyFindings
from models.decision import (
    CompanyBrief,
    Decision,
    ExitCondition,
    Recommendation,
)
from models.profile import InvestorProfile
from models.research import Article
from models.risk import CandidateCritique, RiskFindings

# Two or three sentences plus a few conditions, on top of what this model spends
# reasoning before it answers. Sized per call: Groq charges max_tokens against
# the quota even when unused, and Agent 4 showed what happens when the budget is
# too tight - the generation is cut off mid-sentence and there is nothing left
# to salvage.
BRIEF_MAX_TOKENS = 2500

# Metric names an exit condition may legitimately name. Anything else is a
# metric the model invented, and a condition on a number nobody measures cannot
# be monitored any more than one citing no source at all.
KNOWN_METRICS = {
    "revenue_growth",
    "operating_margin",
    "gross_margin",
    "debt_to_equity",
    "net_income_is_negative",
    "free_cash_flow_is_negative",
}


def _brief_llm():
    """Model wired to emit a CompanyBrief. Lazy, so --help needs no key.

    ``json_schema`` for the reason recorded in the risk agent: under tool
    calling this model sometimes names the tool ``functions.<Schema>`` and the
    client rejects the whole response with nothing left to salvage.
    """
    return get_llm(max_tokens=BRIEF_MAX_TOKENS).with_structured_output(
        CompanyBrief, method="json_schema"
    )


BRIEF_SYSTEM_PROMPT = """
You write the final brief for ONE company that has already been selected. You
are not deciding whether to recommend it. That decision is made.

You will be given the company, the themes it was selected for, its measured
fundamentals, the risks a critic already found against it, and the articles
behind those risks.

WRITE TWO THINGS

1. A THESIS of two or three sentences: why this company, connecting the theme to
   what the company actually SELLS. Restating the theme is not a thesis. "It
   benefits from the AI buildout" says nothing; "it makes the lithography
   machines every advanced fab has to buy" says why this company rather than any
   other in the sector.

2. EXIT CONDITIONS: two or three things that, if they happened, would mean the
   case has broken.

EXIT CONDITIONS MUST BE CHECKABLE

Each one must be something a person could look up in six months and answer YES
or NO. Ground every condition in one of:
  - an article, cited by its exact [A3]-style label from the list below
  - a metric, named exactly: revenue_growth, operating_margin, gross_margin,
    debt_to_equity, net_income_is_negative, free_cash_flow_is_negative

A condition citing neither will be DISCARDED and the discard is counted.

These are NOT exit conditions:
  - "monitor the competitive landscape"     nothing to check
  - "if fundamentals deteriorate"           which fundamental, by how much
  - "if the share price falls significantly" that is a price, not a business
  - "if management fails to execute"        unfalsifiable

These ARE:
  - "the FTC probe results in a fine"       [cites the article reporting it]
  - "debt_to_equity rises above 3.0"        [names the metric]
  - "revenue_growth turns negative"         [names the metric]

AT LEAST ONE CONDITION MUST CITE AN ARTICLE

When articles are supplied below, at least one of your conditions must be about
what those articles describe. Metric thresholds are the easy answer and they are
the same for every company in every sector: "revenue_growth turns negative"
could be written without reading anything at all. The risks found against THIS
company are specific to it, and a brief that ignores them is generic advice
wearing the company's name.

DO NOT WATCH FOR SOMETHING THAT HAS ALREADY HAPPENED

You are told below which metrics have ALREADY crossed their threshold. A
condition on one of those is true the moment you write it, so it can never tell
anyone anything new. If the thing has already happened, either write about what
would make it WORSE, or pick something else.

BE HONEST ABOUT THE RISKS ALREADY FOUND
The critic's findings are given to you. Do not repeat them as if new, and do not
pretend they are not there. The thesis should hold DESPITE them, or say plainly
what would have to be true for it to.

FIT THE INVESTOR
You are told their risk tolerance and how long they intend to hold. If the
company is a poor fit for either - a speculative name for someone with low risk
tolerance, a slow story for a short horizon - say so in the thesis. Do not
quietly leave it out.

NO PRICES, NO POSITION SIZES, NO ALLOCATION
Never suggest how much to invest, what proportion of a portfolio to hold, or
what the shares are worth. That is advice, and this system is not licensed to
give it.

KEEP IT SHORT
"""


def _format_articles(articles: Sequence[Article]) -> tuple[str, dict[str, Article]]:
    """Render articles for the prompt and return the label -> article mapping.

    Labels are short ([A1], [A2], ...) because a model copies those reliably and
    a 36-character uuid it does not. Same mechanism as Agents 2 and 4.
    """
    lines: list[str] = []
    mapping: dict[str, Article] = {}

    for index, article in enumerate(articles, start=1):
        label = f"A{index}"
        mapping[label] = article
        lines.append(
            f"[{label}] {article.published_at:%Y-%m-%d} | {article.source}\n"
            f"{article.title}\n{article.description}"
        )

    return "\n\n".join(lines), mapping


def _evidence_for(
    critique: CandidateCritique, risks: RiskFindings
) -> list[Article]:
    """The articles behind this candidate's risks, deduplicated."""
    wanted = {uuid for risk in critique.risks for uuid in risk.article_ids}
    return [a for a in risks.articles if a.uuid in wanted]


def write_brief(
    candidate: CompanyCandidate,
    critique: CandidateCritique,
    profile: InvestorProfile,
    articles: Sequence[Article],
) -> tuple[CompanyBrief, dict[str, Article]]:
    """Ask the model for the thesis and exit conditions for one company."""
    rendered, mapping = _format_articles(articles)
    metrics = candidate.fundamentals.comparable

    risk_lines = "\n".join(
        f"- [{r.severity}] {r.claim}" for r in critique.risks
    ) or "- none were found"

    # Named explicitly rather than left for the model to infer from the numbers.
    # It wrote "free_cash_flow_is_negative" as a thing to watch for on a company
    # whose free cash flow was already -28,367,000.
    spent = sorted(_already_triggered(critique))
    spent_line = (
        "ALREADY CROSSED - do not use these as conditions: " + ", ".join(spent)
        if spent else "ALREADY CROSSED: none"
    )

    user_message = (
        f"COMPANY\n{candidate.name} ({candidate.ticker})\n"
        f"Exposure graded {candidate.exposure}: {candidate.exposure_rationale}\n"
        f"Themes: {', '.join(candidate.themes) or 'none recorded'}\n\n"
        f"MEASURED FUNDAMENTALS\n"
        f"revenue_growth={metrics.revenue_growth} "
        f"operating_margin={metrics.operating_margin}\n"
        f"gross_margin={metrics.gross_margin} "
        f"debt_to_equity={metrics.debt_to_equity}\n\n"
        f"INVESTOR\n"
        f"risk tolerance: {profile.risk_tolerance}; "
        f"holding period: {profile.holding_period}; age {profile.age}\n\n"
        f"RISKS ALREADY FOUND\n{risk_lines}\n\n"
        f"{spent_line}\n\n"
        f"ARTICLES BEHIND THOSE RISKS ({len(articles)})\n\n{rendered or 'none'}"
    )

    brief = invoke_structured(
        _brief_llm(),
        [("system", BRIEF_SYSTEM_PROMPT), ("human", user_message)],
        CompanyBrief,
        list_field="exit_conditions",
    )
    return brief, mapping


def _already_triggered(critique: CandidateCritique) -> set[str]:
    """Metrics that have ALREADY crossed their threshold for this company.

    Agent 4's fundamental rules fire on measured values, so a metric appearing
    among its risks is one where the bad thing has happened already.
    """
    return {r.metric for r in critique.risks if r.is_fundamental and r.metric}


def _resolve_conditions(
    brief: CompanyBrief,
    mapping: dict[str, Article],
    already_triggered: set[str],
) -> tuple[list[ExitCondition], int]:
    """Keep only the conditions that cite something real and not yet true.

    Three things are stripped:

    * a label the model invented, because it points at no article;
    * a metric the model invented, because nobody measures it;
    * a metric that has ALREADY crossed its threshold, because a condition that
      is true the moment it is written is not an exit condition.

    That last one was found by the eval. PowerBank was recommended with
    "free_cash_flow_is_negative" as the thing to watch for, while its free cash
    flow was already -28,367,000. The condition was perfectly checkable and
    immediately true, so it carried no information at all - the mirror image of
    the unfalsifiable conditions the prompt already bans, and invisible to every
    check that looks for vagueness.

    A condition left citing nothing usable is dropped entirely.
    """
    kept: list[ExitCondition] = []
    discarded = 0

    for condition in brief.exit_conditions:
        real_ids = [
            mapping[label].uuid
            for label in condition.article_ids
            if label in mapping
        ]

        metric = condition.metric
        if metric not in KNOWN_METRICS or metric in already_triggered:
            metric = None

        if not real_ids and metric is None:
            discarded += 1
            continue

        kept.append(condition.model_copy(
            update={"article_ids": real_ids, "metric": metric}
        ))

    return kept, discarded


def _fallback_conditions(
    candidate: CompanyCandidate, critique: CandidateCritique
) -> list[ExitCondition]:
    """A monitorable condition when the model produced none that survived.

    The schema refuses a recommendation with no way out of it, so something has
    to fill the gap. Dropping an otherwise sound company because the prose came
    back unusable would let a writing failure change the answer, which is the
    wrong trade.

    These are deliberately mechanical. They are built from what was already
    measured or already found, so they are always checkable, and they read as
    the generic conditions they are rather than pretending to insight.
    """
    for risk in critique.risks:
        if risk.article_ids:
            return [ExitCondition(
                condition=f"The reported problem develops further: {risk.claim}",
                article_ids=list(risk.article_ids),
            )]
        # "deteriorates FURTHER from x" is deliberate: the metric has already
        # crossed its threshold, so the only honest condition on it is one about
        # what happens next, not about it crossing again.
        if risk.metric in KNOWN_METRICS:
            return [ExitCondition(
                condition=(
                    f"{risk.metric} deteriorates further from its current "
                    f"value of {risk.metric_value}."
                ),
                metric=risk.metric,
            )]

    if candidate.fundamentals.comparable.revenue_growth is not None:
        return [ExitCondition(
            condition="revenue_growth turns negative for a full reporting period.",
            metric="revenue_growth",
        )]

    return [ExitCondition(
        condition="operating_margin turns negative for a full reporting period.",
        metric="operating_margin",
    )]


def decide(
    companies: CompanyFindings,
    risks: RiskFindings,
    profile: InvestorProfile,
) -> Decision:
    """Produce the final recommendation, or say why there is none.

    Selection happens first and in Python. Only companies that survive it are
    ever described, so the model cannot talk a rejected candidate back in.
    """
    chosen: Selection = select(companies, risks, profile)

    if not chosen.selected:
        return Decision(
            recommendations=[],
            excluded=chosen.excluded,
            no_recommendation_reason=chosen.no_recommendation_reason,
        )

    recommendations: list[Recommendation] = []
    discarded_total = 0

    for candidate, critique in chosen.selected:
        articles = _evidence_for(critique, risks)
        brief, mapping = write_brief(candidate, critique, profile, articles)

        conditions, discarded = _resolve_conditions(
            brief, mapping, _already_triggered(critique)
        )
        discarded_total += discarded

        if not conditions:
            conditions = _fallback_conditions(candidate, critique)

        recommendations.append(Recommendation(
            ticker=candidate.ticker,
            name=candidate.name,
            thesis=brief.thesis,
            exit_conditions=conditions,
            screen_score=candidate.screen_score,
            verdict=critique.verdict,
            exposure=candidate.exposure,
            themes=list(candidate.themes),
            evidence_article_ids=list(candidate.evidence_article_ids),
            known_risks=[r.claim for r in critique.risks],
        ))

    notes = None
    if chosen.excluded:
        notes = (
            f"Recommended {len(recommendations)} of "
            f"{len(recommendations) + len(chosen.excluded)} candidates "
            "considered; the rest are recorded with the reason each was not."
        )

    return Decision(
        recommendations=recommendations,
        excluded=chosen.excluded,
        conditions_discarded=discarded_total,
        notes=notes,
    )
