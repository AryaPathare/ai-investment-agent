"""Central configuration for the investment research system.

Everything that depends on the outside world — API keys, model names, timeouts,
retry counts — is defined here in ONE place, and nowhere else in the codebase.

Why this file exists
--------------------
Previously each agent called ``load_dotenv()`` and built its own ``ChatGroq``
object at import time. That created three problems:

1. Importing an agent required a valid API key, so the code could not be
   imported by a test that never intended to call the model.
2. Every agent repeated the same setup, so changing the model or adding a
   timeout would mean editing eight files and hoping none were missed.
3. There was no timeout and no explicit retry policy, so a network stall could
   hang the whole workflow indefinitely.

Settings are loaded LAZILY (on first use, not on import), which is what makes
the rest of the codebase importable and testable without any credentials.
"""

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute path to the project root (the folder containing this file).
# Used so the .env file is found no matter which directory you run from — a
# relative "./.env" would break when running from inside tests/ or demos/.
PROJECT_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """All external configuration, validated at startup.

    Each field maps to an environment variable of the same name in upper case:
    ``groq_api_key`` reads ``GROQ_API_KEY``. Values come from the real
    environment first, then from the .env file.

    Fields with a default are optional. ``groq_api_key`` has no default, so if
    it is missing the app fails immediately with a clear message rather than
    dying later with a confusing error from deep inside a library.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Ignore unrecognised variables (LANGSMITH_*, FMP_API_KEY, ...) instead
        # of raising. They belong to other libraries or to agents not built yet.
        extra="ignore",
    )

    # --- Credentials --------------------------------------------------------

    # SecretStr hides the value in logs and tracebacks: printing this object
    # shows "**********" instead of your key. Call .get_secret_value() to read
    # the real string — which happens in exactly one place, get_llm() below.
    groq_api_key: SecretStr = Field(
        description="Groq API key. Get one free at https://console.groq.com/keys",
    )

    # --- Model behaviour ----------------------------------------------------

    groq_model: str = Field(
        default="openai/gpt-oss-20b",
        description="Groq model id used by all agents unless overridden.",
    )

    llm_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description=(
            "0.0 makes output as deterministic as possible. Correct for "
            "validation and classification work, where there is a right answer."
        ),
    )

    # ChatGroq ships with max_retries=2 but NO timeout at all, so a stalled
    # connection would block forever. Both are set explicitly here.
    llm_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description="Abort a single model call after this many seconds.",
    )

    llm_max_retries: int = Field(
        default=3,
        ge=0,
        description=(
            "Automatic retries on transient failures (rate limits, timeouts, "
            "5xx errors). Uses exponential backoff internally."
        ),
    )

    llm_max_tokens: int = Field(
        default=2048,
        gt=0,
        description=(
            "Maximum tokens in one model response. Both ends of this were "
            "hit while building Agent 2. Too low and structured output is "
            "truncated mid-JSON, which Groq reports as 'Failed to parse "
            "tool call arguments as JSON' - an error that never mentions "
            "length. Too high and it backfires differently: Groq counts "
            "max_tokens against the tokens-per-minute quota, so a value of "
            "8192 made every request, even a tiny one, cost 8192+ tokens "
            "against the free tier's 8000 TPM ceiling and fail with 413. "
            "2048 fits five themes with citations (~1000 tokens observed) "
            "while leaving room for the prompt inside the quota."
        ),
    )

    # --- Workflow limits ----------------------------------------------------

    max_clarification_attempts: int = Field(
        default=3,
        ge=1,
        description=(
            "How many times the profile agent may ask the user to clarify "
            "before giving up. Guarantees the clarification loop terminates "
            "even if the model never returns a clean profile."
        ),
    )

    # --- News search (Agent 2) ----------------------------------------------

    news_api_key: SecretStr | None = Field(
        default=None,
        description=(
            "TheNewsAPI token. Get one free at https://www.thenewsapi.com. "
            "Optional so the app still runs without Agent 2."
        ),
    )

    news_days_back: int = Field(
        default=14,
        ge=1,
        description=(
            "How far back to search. The API defaults to searching ALL history "
            "sorted by relevance, which returned 2023 articles in testing - "
            "useless for an agent about current events. Recency is a filter; "
            "relevance is the sort."
        ),
    )

    news_articles_per_query: int = Field(
        default=3,
        ge=1,
        le=100,
        description=(
            "Articles per request. The free tier caps this at 3, which is why "
            "we issue several narrow queries instead of one broad one."
        ),
    )

    news_cache_ttl_hours: float = Field(
        default=24.0,
        ge=0,
        description=(
            "How long a cached search stays fresh. Caching is what makes "
            "development affordable: the free tier allows 100 requests a day "
            "and re-running a test should not spend them. Set 0 to disable."
        ),
    )


    news_max_queries: int = Field(
        default=6,
        ge=1,
        description=(
            "Hard cap on searches per research run. A cost control: each query "
            "spends one of the free tier's 100 daily requests, so a model that "
            "returns twenty queries must not be allowed to run all of them."
        ),
    )

    research_max_themes: int = Field(
        default=5,
        ge=1,
        description=(
            "Maximum themes Agent 2 may return. Fewer is fine and zero is a "
            "legitimate answer; this only caps the top end."
        ),
    )

    # --- Company data (Agent 3) ----------------------------------------------

    fmp_api_key: SecretStr | None = Field(
        default=None,
        description=(
            "Financial Modeling Prep token, for US company fundamentals. Free "
            "at https://site.financialmodelingprep.com - 250 requests/day and "
            "US exchanges ONLY. Non-US companies are served by yfinance, which "
            "needs no key. Optional so the app runs without Agent 3."
        ),
    )

    company_cache_ttl_hours: float = Field(
        default=24.0,
        ge=0,
        description=(
            "How long cached company data stays fresh. One company costs four "
            "FMP calls against a 250/day cap, so roughly sixty companies daily; "
            "without caching a single afternoon of development exhausts it. "
            "Fundamentals change quarterly, so a day is comfortably fresh."
        ),
    )

    max_company_candidates: int = Field(
        default=8,
        ge=1,
        description=(
            "Maximum companies Agent 3 passes to the risk critic. Fewer is fine "
            "and zero is a legitimate answer; this only caps the top end."
        ),
    )

    # --- Observability ------------------------------------------------------
    # These are read directly from os.environ by the LangSmith library, not by
    # this class. They are declared here only so the app can REPORT whether
    # tracing is on; setting them in code would have no effect.

    langsmith_tracing: bool = Field(
        default=False,
        description=(
            "Whether LLM calls are traced to LangSmith. Set LANGSMITH_TRACING="
            "true in .env to enable."
        ),
    )

    langsmith_project: str = Field(
        default="default",
        description="LangSmith project name that traces are grouped under.",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the settings, loading and validating them on first call.

    ``@lru_cache`` means the work happens once per process and every later call
    returns the same object — a lazy singleton. Nothing runs at import time, so
    ``import config`` never needs an API key.
    """
    # pydantic-settings reads the .env file directly, but it does NOT copy the
    # values into os.environ. Some libraries — LangSmith tracing in particular —
    # read os.environ themselves, so it still gets populated once here.
    load_dotenv(PROJECT_ROOT / ".env")

    try:
        return Settings()
    except ValidationError as exc:
        raise RuntimeError(
            "Configuration is invalid or incomplete.\n\n"
            f"{exc}\n\n"
            f"Fix: copy .env.example to .env in {PROJECT_ROOT} and fill in the "
            "required values.\n"
            "    Copy-Item .env.example .env"
        ) from exc


@lru_cache(maxsize=None)
def get_llm(
    temperature: float | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
) -> ChatGroq:
    """Return a configured chat model, shared across the application.

    Args:
        temperature: Override the configured default. Useful later if one agent
            needs more variation than another.
        model: Override the configured model id, e.g. to run a stronger model
            for a harder agent.
        max_tokens: Override the response ceiling for this call. Size it to what
            the call actually needs: Groq charges max_tokens against the
            tokens-per-minute quota whether or not they are used, so one global
            value large enough for the biggest call makes every small call
            expensive. A pipeline of two calls at 4096 each exceeds the free
            tier's 8000 TPM on its own.

    Results are cached per unique argument combination, so agents asking for the
    same settings share one client instead of each opening its own.
    """
    settings = get_settings()

    return ChatGroq(
        model=model if model is not None else settings.groq_model,
        temperature=(
            temperature if temperature is not None else settings.llm_temperature
        ),
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        max_tokens=(
            max_tokens if max_tokens is not None else settings.llm_max_tokens
        ),
        api_key=settings.groq_api_key.get_secret_value(),
    )
