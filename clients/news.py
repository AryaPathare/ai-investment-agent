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
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import date, datetime, timedelta
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


def _write_cache(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
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


def _is_duplicate_title(a: str, b: str) -> bool:
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

        _write_cache(path, payload)

    articles = [a for a in map(_to_article, payload.get("data", [])) if a is not None]
    return articles


def search_many(
    queries: list[str],
    *,
    days_back: int | None = None,
    limit: int | None = None,
    use_cache: bool = True,
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
                    query, days_back=days_back, limit=limit, use_cache=use_cache
                )
            )
            succeeded.append(query)
        except NewsAPIError:
            continue

    return deduplicate(collected), succeeded
