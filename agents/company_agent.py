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
from functools import lru_cache

from config import get_llm
from models.companies import MentionExtraction
from models.research import Article, ResearchFindings

# Response budgets, sized per call. Both of Agent 3's calls must fit inside the
# free tier's 8000 tokens per minute alongside their prompts, and gpt-oss-20b
# spends tokens on reasoning before the visible answer.
MENTION_MAX_TOKENS = 2500


@lru_cache(maxsize=1)
def _mention_llm():
    """Model wired to emit a MentionExtraction. Lazy, as in every other agent."""
    return get_llm(max_tokens=MENTION_MAX_TOKENS).with_structured_output(
        MentionExtraction
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

    extraction = _mention_llm().invoke(
        [("system", MENTION_SYSTEM_PROMPT), ("human", user_message)]
    )
    return extraction, mapping
