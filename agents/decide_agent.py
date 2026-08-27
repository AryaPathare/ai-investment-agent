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
from clients.companies import fetch_fx_rate
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
from models.research import Article, ResearchFindings
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

    RETRIED, which it was not until a live run died here. The provider returns
    an intermittent 400 with an EMPTY ``failed_generation`` - the model produced
    nothing at all, rather than something wrong. Agents 2 and 3 already retry
    for exactly this and record it as intermittent.

    It matters most at this stage. Agent 5 runs last, so an unretried blip
    throws away the research, the company analysis and the risk critique that
    were already paid for - about 30k of a 200k daily budget - to save one
    retry of a single call.
    """
    return (
        get_llm(max_tokens=BRIEF_MAX_TOKENS)
        .with_structured_output(CompanyBrief, method="json_schema")
        .with_retry(stop_after_attempt=3)
    )


BRIEF_SYSTEM_PROMPT = """
You write the final brief for ONE company that has already been selected. You
are not deciding whether to recommend it. That decision is made.

You will be given the company, the themes it was selected for, its measured
fundamentals, the risks a critic already found against it, and the articles
behind all of that - both the ones a critic cited AGAINST this company and the
ones that put it in the theme to begin with.

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

WRITE FOR SOMEONE WHO HAS NEVER BOUGHT A SHARE

That is who reads this. They chose a sector from a list twenty minutes ago. Every
sentence they have to read twice is a sentence that has failed.

ONE IDEA PER SENTENCE, and keep sentences under about twenty words. The failure
is never that the thought was too complex - it is three thoughts joined by
commas.

  Hard:  "CATL is the world's largest lithium-ion battery manufacturer,
          positioned to capture the rapid growth in energy storage demand driven
          by electric vehicles and grid-scale storage."
  Plain: "CATL makes more lithium-ion batteries than anyone else in the world.
          Electric cars and power grids both need them, and demand is growing
          fast."

SAY WHAT THE COMPANY SELLS, in the words a person outside the industry would
use. "It makes the machines that print circuits onto silicon wafers" beats "it
supplies advanced lithography solutions".

BANNED, because they say nothing a reader can picture:

  positioned to capture        well-placed to benefit
  diversified portfolio        compelling play
  competitive edge over rivals strong fundamentals
  robust growth trajectory     leveraging its expertise

If you name a financial measure, say what it means in the same breath: "a 37%
operating margin, meaning it keeps 37p of profit from every pound of sales".

The same applies to the exit conditions. "The Italian order is cancelled" is
something a person can check. "Order book deterioration materialises" is not.

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
    critique: CandidateCritique,
    risks: RiskFindings,
    candidate: CompanyCandidate | None = None,
    research: ResearchFindings | None = None,
) -> list[Article]:
    """Every article this candidate is allowed to cite, deduplicated.

    TWO sources, and for a long time Agent 5 was handed only the first.

    ``RiskFindings.articles`` keeps the articles a risk actually CITED, and
    ``risk_rules`` produces metric-derived risks that cite nothing. So a
    candidate whose risks were all thresholds arrived here with an EMPTY list
    and then satisfied the citation rule vacuously - there was nothing to cite.
    That is what the 1-of-8 citation rate was really measuring: not a model
    taking the cheap option, but one article reaching the only company that had
    one. Agent 5 complied every time it could.

    The second source is the candidate's own ``evidence_article_ids`` - the
    articles that put it in the theme at all. They were carried the whole way
    down and then never passed in, because they live in ``ResearchFindings``
    and ``decide()`` was never given it.

    Risk articles come FIRST because they are the bear case, and an exit
    condition is a bear-case question. A theme article is bullish, so it is
    weaker grounds for "what would mean this has broken" - available, but not
    the first thing offered.

    Both extra arguments are optional so that a caller with no research to hand
    still gets the old behaviour rather than an error.
    """
    wanted = {uuid for risk in critique.risks for uuid in risk.article_ids}
    evidence = [a for a in risks.articles if a.uuid in wanted]

    if candidate is None or research is None:
        return evidence

    seen = {article.uuid for article in evidence}
    theme_ids = set(candidate.evidence_article_ids)
    for article in research.articles:
        if article.uuid in theme_ids and article.uuid not in seen:
            seen.add(article.uuid)
            evidence.append(article)

    return evidence


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
        f"ARTICLES ({len(articles)}) - those a risk cited, then those "
        f"the company was selected for\n\n{rendered or 'none'}"
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


def _affordability(price, profile) -> tuple[int | None, float | None]:
    """How many shares the stated amount buys, and the price in their money.

    Converts when the currencies differ, which the first version of this
    deliberately refused to do. The refusal was the right default and the wrong
    outcome: a run whose investor said USD was recommended a Shenzhen listing in
    CNY and a Vietnamese one in VND, so every line read "not converted". The
    pipeline's job is to find companies anywhere, so currency agreement is the
    exception rather than something a sensible default can secure.

    Returns (None, None) whenever anything is missing - no price, no stated
    currency, no rate available - and the brief then shows the price alone,
    which is the behaviour this replaces rather than removes.
    """
    currency = getattr(profile, "investment_currency", None)
    if price is None or not currency:
        return None, None

    amount, code = price.in_major_units
    rate = fetch_fx_rate(currency, code)
    if rate is None:
        return None, None

    # Their money, in the currency the share trades in.
    converted = profile.investment_amount * rate
    if amount <= 0:
        return None, None

    # Floor, not round: telling someone they can afford a share they cannot is
    # the one direction of error that matters here.
    return int(converted // amount), amount / rate


def decide(
    companies: CompanyFindings,
    risks: RiskFindings,
    profile: InvestorProfile,
    research: ResearchFindings | None = None,
) -> Decision:
    """Produce the final recommendation, or say why there is none.

    Selection happens first and in Python. Only companies that survive it are
    ever described, so the model cannot talk a rejected candidate back in.

    ``research`` is what a candidate was selected FOR. Without it a candidate
    whose risks are all metric thresholds has no article to cite and cannot
    meet the prompt's citation rule at all - see ``_evidence_for``. It is
    optional because a decision is still produceable without it, and the
    Selection above does not depend on it.
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
        articles = _evidence_for(critique, risks, candidate, research)
        brief, mapping = write_brief(candidate, critique, profile, articles)

        conditions, discarded = _resolve_conditions(
            brief, mapping, _already_triggered(critique)
        )
        discarded_total += discarded

        if not conditions:
            conditions = _fallback_conditions(candidate, critique)

        shares, unit_price = _affordability(candidate.fundamentals.price, profile)

        recommendations.append(Recommendation(
            ticker=candidate.ticker,
            name=candidate.name,
            thesis=brief.thesis,
            exit_conditions=conditions,
            screen_score=candidate.screen_score,
            price=candidate.fundamentals.price,
            shares_affordable=shares,
            price_in_investor_currency=unit_price,
            verdict=critique.verdict,
            exposure=candidate.exposure,
            themes=list(candidate.themes),
            evidence_article_ids=list(candidate.evidence_article_ids),
            known_risks=[r.claim for r in critique.risks],
        ))

    notes = None
    if chosen.excluded:
        notes = (
            f"{len(recommendations) + len(chosen.excluded)} companies were "
            f"looked at closely and the best {len(recommendations)} are above. "
            "The rest are listed with the reason each one was not chosen."
        )

    return Decision(
        recommendations=recommendations,
        excluded=chosen.excluded,
        conditions_discarded=discarded_total,
        notes=notes,
    )
