"""Agent 3 — Companies.

Turns Agent 2's themes and articles into a ranked shortlist of investable
companies with real fundamentals.

    1. extract_mentions()      LLM     articles -> company NAMES
    2. clients.companies       Python  names -> verified tickers + fundamentals
    3. assess_exposure()       LLM     is this company really tied to the theme?
    4. screen and rank         Python  computed from the fundamentals

Most of this agent is deterministic. The model is used at exactly two points,
both of which require reading prose: spotting which companies an article talks
about, and judging whether a company is genuinely exposed to a theme or merely
appeared in the same paragraph. Everything else - resolving a ticker, fetching
figures, screening, ranking - is code, because code does it correctly every time
and a model does not.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from agents.screening import MIN_SCORE, score, screen
from agents.structured import invoke_structured
from clients.companies import (
    CompanyDataError,
    ResolvedCompany,
    _search_raw,
    fetch_fundamentals,
    resolve_company,
)
from config import get_llm, get_settings
from models.companies import (
    CompanyCandidate,
    CompanyFindings,
    CompanyMention,
    DroppedCompany,
    ExposureAssessment,
    MentionExtraction,
)
from models.research import Article, ResearchFindings, Theme

# Response budgets, sized per call. Both of Agent 3's calls must fit inside the
# free tier's 8000 tokens per minute alongside their prompts, and gpt-oss-20b
# spends tokens on reasoning before the visible answer.
MENTION_MAX_TOKENS = 2500


@lru_cache(maxsize=1)
def _mention_llm():
    """Model wired to emit a MentionExtraction. Lazy, as in every other agent."""
    # Retried for the same reason as the research agent's query call: the
    # empty-generation 400 is intermittent, and "no companies at all" is a
    # real answer we want the model to state, not one we want to infer from
    # a failed request.
    return (
        get_llm(max_tokens=MENTION_MAX_TOKENS)
        .with_structured_output(MentionExtraction)
        .with_retry(stop_after_attempt=3)
    )


MENTION_SYSTEM_PROMPT = """
You read news articles and list the companies they name.

That is the whole job. You are not assessing investments, not judging which
companies are interesting, and not deciding anything about them yet.

NAMES ONLY. NEVER A TICKER SYMBOL.

Write the company name as the article writes it: "Nvidia", "Taiwan
Semiconductor", "Waaree Energies". Do NOT write NVDA, TSM, or any ticker.

Ticker symbols are looked up afterwards in a market database. A guessed ticker
is worse than no ticker, because several real symbols exist for the same
company - NVDA, NVDA.NE and NVD.DE are all "Nvidia" on different exchanges - and
the wrong one silently returns the wrong company's financials.

ONLY COMPANIES THE ARTICLE ACTUALLY NAMES

Do not add companies you happen to know are involved in the topic. If an article
discusses battery storage without naming a manufacturer, that article yields no
mentions. Your knowledge of the industry is not evidence.

WHAT IS NOT A COMPANY MENTION

  - Generic groups: "chipmakers", "the banks", "utilities", "automakers"
  - The publisher: Reuters, Bloomberg, Yahoo Finance, CNBC and similar appear
    as the SOURCE of an article, not as a company it is reporting on
  - Funds and ETFs: "ProShares Ultra SpaceX", "iShares Semiconductor ETF"
  - Indices: "the S&P 500", "Nasdaq Composite"
  - Countries, regulators and agencies: "the FDA", "the EU", "China"

Include a company even if you believe it is private or a subsidiary. Whether it
can be invested in is checked later against a market database; that is not your
decision to make.

ONE ENTRY PER COMPANY PER ARTICLE

If an article names the same company three times, that is one mention. If two
different articles name it, that is two mentions, one for each article label.

FOR EACH MENTION

  name        the company as written in the article
  article_id  the exact label of the article, e.g. "A3"
  context     one short sentence, under 15 words, on what the article says this
              company is doing

Use only labels that appear in the list you are given.

If the articles name no companies at all, return an empty list. That is a
correct answer, not a failure.
"""


def _format_articles(articles: Sequence[Article]) -> tuple[str, dict[str, Article]]:
    """Render articles for the prompt, and return the label -> article mapping.

    Short labels for the same reason Agent 2 uses them: a model copies "A3"
    reliably and a 36-character uuid unreliably. Python maps them back.
    """
    lines: list[str] = []
    mapping: dict[str, Article] = {}

    for index, article in enumerate(articles, start=1):
        label = f"A{index}"
        mapping[label] = article
        lines.append(
            f"[{label}] {article.published_at:%Y-%m-%d} | {article.source}\n"
            f"{article.title}\n{article.description}\n{article.snippet}"
        )

    return "\n\n".join(lines), mapping


def extract_mentions(
    findings: ResearchFindings,
) -> tuple[MentionExtraction, dict[str, Article]]:
    """List the companies named in Agent 2's cited articles.

    Args:
        findings: Output from Agent 2. Only the articles it actually cited are
            considered, since those are the ones tied to a theme.

    Returns:
        (extraction, label -> Article mapping). The mapping resolves the model's
        "A3"-style references back to real articles.

    Raises:
        Exception: Propagated from the model call if it fails after retries.
    """
    if not findings.articles:
        return MentionExtraction(mentions=[]), {}

    rendered, mapping = _format_articles(findings.articles)

    user_message = (
        f"ARTICLES ({len(findings.articles)} cited by the research stage)\n\n"
        f"{rendered}"
    )

    extraction = invoke_structured(
        _mention_llm(),
        [("system", MENTION_SYSTEM_PROMPT), ("human", user_message)],
        MentionExtraction,
        list_field="mentions",
        # "These articles name no companies" is a legitimate answer.
        empty_default=MentionExtraction(mentions=[]),
    )
    return extraction, mapping


EXPOSURE_MAX_TOKENS = 2000


@lru_cache(maxsize=1)
def _exposure_llm():
    """Model wired to emit an ExposureAssessment."""
    return (
        get_llm(max_tokens=EXPOSURE_MAX_TOKENS)
        .with_structured_output(ExposureAssessment)
        .with_retry(stop_after_attempt=3)
    )


@dataclass(frozen=True)
class ExposureRow:
    """One company considered against one theme.

    The unit of judgement is the PAIR, not the company. A semiconductor firm can
    be directly exposed to an AI-capacity theme and entirely incidental to a
    banking-regulation one, and collapsing that into a single per-company rating
    would lose the distinction that makes the field useful.
    """

    label: str
    company: ResolvedCompany
    theme_name: str
    theme_why: str
    contexts: tuple[str, ...]


EXPOSURE_SYSTEM_PROMPT = """
You judge how exposed a company is to a market theme.

For each numbered row you are given a company, its industry, a theme, and what
the articles said about that company. Grade the connection between that company
and that theme.

THE THREE LEVELS

  direct
      The theme materially drives this company's business. If the theme plays
      out, this company's revenue or earnings change noticeably.
      Example: a memory manufacturer, against a theme about AI data centre
      buildout driving memory demand.

  partial
      Real but secondary exposure. The company benefits or suffers, but the
      theme is not central to what it does.
      Example: an industrial conglomerate with one division serving the sector.

  incidental
      The company appeared in an article about the theme without being
      meaningfully affected by it. Same story, not the same business.
      Example: a bank named because it published a note about the sector, or a
      company mentioned only as a customer, comparison or bystander.

MOST MENTIONS ARE INCIDENTAL, AND SAYING SO IS THE POINT

News articles name companies constantly - as commentators, customers,
comparisons, or simply because they moved that day. Being named in an article
about a theme is not exposure to it.

Expect "direct" to be the MINORITY of your answers. If you are grading most rows
as direct, you are grading how relevant the article felt rather than how the
business is actually affected.

When you are unsure, answer "incidental". A company wrongly called incidental is
dropped, which costs one candidate. A company wrongly called direct is analysed,
ranked and recommended on a connection that does not exist.

USE THE INDUSTRY, NOT JUST THE ARTICLE

The industry field is the strongest signal you have. A company in "Banks -
Regional" is not directly exposed to a semiconductor manufacturing theme, no
matter how prominently the article named it. Where the article and the industry
disagree, trust the industry.

If the company's industry sits OUTSIDE the theme's sector, the highest grade
available is incidental - unless the article shows it producing, supplying or
building within that sector rather than using it. Size does not change this. A
very large buyer is still a buyer.

BUYING THE THING IS NOT EXPOSURE TO THE THING

The commonest error, and the one that reaches a reader looking plausible.

A company that PURCHASES what a theme is about is a customer of that theme, not
a participant in it. Grade it incidental. Ask which way the money flows: if the
theme playing out means this company SPENDS more, it is a buyer.

Measured on 2026-08-24: a beginner asking for renewable energy was recommended
Alphabet and Amazon, because both buy battery storage for their data centres.
Both connections are real and neither is renewable-energy exposure - they are an
advertising business and a retailer, and if grid storage booms their costs go
up. An investor who asked for renewable energy and received Alphabet has been
answered with something they could have found without this system.

  Buyer, so incidental:  a data centre operator against a battery storage theme
  Buyer, so incidental:  a carmaker against a lithium mining theme
  Buyer, so incidental:  a retailer against a logistics automation theme
  Participant, so grade it: the company MAKING the batteries, mining the
      lithium, or building the automation

FOR EACH ROW

  company_id  the row's exact label, e.g. "C3"
  exposure    direct, partial, or incidental
  rationale   one short sentence, under 20 words

Grade every row you are given, exactly once. Use only labels that appear.
"""


def _format_exposure_rows(rows: Sequence[ExposureRow]) -> str:
    blocks: list[str] = []
    for row in rows:
        company = row.company
        context = " ".join(row.contexts) or "(no additional context)"
        blocks.append(
            f"[{row.label}]\n"
            f"  company : {company.name} ({company.ticker})\n"
            f"  industry: {company.industry or 'unknown'} / "
            f"{company.sector or 'unknown'}\n"
            f"  theme   : {row.theme_name} - {row.theme_why}\n"
            f"  articles said: {context}"
        )
    return "\n\n".join(blocks)


def assess_exposure(rows: Sequence[ExposureRow]) -> ExposureAssessment:
    """Grade each company-theme pair as direct, partial or incidental.

    Args:
        rows: Company-theme pairs to judge, each carrying its own label.

    Returns:
        One verdict per row. Rows the model failed to grade are handled by the
        caller, which treats a missing verdict as incidental - the conservative
        default, since an ungraded company should not be promoted by accident.

    Raises:
        Exception: Propagated from the model call if it fails after retries.
    """
    if not rows:
        return ExposureAssessment(verdicts=[])

    user_message = (
        f"Grade all {len(rows)} rows.\n\n{_format_exposure_rows(rows)}"
    )

    return invoke_structured(
        _exposure_llm(),
        [("system", EXPOSURE_SYSTEM_PROMPT), ("human", user_message)],
        ExposureAssessment,
        list_field="verdicts",
        # An empty assessment is safe: ungraded pairs default to incidental,
        # which drops the company rather than promoting it.
        empty_default=ExposureAssessment(verdicts=[]),
    )


def _drop_reason_for_unresolved(name: str, use_cache: bool) -> tuple[str, str]:
    """Distinguish "nothing matched" from "matches existed but none qualified".

    Both return None from resolve_company, but they mean different things, and
    drop_summary is only useful if they are kept apart. A run full of
    no_ticker_found suggests extraction is producing names that are not
    companies; a run full of not_an_operating_company suggests the fund and
    subsidiary filters are doing their job.

    Uses the cached search, so this costs nothing.
    """
    try:
        hits = _search_raw(name, use_cache)
    except CompanyDataError:
        return "no_ticker_found", "search failed"

    if not hits:
        return "no_ticker_found", "no securities matched this name"
    return (
        "not_an_operating_company",
        f"{len(hits)} matches, none an investable operating company "
        "(private, a fund, a subsidiary, or a different business)",
    )


def _themes_by_article(research: ResearchFindings) -> dict[str, list[Theme]]:
    """Map each article uuid to the themes that cited it."""
    mapping: dict[str, list[Theme]] = {}
    for theme in research.themes:
        for evidence in theme.evidence:
            mapping.setdefault(evidence.article_id, []).append(theme)
    return mapping


def analyse_companies(
    research: ResearchFindings,
    *,
    use_cache: bool = True,
) -> CompanyFindings:
    """Agent 3, end to end: research findings in, ranked companies out.

    Args:
        research: Output from Agent 2.
        use_cache: Set False to force live provider calls.

    Returns:
        CompanyFindings. ``found_nothing`` is True when nothing survived, which
        is a legitimate outcome. ``drop_summary`` explains where everything went.

    Raises:
        Exception: Propagated from a model call that failed after its retries.
            The workflow catches this; see workflow.py.
    """
    settings = get_settings()
    dropped: list[DroppedCompany] = []
    notes: list[str] = []

    if research.found_nothing or not research.articles:
        return CompanyFindings(
            notes="No research themes to analyse, so no companies were examined."
        )

    # --- 1. articles -> company names (LLM) ---------------------------------
    extraction, article_map = extract_mentions(research)
    mentions = [m for m in extraction.mentions if m.article_id in article_map]

    invented = len(extraction.mentions) - len(mentions)
    if invented:
        notes.append(f"Ignored {invented} mention(s) citing an unknown article.")

    if not mentions:
        return CompanyFindings(
            mentions_extracted=0,
            notes="The articles named no companies. " + " ".join(notes),
        )

    # --- 2. group mentions by company name ----------------------------------
    by_name: dict[str, list[CompanyMention]] = {}
    for mention in mentions:
        by_name.setdefault(mention.name.strip(), []).append(mention)

    # Most-mentioned first: a company named across several articles is more
    # likely central to the story than one named once.
    ordered = sorted(by_name.items(), key=lambda kv: -len(kv[1]))

    if len(ordered) > settings.max_companies_examined:
        notes.append(
            f"{len(ordered)} companies were named; examined the "
            f"{settings.max_companies_examined} most frequently mentioned to "
            "stay within the data request budget."
        )
        ordered = ordered[: settings.max_companies_examined]

    # --- 3. resolve and fetch (Python) --------------------------------------
    theme_map = _themes_by_article(research)
    resolved: dict[str, dict] = {}

    for name, name_mentions in ordered:
        company = resolve_company(name, use_cache=use_cache)
        if company is None:
            reason, detail = _drop_reason_for_unresolved(name, use_cache)
            dropped.append(DroppedCompany(name=name, reason=reason, detail=detail))
            continue

        if company.ticker in resolved:
            # Two names for one company, such as AMD and Advanced Micro Devices.
            dropped.append(
                DroppedCompany(
                    name=name,
                    reason="duplicate",
                    detail=f"same company as an earlier mention ({company.ticker})",
                )
            )
            resolved[company.ticker]["mentions"].extend(name_mentions)
            continue

        try:
            fundamentals = fetch_fundamentals(company, use_cache=use_cache)
        except CompanyDataError as exc:
            dropped.append(
                DroppedCompany(name=name, reason="no_fundamentals", detail=str(exc))
            )
            continue

        resolved[company.ticker] = {
            "company": company,
            "fundamentals": fundamentals,
            "mentions": list(name_mentions),
        }

    if not resolved:
        return CompanyFindings(
            mentions_extracted=len(mentions),
            companies_examined=len(ordered),
            dropped=dropped,
            notes="No mentioned company resolved to an investable security. "
            + " ".join(notes),
        )

    # --- 4. build company-theme pairs for exposure judgement ----------------
    rows: list[ExposureRow] = []
    row_index: dict[str, tuple[str, Theme]] = {}

    for ticker, record in resolved.items():
        seen: dict[str, Theme] = {}
        for mention in record["mentions"]:
            article = article_map[mention.article_id]
            for theme in theme_map.get(article.uuid, []):
                seen.setdefault(theme.name, theme)

        for theme in seen.values():
            label = f"C{len(rows) + 1}"
            contexts = tuple(
                m.context
                for m in record["mentions"]
                if any(
                    t.name == theme.name
                    for t in theme_map.get(article_map[m.article_id].uuid, [])
                )
            )
            rows.append(
                ExposureRow(
                    label=label,
                    company=record["company"],
                    theme_name=theme.name,
                    theme_why=theme.why_it_matters,
                    contexts=contexts,
                )
            )
            row_index[label] = (ticker, theme)

    # --- 5. grade exposure (LLM) --------------------------------------------
    assessment = assess_exposure(rows)
    verdicts = {
        v.company_id: v for v in assessment.verdicts if v.company_id in row_index
    }

    ungraded = len(rows) - len(verdicts)
    if ungraded:
        notes.append(
            f"{ungraded} company-theme pair(s) were not graded and were treated "
            "as incidental."
        )

    # Best exposure a company reached across its themes. A company can be
    # incidental to one theme and direct to another; the direct link is the
    # reason to consider it at all, so that is the one that counts.
    rank = {"incidental": 0, "partial": 1, "direct": 2}
    best: dict[str, dict] = {}

    for label, (ticker, theme) in row_index.items():
        verdict = verdicts.get(label)
        level = verdict.exposure if verdict else "incidental"
        rationale = (
            verdict.rationale if verdict else "not graded; treated as incidental"
        )

        current = best.get(ticker)
        if current is None or rank[level] > rank[current["exposure"]]:
            best[ticker] = {
                "exposure": level,
                "rationale": rationale,
                "themes": {theme.name},
            }
        elif rank[level] == rank[current["exposure"]]:
            current["themes"].add(theme.name)

    # --- 6. screen, score and rank (Python) ---------------------------------
    candidates: list[CompanyCandidate] = []

    for ticker, record in resolved.items():
        verdict = best.get(
            ticker, {"exposure": "incidental", "rationale": "", "themes": set()}
        )
        company = record["company"]
        fundamentals = record["fundamentals"]

        if verdict["exposure"] == "incidental":
            dropped.append(
                DroppedCompany(
                    name=company.name,
                    reason="incidental_mention",
                    detail=verdict["rationale"] or "no meaningful link to any theme",
                )
            )
            continue

        passed, reason = screen(fundamentals.comparable)
        if not passed:
            dropped.append(
                DroppedCompany(
                    name=company.name,
                    reason=reason,
                    detail=(
                        "metrics available: "
                        f"{fundamentals.comparable.completeness:.0%}"
                    ),
                )
            )
            continue

        breakdown = score(fundamentals.comparable, verdict["exposure"])

        # A zero score is the ranking's own verdict that nothing about this
        # company supports recommending it. Keeping it and ranking it last would
        # still be recommending it, so it is dropped instead.
        if breakdown.total <= MIN_SCORE:
            dropped.append(
                DroppedCompany(
                    name=company.name,
                    reason="failed_screen",
                    detail=(
                        f"scored {breakdown.total:.3f} on "
                        f"{fundamentals.comparable.completeness:.0%} of metrics"
                    ),
                )
            )
            continue

        article_uuids = sorted(
            {article_map[m.article_id].uuid for m in record["mentions"]}
        )

        candidates.append(
            CompanyCandidate(
                ticker=ticker,
                name=company.name,
                exchange=company.exchange,
                currency=company.currency or fundamentals.amounts.currency,
                sector=company.sector or "",
                industry=company.industry or "",
                fundamentals=fundamentals,
                exposure=verdict["exposure"],
                exposure_rationale=verdict["rationale"],
                themes=sorted(verdict["themes"]),
                evidence_article_ids=article_uuids,
                screen_score=breakdown.total,
            )
        )

    candidates.sort(key=lambda c: -c.screen_score)

    if len(candidates) > settings.max_company_candidates:
        notes.append(
            f"Kept the {settings.max_company_candidates} highest-ranked of "
            f"{len(candidates)} qualifying companies."
        )
        candidates = candidates[: settings.max_company_candidates]

    return CompanyFindings(
        candidates=candidates,
        dropped=dropped,
        mentions_extracted=len(mentions),
        companies_examined=len(ordered),
        notes=" ".join(notes) or None,
    )
