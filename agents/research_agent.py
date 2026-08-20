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

from functools import lru_cache

from config import get_llm
from models.profile import InvestorProfile
from models.research import SearchQueries


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
