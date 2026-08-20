"""Agent 2 — Research.

Turns a validated InvestorProfile into themes worth investigating, each grounded
in real retrieved news articles.

The agent runs in three stages:

    1. generate_search_queries()   LLM   profile -> search terms
    2. clients.news.search_many()  Python  terms -> real articles
    3. synthesise_themes()         LLM   articles -> themes citing article uuids

The ordering is the important part. The model never proposes a theme and then
goes looking for support — it reads what the world is actually publishing and
summarises that. Asking a model "what trends matter?" first would produce
plausible-sounding trends from training data that may be months or years stale,
and the search would then be confirmation-hunting for a conclusion already
reached.
"""

from collections.abc import Sequence
from functools import lru_cache

from agents.structured import invoke_structured
from clients.news import search_many
from config import get_llm, get_settings
from models.profile import InvestorProfile
from models.research import (
    Article,
    ResearchFindings,
    SearchQueries,
    Theme,
    ThemeProposal,
)


# Response budgets, sized per call rather than globally.
#
# Two constraints pull against each other:
#   * Groq counts max_tokens against the tokens-per-minute quota even when
#     unused, so both calls in this pipeline must fit inside 8000 TPM together.
#   * gpt-oss-20b is a REASONING model. It emits internal reasoning tokens
#     before the answer and those count too, so the budget must be far larger
#     than the visible output suggests. 512 looked generous for six short search
#     queries and truncated one mid-string.
#
# Budget: query (~600 prompt + 1500) + themes (~2000 prompt + 3000) = 7100.
QUERY_MAX_TOKENS = 2000
THEME_MAX_TOKENS = 3000


@lru_cache(maxsize=1)
def _query_llm():
    """Model wired to emit SearchQueries. Lazy, for the reasons in config.py."""
    # Retry the empty-generation failure. Groq reports it as 400 "model did
    # not call a tool" with an empty generation, which happens when the
    # model produces nothing at all. It is intermittent, and the correct
    # answer here is never "no queries", so retrying is right. ChatGroq's
    # own max_retries does not cover it: a 400 is a client error and the SDK
    # does not retry those.
    return (
        get_llm(max_tokens=QUERY_MAX_TOKENS)
        .with_structured_output(SearchQueries)
        .with_retry(stop_after_attempt=3)
    )


QUERY_SYSTEM_PROMPT = """
You turn an investor's profile into news search queries.

You are NOT deciding what to invest in, and you are NOT identifying trends yet.
Your only job is to produce the search terms that will retrieve news worth
reading for this particular investor.

WHAT MAKES A GOOD QUERY

Each search returns only THREE articles, so a wasted query is expensive.

Be SPECIFIC. Target a concrete development, policy, technology, company action
or event.

  Good:  "semiconductor export controls"
  Good:  "grid scale battery storage contracts"
  Good:  "GLP-1 drug manufacturing capacity"
  Bad:   "technology"            (too broad, returns generic noise)
  Bad:   "good stocks to buy"    (opinion pieces, not developments)
  Bad:   "investing"             (meaningless as a search)

Search for what is HAPPENING in an industry: regulation, capacity changes,
supply chains, major contracts, technology shifts, policy decisions, big
corporate moves. Do not search for stock recommendations or price predictions.

NEVER PUT A YEAR OR DATE IN A QUERY

Every search is already restricted to the last two weeks by a date filter
applied in code. Writing "2024", "2025", "this year" or "recent" does NOT make
results more recent — it pollutes the relevance ranking with articles that
merely happen to mention that year.

Measured on the live API: "solar farm approvals" returned articles about a solar
farm upgrade and solar-powered farming. The same query with "2024" appended
returned an asset acquisition in Poland and a story about diesel generators.
Same number of articles, visibly worse ones.

Write "semiconductor export controls", never "semiconductor export controls 2024".

COVER DIFFERENT ANGLES

Produce four to six queries that approach the investor's interests from
different directions rather than rephrasing one idea. Different phrasings
surface different stories, and variety is what makes the retrieved pool useful.

For an investor interested in renewable energy, four queries covering grid
storage, solar manufacturing, energy policy and transmission infrastructure are
far more useful than four rewordings of "renewable energy".

RESPECT RESTRICTIONS

If the profile lists restrictions, do not write queries that go looking for news
in those areas. A restriction against fossil fuel companies means no queries
about oil, gas or coal. The investor has already ruled those out and retrieving
them wastes requests.

USE THE WHOLE PROFILE

Interests are the main driver, but the rest matters too:
  - A short holding period favours near-term developments over decade-long
    structural shifts.
  - Low risk tolerance favours established industries over speculative ones.
  - A large investment amount may make capital-intensive sectors relevant.

Write queries in English. Use plain search terms, not questions or sentences.
"""


def generate_search_queries(profile: InvestorProfile) -> SearchQueries:
    """Ask the model for news search terms suited to this investor.

    Args:
        profile: A validated investor profile. Must not need clarification —
            searching on contradictory preferences wastes requests.

    Returns:
        Normalised, deduplicated search queries.

    Raises:
        Exception: Propagated from the model call if it fails after retries.
            The workflow catches this; see workflow.py.
    """
    user_message = (
        "Produce news search queries for this investor:\n"
        f"{profile.model_dump_json(indent=2, exclude={'status', 'clarification_reason'})}"
    )

    return invoke_structured(
        _query_llm(),
        [("system", QUERY_SYSTEM_PROMPT), ("human", user_message)],
        SearchQueries,
        list_field="queries",
        # No empty_default: "no search queries" is never a correct answer, so a
        # blank response must surface as a failure rather than a silent no-op.
    )


@lru_cache(maxsize=1)
def _theme_llm():
    """Model wired to emit a ThemeProposal. Lazy, as above."""
    return get_llm(max_tokens=THEME_MAX_TOKENS).with_structured_output(ThemeProposal)


THEME_SYSTEM_PROMPT = """
You identify investment themes from news articles that have already been
retrieved for a specific investor.

You do NOT recommend stocks. You do NOT give investment advice. You identify
what is happening that is worth investigating further.

GROUND EVERY THEME IN THE ARTICLES

You will be shown a numbered list of articles. Every theme you propose must be
supported by at least one of them.

You may NOT introduce a theme from your own knowledge. If you believe something
important is happening but no article in the list mentions it, leave it out.
Your training data has a cutoff; these articles are current. When they disagree
with what you remember, the articles are right.

HOW TO CITE

Each article carries a label like [A3]. Put that exact label in article_id.

Only labels that appear in the list are valid. Do not invent labels, do not
guess at ids, and do not cite an article that is not shown. A citation that does
not match a real label will be discarded, and a theme that loses all of its
citations is discarded with it.

BE HONEST ABOUT WHAT EACH ARTICLE SHOWS

Set stance truthfully:
  supports    - the article is evidence FOR the theme
  weakens     - the article is evidence AGAINST it
  complicates - relevant, but it cuts both ways

Do not label an article "supports" because you want the theme to look strong.
An article reporting a delay, a cancellation, a regulatory obstacle or falling
demand WEAKENS the theme it relates to, and saying so is more useful than a
tidy story. Contradicting evidence is passed to a later risk review, so hiding
it only makes the final recommendation worse.

RETURN FEWER THAN FIVE. RETURNING NONE IS CORRECT SOMETIMES.

Five is a maximum, not a target. Most sets of articles support two or three real
themes at most.

Return a theme ONLY if the articles genuinely show something worth investigating
for this investor. If the retrieved articles are thin, off-topic, or just
routine news with no investable angle, return fewer themes — or an empty list
with a note explaining why.

An empty list is a legitimate, useful answer. Padding the list with weak themes
is worse than returning nothing, because everything downstream will treat a
theme as though it mattered.

KEEP IT SHORT

name: at most SIX words. "FDA Approval Shifts", not "FDA Leadership Change
         Impact on the Drug Approval Landscape".
relevance: ONE short sentence, under 15 words.
why_it_matters: at most TWO sentences.
industries: at most three entries.

Long prose here is not rewarded. A verbose response risks being cut off before
it is complete, which loses the whole answer, not just the excess.

CONFIDENCE

  high   - several INDEPENDENT sources point the same way
  medium - one solid source, or several that only partly agree
  low    - suggestive but thin

Duplicate coverage has already been removed, so two articles here really are two
sources. Still, two articles is not "several".

RELEVANCE TO THIS INVESTOR

why_it_matters must be about THIS investor, not about the world in general.
Connect the theme to their stated interests, their holding period and their risk
tolerance.

Never propose a theme in an area the investor's restrictions rule out, however
strong the evidence. They have already said no.

TIMEFRAME

  already_underway  - happening now, visible in results today
  within_6_months   - expected to matter in the near term
  6_to_18_months    - building, not yet showing up
  beyond_18_months  - structural, long horizon
  unclear           - the articles do not say
"""


def _format_articles(articles: Sequence[Article]) -> tuple[str, dict[str, Article]]:
    """Render articles for the prompt and return the label -> article mapping.

    Labels are short ([A1], [A2], ...) because a model can copy those reliably
    and a 36-character uuid it cannot. The mapping is kept so Python can
    translate citations back afterwards.
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


def synthesise_themes(
    profile: InvestorProfile,
    articles: Sequence[Article],
) -> tuple[ThemeProposal, dict[str, Article]]:
    """Ask the model to find themes in the retrieved articles.

    Args:
        profile: The investor the research is for.
        articles: Deduplicated articles from the news client.

    Returns:
        (proposal, label -> Article mapping). The mapping is needed to translate
        the model's [A3]-style citations back to real articles.

    Raises:
        Exception: Propagated from the model call if it fails after retries.
    """
    if not articles:
        return ThemeProposal(themes=[], notes="No articles were retrieved."), {}

    rendered, mapping = _format_articles(articles)

    user_message = (
        "INVESTOR\n"
        f"{profile.model_dump_json(indent=2, exclude={'status', 'clarification_reason'})}"
        f"\n\nARTICLES ({len(articles)} retrieved, most recent search)\n\n"
        f"{rendered}"
    )

    proposal = invoke_structured(
        _theme_llm(),
        [("system", THEME_SYSTEM_PROMPT), ("human", user_message)],
        ThemeProposal,
        list_field="themes",
        # An empty response IS an answer here: the prompt explicitly permits
        # returning no themes when nothing clears the evidence bar, and the
        # model sometimes expresses that by producing nothing at all.
        empty_default=ThemeProposal(
            themes=[],
            notes=(
                "The model returned no themes for these articles, which it does "
                "when nothing clears the bar."
            ),
        ),
    )

    return proposal, mapping


# Ordered worst-to-best so max() and sorting behave intuitively.
_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


def _resolve_citations(
    proposal: ThemeProposal,
    mapping: dict[str, Article],
) -> tuple[list[Theme], list[str]]:
    """Discard invented citations and rewrite valid labels to real uuids.

    The schema prevents the model from WRITING article data. It cannot prevent
    the model from citing [A17] when only [A14] exists — the schema has no idea
    what was retrieved. That check belongs here, and it is a plain set
    membership test.

    A theme that loses every citation is dropped entirely. Its evidence was
    invented, so whatever it was describing did not come from the articles, and
    an ungrounded theme is exactly what searching first was meant to prevent.

    Returns:
        (themes with real uuids, human-readable notes about what was dropped)
    """
    kept: list[Theme] = []
    problems: list[str] = []

    for theme in proposal.themes:
        valid = [e for e in theme.evidence if e.article_id in mapping]
        invented = len(theme.evidence) - len(valid)

        if invented:
            problems.append(
                f"{theme.name!r}: dropped {invented} citation(s) referring to "
                "articles that were never retrieved"
            )

        if not valid:
            problems.append(
                f"{theme.name!r}: dropped entirely - every citation was invalid, "
                "so the theme was not grounded in retrieved evidence"
            )
            continue

        # Rewrite each surviving label to the article's real uuid, so Agent 3
        # can match evidence against ResearchFindings.articles.
        resolved = [
            e.model_copy(update={"article_id": mapping[e.article_id].uuid})
            for e in valid
        ]
        kept.append(theme.model_copy(update={"evidence": resolved}))

    return kept, problems


def research_themes(
    profile: InvestorProfile,
    *,
    use_cache: bool = True,
) -> ResearchFindings:
    """Agent 2, end to end: profile in, grounded themes out.

    Args:
        profile: A validated investor profile.
        use_cache: Set False to force live news searches.

    Returns:
        ResearchFindings. ``found_nothing`` is True when nothing cleared the
        bar, which is a legitimate outcome rather than a failure.

    Raises:
        ValueError: The profile still needs clarification. Researching against
            contradictory preferences wastes requests and produces themes the
            investor may have already ruled out.
        Exception: Propagated from a model call that failed after its retries.
            The workflow catches this; see workflow.py.
    """
    if profile.needs_clarification:
        raise ValueError(
            "Cannot research an unvalidated profile: "
            f"{profile.clarification_reason}"
        )

    settings = get_settings()
    notes: list[str] = []

    # --- 1. profile -> search queries (LLM) ---------------------------------
    queries = generate_search_queries(profile).queries

    if len(queries) > settings.news_max_queries:
        notes.append(
            f"Model proposed {len(queries)} queries; ran the first "
            f"{settings.news_max_queries} to stay within the request budget."
        )
        queries = queries[: settings.news_max_queries]

    # --- 2. queries -> real articles (Python) -------------------------------
    articles, succeeded = search_many(queries, use_cache=use_cache)

    if len(succeeded) < len(queries):
        notes.append(
            f"{len(queries) - len(succeeded)} of {len(queries)} searches failed; "
            "themes are based on the rest."
        )

    if not articles:
        return ResearchFindings(
            queries_used=succeeded,
            articles_retrieved=0,
            notes="No articles were retrieved, so no themes could be grounded. "
            + " ".join(notes),
        )

    # --- 3. articles -> themes (LLM) ----------------------------------------
    proposal, mapping = synthesise_themes(profile, articles)

    # --- 4. verify every citation is real (Python) --------------------------
    themes, problems = _resolve_citations(proposal, mapping)
    notes.extend(problems)

    # --- 5. cap the number of themes, loudly --------------------------------
    # Silent truncation reads as "this is everything" when it is not, so if the
    # cap bites it goes in the notes.
    if len(themes) > settings.research_max_themes:
        themes.sort(key=lambda t: _CONFIDENCE_RANK[t.confidence], reverse=True)
        notes.append(
            f"Kept the {settings.research_max_themes} highest-confidence themes "
            f"out of {len(themes)}."
        )
        themes = themes[: settings.research_max_themes]

    # --- 6. attach only the articles actually cited -------------------------
    cited_uuids = {e.article_id for theme in themes for e in theme.evidence}
    cited_articles = [a for a in articles if a.uuid in cited_uuids]

    if proposal.notes:
        notes.append(proposal.notes)

    return ResearchFindings(
        themes=themes,
        articles=cited_articles,
        queries_used=succeeded,
        articles_retrieved=len(articles),
        notes=" ".join(notes) or None,
    )
