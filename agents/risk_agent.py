"""Agent 4 — the risk critic. Attacks each candidate Agent 3 ranked.

THE SHAPE

    for each candidate, best-ranked first, up to the configured cap:
        Python   builds bear-case queries          (deterministic)
        Python   retrieves articles for them       (news client, cached)
        LLM      reads the articles, returns risks (judgement about prose)
        Python   discards any risk citing an article that was not retrieved
        Python   adds risks derived from the fundamentals
        Python   computes the verdict from severities

One model call per critiqued candidate. Everything else is arithmetic or string
handling, which is the same division of labour as Agents 2 and 3: the model is
used where language has to be judged, and nowhere else.

WHY IT RETRIEVES ITS OWN EVIDENCE

Agent 2 has recorded a dissenting stance exactly once, ever. That is not a
prompt failure - the cause is structural. A theme is built out of the articles
that support it, so an article contradicting it becomes a DIFFERENT theme rather
than dissent within this one, and most themes end up citing a single article
anyway, which cannot disagree with itself.

So the corpus Agent 2 hands on contains almost no bad news, and a critic reading
only that corpus would confirm whatever it was given. Going and looking for the
bear case is the job, not a workaround.

WHAT THIS AGENT MUST NOT DO

It must not produce a score. Agent 3's ranking is Python arithmetic over
provider data precisely so that it is reproducible and inspectable, and a
model-invented number competing with it would destroy that property. This agent
produces grounded risks and a verdict derived from them; Agent 5 decides.

It must not manufacture criticism. Asked to attack a company, a model will
always find something to say, and "competition is intense" is true of every
company ever listed. An empty risk list is a legitimate, useful answer - which
is why the effort spent is recorded beside it, so silence can be told apart from
soundness.
"""

from __future__ import annotations

from typing import Sequence

from agents.bear_queries import bear_queries
from agents.risk_rules import fundamental_risks
from agents.structured import invoke_structured
from clients.news import NewsAPIError, drop_low_quality, search_many
from config import get_llm, get_settings
from models.companies import CompanyCandidate, CompanyFindings
from models.research import Article
from models.risk import (
    CandidateCritique,
    NewsRiskAssessment,
    Risk,
    RiskFindings,
)

# Sized per call rather than globally, because Groq charges max_tokens against
# the quota even when unused.
#
# 1600 was not enough and the failure was ugly: the provider returned a 400 with
# the generation cut off mid-sentence ("Pfizer's non-"), so there was not even
# valid JSON left to salvage. This model reasons before it answers, so the
# budget has to cover the thinking as well as the output - the same trap
# recorded for the theme call, which sits at 3000 for a comparable job.
RISK_MAX_TOKENS = 3000


def _risk_llm():
    """Model wired to emit a NewsRiskAssessment. Lazy, so --help needs no key.

    ``json_schema`` rather than the default tool-calling path. Under tool
    calling this model names the tool ``functions.NewsRiskAssessment``, and the
    client rejects the whole response with "Unknown tool type" - the answer is
    thrown away over a naming convention, and there is no failed_generation on
    that error to salvage from. Asking for a JSON object instead removes the
    tool envelope, and with it the chance to misname it.
    """
    return get_llm(max_tokens=RISK_MAX_TOKENS).with_structured_output(
        NewsRiskAssessment, method="json_schema"
    )


RISK_SYSTEM_PROMPT = """
You are a risk critic. Your job is to find the reasons an investment case could
FAIL. Assume the analysts before you were too optimistic.

You will be given one company, why it was selected, and news articles retrieved
specifically to find bad news about it.

GROUND EVERY RISK IN THE ARTICLES

Each article carries a label like [A3]. Put those exact labels in article_ids.

Only labels that appear in the list are valid. Do not invent labels and do not
cite an article that is not shown. A risk citing a label that does not exist
will be DISCARDED, and discarded risks are counted and reported.

If the articles do not support a risk, you cannot report that risk. You are not
being asked what could theoretically go wrong. You are being asked what these
articles show.

DO NOT MANUFACTURE CRITICISM

Return an EMPTY list if the articles show nothing that genuinely undermines the
case. That is a real finding and it is reported as one.

These are NOT risks, and reporting them is worse than reporting nothing:
  - "competition is intense"          true of every company ever listed
  - "valuation may be stretched"      an opinion about price, not the business
  - "macro conditions are uncertain"  true always, everywhere
  - "the share price could fall"      that is what a share price is

A risk must name a SPECIFIC MECHANISM of harm. Not "faces competition" but
"a rival's new plant adds supply in the segment that produced most of the
margin". If you cannot name the mechanism, you do not have a risk.

ALREADY-KNOWN BAD NEWS IS STILL A RISK
Report what the articles show even if it seems widely known. What you must not
do is invent something the articles do not support.

SEVERITY
  critical  - undermines the reason for holding the company at all
  material  - a real cost to the case; changes how large a position makes sense
  minor     - worth knowing; would not change a decision on its own

Use critical sparingly. It is for a fact that breaks the thesis - a fraud
investigation, losing the customer that is most of revenue, the product being
banned - not for bad news that is merely serious.

TYPE
  competitive          a rival, a substitute, pricing pressure
  regulatory           law, licence, investigation, sanction
  financial            leverage, cash burn, margin compression
  execution            delay, recall, failed launch, key people leaving
  concentration        one customer, one product, one geography
  thesis_invalidation  the THEME itself is weaker than it was thought to be

KEEP IT SHORT
One sentence per claim. Name the mechanism, not the mood.
"""


def _format_articles(articles: Sequence[Article]) -> tuple[str, dict[str, Article]]:
    """Render articles for the prompt and return the label -> article mapping.

    Labels are short ([A1], [A2], ...) because a model can copy those reliably
    and a 36-character uuid it cannot. Same mechanism as Agent 2.
    """
    lines: list[str] = []
    mapping: dict[str, Article] = {}

    for index, article in enumerate(articles, start=1):
        label = f"A{index}"
        mapping[label] = article
        lines.append(
            f"[{label}] {article.published_at:%Y-%m-%d} | {article.source}\n"
            f"{article.title}\n"
            f"{article.description}\n"
            f"{article.snippet}"
        )

    return "\n\n".join(lines), mapping


def assess_news_risks(
    candidate: CompanyCandidate,
    articles: Sequence[Article],
) -> tuple[NewsRiskAssessment, dict[str, Article]]:
    """Ask the model what the retrieved articles show against this candidate.

    Returns:
        (assessment, label -> Article mapping) so Python can translate the
        model's [A3]-style citations back to real articles afterwards.
    """
    if not articles:
        return (
            NewsRiskAssessment(
                risks=[], notes="No bear-case articles were retrieved."
            ),
            {},
        )

    rendered, mapping = _format_articles(articles)

    user_message = (
        f"COMPANY\n{candidate.name} ({candidate.ticker})\n\n"
        f"WHY IT WAS SELECTED\n"
        f"Exposure graded {candidate.exposure}: {candidate.exposure_rationale}\n"
        f"Themes: {', '.join(candidate.themes) or 'none recorded'}\n\n"
        f"ARTICLES ({len(articles)} retrieved by searching for bad news)\n\n"
        f"{rendered}"
    )

    assessment = invoke_structured(
        _risk_llm(),
        [("system", RISK_SYSTEM_PROMPT), ("human", user_message)],
        NewsRiskAssessment,
        list_field="risks",
        # An empty response IS an answer here: the prompt explicitly permits
        # finding nothing, and the model often expresses that by returning
        # nothing at all rather than an empty list.
        empty_default=NewsRiskAssessment(
            risks=[],
            notes="The model reported nothing in these articles that undermines the case.",
        ),
    )

    return assessment, mapping


def _resolve_citations(
    assessment: NewsRiskAssessment,
    mapping: dict[str, Article],
    ticker: str,
) -> tuple[list[Risk], int]:
    """Discard invented citations and rewrite valid labels to real uuids.

    A risk keeps only the labels that were actually shown. If none of its labels
    survive, the risk itself is dropped - it is then grounded in nothing, which
    is the one thing the schema refuses to represent.

    The ticker is overwritten rather than trusted. The model is told which
    company it is looking at, but a risk filed against the wrong ticker would
    attach criticism to a company nobody examined.

    Returns:
        (surviving risks, how many were discarded)
    """
    kept: list[Risk] = []
    discarded = 0

    for risk in assessment.risks:
        real_ids = [
            mapping[label].uuid for label in risk.article_ids if label in mapping
        ]
        if not real_ids:
            discarded += 1
            continue

        kept.append(
            risk.model_copy(update={"article_ids": real_ids, "ticker": ticker})
        )

    return kept, discarded


def _retrieve_bear_case(
    candidate: CompanyCandidate, use_cache: bool
) -> tuple[list[Article], list[str]]:
    """Search for bad news about one candidate.

    A provider failure is not allowed to end the run. The critic reporting
    "nothing retrieved" for one company is a far better outcome than the whole
    pipeline failing, and the empty article count records that it happened.
    """
    queries = bear_queries(candidate)

    try:
        articles, succeeded = search_many(queries, use_cache=use_cache)
    except NewsAPIError:
        return [], []

    # Commentary and advocacy are withheld before the model ever sees them.
    # A real citation to a worthless article still produces a worthless risk,
    # and the model cannot judge a source it is simply handed as evidence.
    kept, _dropped = drop_low_quality(articles)
    return kept, succeeded


# Worst first, so the most severe of a duplicated pair is the one kept.
_SEVERITY_RANK = {"critical": 0, "material": 1, "minor": 2}


def deduplicate_risks(risks: list[Risk]) -> list[Risk]:
    """Collapse risks that rest on the same evidence.

    Two risks citing the same article are one finding described twice, and the
    verdict is arithmetic over severity COUNTS - so a story counted twice can
    cross the "two material risks" threshold on its own. The threshold is only
    meaningful if the risks it counts are independent, and nothing else in this
    agent enforces that.

    The most severe of a duplicated group is kept, not the first: a story
    reported as material in one risk and minor in another is material.

    Fundamental risks are never collapsed. Each one names a different metric,
    so they are independent by construction.
    """
    ordered = sorted(risks, key=lambda r: _SEVERITY_RANK[r.severity])

    kept: list[Risk] = []
    claimed: set[str] = set()

    for risk in ordered:
        if risk.is_fundamental:
            kept.append(risk)
            continue

        ids = set(risk.article_ids)
        if ids & claimed:
            continue

        claimed |= ids
        kept.append(risk)

    # Restore the original ordering so output stays stable and readable.
    return [r for r in risks if r in kept]


def critique_candidate(
    candidate: CompanyCandidate, *, use_cache: bool = True
) -> tuple[CandidateCritique, int, list[Article]]:
    """Attack one candidate: retrieve, judge, ground, and add the numbers.

    Returns:
        (critique, risks discarded for citing nothing retrievable, cited
        articles). The articles are returned so the assembled findings can carry
        them: a uuid Agent 5 cannot resolve is not a citation, it is a string.
    """
    articles, queries_used = _retrieve_bear_case(candidate, use_cache)

    assessment, mapping = assess_news_risks(candidate, articles)
    news_risks, discarded = _resolve_citations(assessment, mapping, candidate.ticker)

    cited_ids = {uuid for risk in news_risks for uuid in risk.article_ids}
    cited = [a for a in articles if a.uuid in cited_ids]

    # Fundamental risks are added AFTER the model call and are never shown to
    # it. They are computed from numbers Agent 3 already measured, so putting
    # them in the prompt would only invite the model to restate them as if it
    # had found them - and they would then be counted twice in the verdict.
    risks = deduplicate_risks(news_risks) + fundamental_risks(candidate)

    return (
        CandidateCritique(
            ticker=candidate.ticker,
            name=candidate.name,
            risks=risks,
            queries_used=queries_used,
            articles_reviewed=len(articles),
        ),
        discarded,
        cited,
    )


def critique_companies(
    findings: CompanyFindings, *, use_cache: bool = True
) -> RiskFindings:
    """Run the risk critic over Agent 3's candidates.

    Candidates are attacked best-ranked first, up to ``max_critique_candidates``.
    Everything beyond the cap is still RECORDED, with the reason it was skipped,
    because a candidate silently missing from the critique would reach Agent 5
    looking uncriticised rather than unexamined.

    ``found_nothing`` on the input is handled here rather than by the caller:
    there is nothing to criticise, and saying so in the notes keeps the reason
    visible instead of leaving an empty result to be interpreted.
    """
    settings = get_settings()

    if findings.found_nothing:
        return RiskFindings(
            critiques=[],
            notes="Agent 3 found no candidates, so there was nothing to criticise.",
        )

    ranked = sorted(findings.candidates, key=lambda c: -c.screen_score)
    examined = ranked[: settings.max_critique_candidates]
    skipped = ranked[settings.max_critique_candidates :]

    critiques: list[CandidateCritique] = []
    articles_retrieved = 0
    risks_discarded = 0
    cited: dict[str, Article] = {}

    for candidate in examined:
        critique, discarded, used = critique_candidate(candidate, use_cache=use_cache)
        critiques.append(critique)
        articles_retrieved += critique.articles_reviewed
        risks_discarded += discarded
        # Keyed by uuid: two candidates can be criticised by the same article,
        # and Agent 5 should see it once.
        cited.update({a.uuid: a for a in used})

    for candidate in skipped:
        critiques.append(
            CandidateCritique(
                ticker=candidate.ticker,
                name=candidate.name,
                skipped_reason=(
                    f"outside the {settings.max_critique_candidates}-candidate "
                    "critique cap for this run"
                ),
            )
        )

    notes = None
    if skipped:
        notes = (
            f"Critiqued the {len(examined)} highest-ranked of "
            f"{len(ranked)} candidates; the rest are recorded as skipped."
        )

    return RiskFindings(
        critiques=critiques,
        articles=list(cited.values()),
        articles_retrieved=articles_retrieved,
        risks_discarded=risks_discarded,
        notes=notes,
    )
