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

from config import get_llm
from models.profile import InvestorProfile
from models.research import Article, SearchQueries, ThemeProposal


@lru_cache(maxsize=1)
def _query_llm():
    """Model wired to emit SearchQueries. Lazy, for the reasons in config.py."""
    return get_llm().with_structured_output(SearchQueries)


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

    return _query_llm().invoke(
        [("system", QUERY_SYSTEM_PROMPT), ("human", user_message)]
    )


@lru_cache(maxsize=1)
def _theme_llm():
    """Model wired to emit a ThemeProposal. Lazy, as above."""
    return get_llm().with_structured_output(ThemeProposal)


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

relevance: ONE short sentence, under 20 words.
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

    proposal = _theme_llm().invoke(
        [("system", THEME_SYSTEM_PROMPT), ("human", user_message)]
    )
    return proposal, mapping
