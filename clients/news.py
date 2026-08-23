"""News search, wrapped behind our own interface.

The rest of the codebase calls ``search_news()`` and gets back ``Article``
objects. It never sees TheNewsAPI's JSON, its parameter names, or its quirks.

Why the wrapper exists
----------------------
1. **Swappability.** If the free tier proves too thin, moving to a different
   provider means rewriting this one file, not hunting vendor details through
   the agent code.
2. **Testability.** Tests mock this function, so no test ever touches the
   network — the same seam ``_structured_llm()`` provides for the LLM.
3. **It hides hard-won facts.** Everything below was learned by calling the
   real API, not from the documentation.

What testing the live API actually revealed
-------------------------------------------
* Cloudflare rejects Python's default urllib user-agent with ``403 error 1010``.
  ``requests`` works because it sends a normal one. We set an explicit UA too.
* The default search covers ALL history sorted by relevance — a query for
  "semiconductor" returned articles from 2023 and 2024. ``published_after`` is
  mandatory for an agent about current events.
* ``sort=relevance_score`` within a recent window beats ``sort=published_at``.
  Sorting by date returns whatever hit the wire last, which is mostly noise.
* ``snippet`` is ~163 characters, not the 60 the docs claim.
* The word ``OR`` is NOT query syntax and matches nothing. ``"Pfizer" lawsuit
  OR investigation`` returns zero articles; ``"Pfizer" lawsuit`` returns three.
* ``|`` IS syntax, but it applies across the WHOLE query, so a required phrase
  stops being required. ``"Pfizer" lawsuit | probe`` returned articles about an
  Israeli army probe and an Air India incident, with no Pfizer in them. For a
  search that must stay on one company, plain space-separated AND is the only
  reliable form.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

import requests

from config import PROJECT_ROOT, get_settings
from models.research import Article

API_URL = "https://api.thenewsapi.com/v1/news/all"
USER_AGENT = "ai-investment-agent/0.1 (personal research project)"

CACHE_DIR = PROJECT_ROOT / ".cache" / "news"

# Two near-identical titles above this ratio are treated as the same story.
# Deliberately high: wrongly merging two genuinely different articles loses
# evidence, which is worse than letting one duplicate through.
TITLE_SIMILARITY_THRESHOLD = 0.85


class NewsAPIError(RuntimeError):
    """The news provider could not be reached or refused the request."""


# --- Caching -----------------------------------------------------------------
# The free tier allows 100 requests a day. Without caching, every test run and
# every debugging cycle spends them, and each one waits on the network. With it,
# a repeated query is instant and free.


# Sources whose output is commentary, advocacy or aggregation rather than
# reporting. Articles from these are withheld from the risk critic.
#
# WHY THIS EXISTS, AND WHY IT IS UNCOMFORTABLE
#
# Grounding a risk in a retrieved article turns out to be necessary and not
# sufficient: the citation can be real while the article is worthless. Agent 4
# graded two MATERIAL risks against Pfizer - potential miscarriage litigation,
# and eroding vaccine demand - from two joemygod.com pieces, one of which was
# itself reporting that the underlying claim was a lie, and the other an
# advocacy group soliciting donations for lawsuits premised on it. Both risks
# were specific, correctly cited, and passed every check. Together they tipped
# the verdict from "survives" to "weakened".
#
# Judging which publications are credible is a real editorial judgement and this
# list is one. It is kept HERE, visible and short, rather than buried in a
# prompt, for the same reason the screening thresholds are: a judgement that
# changes results should be one a reader can find, argue with and edit.
#
# The test is not political slant. It is whether the outlet does original
# REPORTING that a business decision could rest on. An opinion blog may be
# entirely right and still not be evidence that a company faces litigation.
# Extended 2026-08-23 from EVIDENCE rather than from more searching. Every
# addition below actually appeared in .cache/news - 272 distinct articles across
# 130 sources - so none of it is a guess about what might turn up. That audit
# also measured the honest limits of this approach, recorded here because the
# number looks better than it is:
#
#   * the original seven removed 2.6% of the corpus; with these, 15.1%
#   * 86 of the 130 sources contributed exactly ONE article
#
# That tail is the real finding. **A list of names cannot cover a distribution
# where two thirds of sources appear once**, and no amount of extending it will.
# What this list is good for is the recurring offenders; what it cannot do is
# make the filter complete, and it should not be mistaken for having done so.
#
# Two problems found in the same audit are deliberately NOT addressed here,
# because a source denylist is the wrong instrument for either:
#
#   * Press releases - 6% of the corpus, "X Announces Second Quarter Results".
#     A press release is the company's own framing, which makes it close to
#     worthless to a RISK critic specifically. But it arrives through ordinary
#     newspapers that also do real reporting, so it has to be filtered by the
#     shape of the article, not by who carried it.
#   * Off-topic matches - dealigg.com is listed below as a non-publisher, but
#     the deeper issue is a battery-storage query returning retail battery
#     deals. That is a relevance failure, and no source list fixes relevance.
LOW_QUALITY_SOURCES = {
    # --- Commentary and advocacy, not reporting -----------------------------
    "joemygod.com",             # political commentary blog
    "thegatewaypundit.com",     # partisan commentary
    "zerohedge.com",            # financial commentary, frequently speculative
    "steynonline.com",          # personal opinion site
    "beforeitsnews.com",
    "naturalnews.com",
    "revolver.news",            # partisan commentary
    "endoftheamericandream.com",
    "activistpost.com",
    "unlimitedhangout.com",
    "wattsupwiththat.com",      # climate commentary blog
    "armstrongeconomics.com",   # self-published financial speculation

    # --- Not publishers at all ----------------------------------------------
    # These have no editorial process to judge. Several are not even websites a
    # person reads: they are tool endpoints and CDN hostnames that the provider
    # reports as the source, which is how "airedale.futurecdn.net" ends up
    # sitting in a corpus about renewable energy.
    "app.buzzsumo.com",         # content-marketing tool
    "airedale.futurecdn.net",   # CDN hostname
    "api.foxsports.com",        # API endpoint
    "news.ycombinator.com",     # link aggregator, no original reporting
    "dealigg.com",              # retail deals aggregator
    "prweb.com",                # press-release wire: paid placement
    "blog.hubspot.com",         # corporate content marketing

    # --- Content mills ------------------------------------------------------
    # Volume financial content optimised for search, not reporting a business
    # decision could rest on.
    "insidermonkey.com",
    "financefeeds.com",
    "investedwallet.com",
    "profitconfidential.com",
}


def drop_low_quality(articles: list[Article]) -> tuple[list[Article], list[str]]:
    """Split articles into those worth reasoning over and those that are not.

    Returns:
        (kept, dropped source names). The dropped sources are returned rather
        than discarded so a caller can report what was withheld - a filter that
        silently removes evidence is its own kind of unreliable narrator.
    """
    kept: list[Article] = []
    dropped: list[str] = []

    for article in articles:
        if article.source.lower() in LOW_QUALITY_SOURCES:
            dropped.append(article.source)
        else:
            kept.append(article)

    return kept, dropped


def _cache_path(params: dict) -> Path:
    """A stable filename for one set of request parameters.

    The API token is excluded from the key: it is not part of what identifies a
    query, and it must never be written into a filename.
    """
    key = json.dumps(
        {k: v for k, v in sorted(params.items()) if k != "api_token"},
        sort_keys=True,
    )
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{digest}.json"


def _read_cache(path: Path, ttl_hours: float) -> dict | None:
    if ttl_hours <= 0 or not path.exists():
        return None
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    if age_hours > ttl_hours:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None  # a corrupt cache entry should never break a real run


# The key the provenance block is written under. Leading underscore so it can
# never collide with a field the provider adds later: everything TheNewsAPI
# returns is a bare name ("meta", "data").
PROVENANCE_KEY = "_provenance"


def _write_cache(path: Path, payload: dict, provenance: dict | None = None) -> None:
    """Write a response to the cache, with a record of what asked for it.

    WHY THE PROVENANCE BLOCK EXISTS

    The cache used to store the provider's reply and nothing else. That made it
    a corpus of articles with no record of the questions that produced them,
    and the cost showed up the first time anyone tried to learn from it: an
    audit of 272 cached articles could see that 6% were press releases and
    could NOT tell whether they reached the theme research or the risk critic -
    two agents for whom that content means completely different things.

    A press release is ordinary input for Agent 2 and close to worthless for
    Agent 4, whose entire job is the bear case. So the one question worth asking
    was the one the cache could not answer, and the finding had to be written
    down as unproven.

    The block is namespaced under a leading underscore and everything else is
    left exactly as the provider sent it, so `payload["data"]` is untouched and
    the 224 entries written before this change stay readable - they simply have
    no provenance, which is itself accurate.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if provenance is not None:
            # Copied, not mutated: the caller's payload is also what gets
            # parsed into Articles, and quietly adding a key to it would be a
            # surprising side effect of caching.
            payload = {**payload, PROVENANCE_KEY: provenance}
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass  # caching is an optimisation; failing to cache is not an error


# --- Deduplication -----------------------------------------------------------
# Syndication is the problem being solved here. One Reuters story reappears on
# a dozen sites under a near-identical headline. Counting those as a dozen
# independent sources would make a theme look far better evidenced than it is —
# which matters, because `confidence: high` is supposed to mean "multiple
# INDEPENDENT sources agree".


def _normalise_url(url: str) -> str:
    """Strip the parts of a URL that do not identify the article."""
    url = url.split("?", 1)[0].split("#", 1)[0]
    url = re.sub(r"^https?://(www\.)?", "", url.lower())
    return url.rstrip("/")


def _normalise_title(title: str) -> str:
    """Reduce a headline to comparable form: lowercase, no punctuation."""
    title = re.sub(r"[^\w\s]", " ", title.lower())
    return re.sub(r"\s+", " ", title).strip()


def _numbers_in(title: str) -> list[str]:
    return re.findall(r"\d+", title)


def _is_duplicate_title(a: str, b: str) -> bool:
    """Whether two normalised headlines describe the same story.

    Numbers are checked before similarity, because financial headlines are
    formulaic and differ in exactly the character that matters:

        "Tesla Q2 earnings beat"  vs  "Tesla Q3 earnings beat"     ~0.97 similar
        "Solar plant secures $695M" vs "Solar plant secures $234M" ~0.94 similar

    Those are different stories, and merging them would silently destroy
    evidence. Syndicated copies of one story carry the SAME numbers, so
    requiring the numbers to match costs nothing in the case dedup exists for.
    """
    if _numbers_in(a) != _numbers_in(b):
        return False
    return SequenceMatcher(None, a, b).ratio() >= TITLE_SIMILARITY_THRESHOLD


def deduplicate(articles: list[Article]) -> list[Article]:
    """Remove repeats, keeping the earliest publication of each story.

    Two passes. Exact URL matching catches the same link arriving from more than
    one query. Title similarity catches syndication, where the URLs differ but
    the story does not.

    The earliest article is kept because syndicated copies are published after
    the original, so the earliest is usually the primary source.
    """
    by_url: dict[str, Article] = {}
    for article in articles:
        key = _normalise_url(article.url)
        existing = by_url.get(key)
        if existing is None or article.published_at < existing.published_at:
            by_url[key] = article

    kept: list[Article] = []
    for article in sorted(by_url.values(), key=lambda a: a.published_at):
        title = _normalise_title(article.title)
        if any(_is_duplicate_title(title, _normalise_title(k.title)) for k in kept):
            continue
        kept.append(article)

    return kept


# --- Parsing -----------------------------------------------------------------


def _to_article(raw: dict) -> Article | None:
    """Convert one API record into an Article, or None if unusable.

    Returning None rather than raising is deliberate: one malformed record in a
    batch of thirty should cost us that record, not the whole search.
    """
    try:
        return Article(
            uuid=raw["uuid"],
            title=raw["title"],
            description=raw.get("description") or "",
            snippet=raw.get("snippet") or "",
            url=raw["url"],
            source=raw.get("source") or "unknown",
            published_at=datetime.fromisoformat(
                raw["published_at"].replace("Z", "+00:00")
            ),
            categories=raw.get("categories") or [],
        )
    except (KeyError, TypeError, ValueError):
        return None


# --- Public interface --------------------------------------------------------


def search_news(
    query: str,
    *,
    days_back: int | None = None,
    limit: int | None = None,
    use_cache: bool = True,
    asked_by: str | None = None,
) -> list[Article]:
    """Search recent news for one query.

    Args:
        query: Search terms. The provider supports +, |, -, and "quoted phrases".
        days_back: How far back to look. Defaults to the configured window.
        limit: Articles to return. The free tier caps this at 3.
        use_cache: Set False to force a live call.

    Returns:
        Articles, most relevant first. Empty if nothing matched.

    Raises:
        NewsAPIError: The provider was unreachable or refused the request.
    """
    settings = get_settings()

    if settings.news_api_key is None:
        raise NewsAPIError(
            "NEWS_API_KEY is not set. Add it to .env — see .env.example."
        )

    days = days_back if days_back is not None else settings.news_days_back
    params = {
        "api_token": settings.news_api_key.get_secret_value(),
        "search": query,
        "language": "en",
        "limit": limit if limit is not None else settings.news_articles_per_query,
        # Recency as a FILTER, relevance as the SORT. Without published_after
        # the API happily returns three-year-old articles.
        "published_after": (date.today() - timedelta(days=days)).isoformat(),
        "sort": "relevance_score",
    }

    path = _cache_path(params)
    payload = _read_cache(path, settings.news_cache_ttl_hours) if use_cache else None

    if payload is None:
        try:
            response = requests.get(
                API_URL,
                params=params,
                timeout=settings.llm_timeout_seconds,
                headers={"User-Agent": USER_AGENT},
            )
        except requests.RequestException as exc:
            raise NewsAPIError(f"Could not reach the news API: {exc}") from exc

        if response.status_code == 401:
            raise NewsAPIError("News API rejected the token. Check NEWS_API_KEY.")
        if response.status_code == 429:
            raise NewsAPIError(
                "News API rate limit reached (free tier allows 100 requests/day)."
            )
        if response.status_code != 200:
            raise NewsAPIError(
                f"News API returned HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise NewsAPIError("News API returned a non-JSON response.") from exc

        _write_cache(
            path,
            payload,
            provenance={
                # The API token is deliberately absent, for the same reason it
                # is excluded from the cache key: it identifies the caller, not
                # the query, and must never be written to disk.
                "query": query,
                "asked_by": asked_by,
                "days_back": days,
                "limit": params["limit"],
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    articles = [a for a in map(_to_article, payload.get("data", [])) if a is not None]
    return articles


def search_many(
    queries: list[str],
    *,
    days_back: int | None = None,
    limit: int | None = None,
    use_cache: bool = True,
    asked_by: str | None = None,
) -> tuple[list[Article], list[str]]:
    """Run several queries and return one deduplicated pool of articles.

    Several narrow queries beat one broad one here. The free tier returns only
    3 articles per request, and different phrasings surface different stories,
    so asking from several angles gives both more material and more variety at
    a cost of a few requests out of the daily 100.

    A query that fails does not abandon the others; partial results are more
    useful than none.

    Returns:
        (deduplicated articles, queries that actually succeeded)
    """
    collected: list[Article] = []
    succeeded: list[str] = []

    for query in queries:
        try:
            collected.extend(
                search_news(
                    query,
                    days_back=days_back,
                    limit=limit,
                    use_cache=use_cache,
                    asked_by=asked_by,
                )
            )
            succeeded.append(query)
        except NewsAPIError:
            continue

    return deduplicate(collected), succeeded
