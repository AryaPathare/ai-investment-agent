"""Company lookup and fundamentals, wrapped behind our own interface.

The rest of the codebase calls ``resolve_company()`` and ``fetch_fundamentals()``
and gets back our own types. It never sees FMP's JSON, yfinance's DataFrames, or
the differences between them.

Two providers, split by what each does well
-------------------------------------------
**Resolution uses yfinance**, because its search is measurably better and costs
nothing against a quota:

    "SMIC"    FMP -> COSMICUSD, a cryptocurrency matched on "co-SMIC"
              yf  -> 0981.HK, correct, first result
    "Nvidia"  FMP -> NVDA.NE (CBOE Canada) first, NVDA second
              yf  -> NVDA first

yfinance also returns ``quoteType``, so rejecting ETFs, funds and tokenised
crypto is one field rather than an extra profile call.

**Fundamentals are routed by market.** FMP's free tier covers US exchanges only
and returns 402 for anything else - and misleadingly, its SEARCH happily returns
foreign symbols, so the failure appears only when you ask for data. US tickers
therefore go to FMP, everything else to yfinance.

Units are normalised here
-------------------------
The providers disagree on the same quantity. For AMD, FMP reports
``debtToEquityRatioTTM`` as 0.0636 while yfinance reports ``debtToEquity`` as
6.3610 - exactly 100x apart, because yfinance uses a percentage. Both are
converted to a ratio at this boundary, so ranking code never has to know where a
company's numbers came from.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import warnings
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path

import requests

from config import PROJECT_ROOT, get_settings
from models.companies import (
    ComparableMetrics,
    CurrencyAmounts,
    DataSource,
    Fundamentals,
    MarketPrice,
)

warnings.filterwarnings("ignore", module="yfinance")

FMP_BASE = "https://financialmodelingprep.com/stable"
CACHE_DIR = PROJECT_ROOT / ".cache" / "companies"

# yfinance exchange codes for US venues. A company listed both in the US and
# abroad should be analysed on its US listing, since that is where the user
# would actually buy it and where FMP's better-quality data applies.
US_EXCHANGES = {"NMS", "NYQ", "NGM", "NCM", "ASE", "PCX", "BTS", "NAS", "NYS"}

# Anything that is not an operating company. Tokenised "stocks", leveraged ETFs
# and closed-end funds all surface when searching well-known company names -
# "SpaceX" returns four ETFs and a cryptocurrency before anything else.
NON_EQUITY_TYPES = {
    "ETF", "MUTUALFUND", "CRYPTOCURRENCY", "CURRENCY",
    "INDEX", "FUTURE", "OPTION",
}

# Share of the searched name's words that must appear in the result's name.
# Guards against substring coincidences: "SMIC" sits inside "Cosmic Coin USD",
# which FMP's search returned as its top hit for SMIC.
NAME_MATCH_THRESHOLD = 0.6

# How many scored candidates to verify before giving up on a name.
MAX_VERIFY_ATTEMPTS = 3


class CompanyDataError(RuntimeError):
    """A provider could not be reached or refused the request."""


@dataclass(frozen=True)
class ResolvedCompany:
    """A company name successfully matched to a real, listed security."""

    ticker: str
    name: str
    exchange: str
    currency: str
    is_us: bool
    # Populated from the same ticker record that verification already fetches,
    # so these cost nothing extra. They matter for exposure judgement: knowing
    # that Northern Trust is in "Banks - Regional" is what separates a genuine
    # link to a banking theme from a passing mention in a semiconductor story.
    industry: str | None = None
    sector: str | None = None

    @property
    def source(self) -> DataSource:
        """Which provider will supply this company's fundamentals."""
        return "fmp" if self.is_us else "yfinance"


# --- Caching -----------------------------------------------------------------
# FMP's free tier allows 250 requests a day and one company costs four of them,
# so roughly sixty companies daily. Without caching, a single afternoon of
# development would exhaust it.


def _cache_path(kind: str, key: str) -> Path:
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{kind}-{digest}.json"


def _read_cache(path: Path, ttl_hours: float) -> dict | list | None:
    if ttl_hours <= 0 or not path.exists():
        return None
    if (time.time() - path.stat().st_mtime) / 3600 > ttl_hours:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None  # a corrupt entry must never break a real run


def _write_cache(path: Path, payload) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, default=str), encoding="utf-8")
    except OSError:
        pass  # caching is an optimisation, not a requirement


# --- Name matching -----------------------------------------------------------

# Words that carry no identifying information and would inflate a match score.
_NOISE_WORDS = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd",
    "limited", "plc", "sa", "nv", "ag", "group", "holdings", "holding",
    "the", "and", "technologies", "technology",
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _NOISE_WORDS}


def _name_match_score(query: str, candidate: str) -> float:
    """Fraction of the query's meaningful words present in the candidate name.

    Word-level rather than substring, which is the whole point: "smic" is a
    substring of "cosmic" but not one of its words, so the cryptocurrency that
    FMP returned for "SMIC" scores zero here instead of matching.
    """
    wanted = _tokens(query)
    if not wanted:
        return 0.0
    have = _tokens(candidate)
    hits = sum(1 for w in wanted if w in have)
    return hits / len(wanted)



# Fund and ETF detection by NAME, as a second line of defence.
#
# quoteType alone is not trustworthy. Yahoo reported SPCF ("ProShares Ultra
# SpaceX") as quoteType=ETF with legalType="Exchange Traded Fund" in one run and
# quoteType=EQUITY with legalType=None an hour later - same ticker, same code.
# Provider metadata can change under you; marketing names effectively do not.
#
# Only high-signal markers are listed. Deliberately absent are generic words
# like "trust", "fund" and "shares", which appear in the names of real operating
# companies - Northern Trust being the obvious example - and would cause false
# rejections.
_FUND_SPONSORS = {
    "proshares", "direxion", "ishares", "vanguard", "spdr", "invesco",
    "tradr", "vegashares", "wisdomtree", "roundhill", "defiance",
    "graniteshares", "simplify", "yieldmax", "amplify", "leverageshares",
}
_FUND_MARKERS = {"etf", "etn", "2x", "3x", "inverse", "leveraged"}


def _looks_like_a_fund(name: str) -> bool:
    """Whether a security's name marks it as a fund rather than a company."""
    words = _tokens(name) | set(re.findall(r"[a-z0-9]+", name.lower()))
    if words & _FUND_SPONSORS:
        return True
    if words & _FUND_MARKERS:
        return True
    # "Daily ... Bull/Bear" is the standard leveraged-ETF naming pattern and
    # does not occur in operating company names.
    return "daily" in words and bool(words & {"bull", "bear"})



def _symbol_matches_query(ticker: str, query: str) -> bool:
    """Whether the query is really the company's ticker or a common short name.

    Word matching alone rejects two very common cases, both found on a live run:

        "AMD"    -> "Advanced Micro Devices, Inc."   0.00 word match
        "Google" -> "Alphabet Inc."                  0.00 word match

    Neither shares a word with its legal name, yet both are correct. What they
    do share is the SYMBOL: the query is exactly "AMD", and "GOOGLE" starts with
    "GOOG". That is a strong enough signal to accept on its own.

    The base symbol is used, so a foreign listing like "NVDA.NE" still compares
    as "NVDA". A three-character minimum keeps one- and two-letter tickers from
    matching almost anything.
    """
    base = ticker.split(".")[0].upper()
    wanted = re.sub(r"[^A-Z0-9]", "", query.upper())

    if not base or not wanted:
        return False
    if base == wanted:
        return True
    return len(base) >= 3 and wanted.startswith(base)


# --- Resolution --------------------------------------------------------------


def _without_noise_words(name: str) -> str | None:
    """``name`` with its legal-form words removed, or None if that changes nothing.

    The provider's search matches the name as typed, so a legal suffix that a
    news article always writes can stop a real company from being found at all:
    "Waaree Energies Ltd." returned NOTHING while "Waaree Energies" returned the
    NSE and BSE listings of India's largest solar manufacturer. It was recorded
    as ``no_ticker_found`` — the label for a name that is not a company — and
    dropped out of a renewable-energy brief that had room for it.

    Reuses ``_NOISE_WORDS``, which already declares these words carry no
    identifying information. That knowledge was only ever applied to SCORING the
    candidates that came back, never to asking for them.
    """
    # Only TRAILING legal form is removed. "Energy Technology Ltd." loses the
    # "Ltd."; "Technology Select Sector" keeps every word, because a noise word
    # in the middle of a name is usually part of it.
    words = name.split()
    while words and not _tokens(words[-1]):
        words.pop()

    # "First Solar, Inc." leaves a dangling comma once "Inc." goes.
    stripped = " ".join(words).strip().rstrip(",;-").strip()

    # No retry when nothing was dropped, or when the name was ALL legal form and
    # stripping leaves nothing to search for.
    if not stripped or stripped == name.strip():
        return None
    return stripped


def _search_one(name: str, use_cache: bool) -> list[dict]:
    """Raw search hits from yfinance for exactly this string, cached."""
    path = _cache_path("search", name.lower())
    settings = get_settings()

    cached = _read_cache(path, settings.company_cache_ttl_hours) if use_cache else None
    if cached is not None:
        return cached

    import yfinance as yf

    try:
        quotes = yf.Search(name, max_results=10).quotes or []
    except Exception as exc:  # noqa: BLE001 - any provider failure is one failure
        raise CompanyDataError(f"Company search failed for {name!r}: {exc}") from exc

    _write_cache(path, quotes)
    return quotes


def _search_raw(name: str, use_cache: bool) -> list[dict]:
    """Search hits for a company name, retrying once without its legal form.

    ONLY retries on an empty result, so a name that already resolves keeps
    whatever it resolved to and no existing behaviour moves. Every caller
    benefits, including the drop-reason check, which would otherwise report
    no_ticker_found for a company this function can now find.
    """
    hits = _search_one(name, use_cache)
    if hits:
        return hits

    stripped = _without_noise_words(name)
    if stripped is None:
        return hits
    return _search_one(stripped, use_cache)


def resolve_company(name: str, *, use_cache: bool = True) -> ResolvedCompany | None:
    """Match a company name to a real listed security, or return None.

    Returns None rather than raising when the name simply is not a listed
    company: private firms (SpaceX), subsidiaries (Recurrent Energy, a Canadian
    Solar subsidiary) and misreadings all land here, and each is an ordinary
    outcome rather than an error.

    Candidates are SCORED, never taken in order. Search engines rank by their own
    relevance, which is not ours: searching "Pfizer" returns the German listing
    first, an Argentine one second, and the NYSE listing fourth.
    """
    hits = _search_raw(name, use_cache)

    scored: list[tuple[float, ResolvedCompany]] = []
    for hit in hits:
        if (hit.get("quoteType") or "").upper() in NON_EQUITY_TYPES:
            continue

        ticker = hit.get("symbol")
        display = hit.get("shortname") or hit.get("longname") or ""
        if not ticker:
            continue

        if _looks_like_a_fund(display):
            continue

        match = _name_match_score(name, display)
        symbol_match = _symbol_matches_query(ticker, name)

        # Accept on EITHER signal. A legal name often shares no words with the
        # name people actually use, and the ticker is the other half of the
        # company's identity.
        if match < NAME_MATCH_THRESHOLD and not symbol_match:
            continue

        exchange = (hit.get("exchange") or "").upper()
        is_us = exchange in US_EXCHANGES

        # A US listing breaks ties in its favour: that is where a US-based user
        # would actually buy, and where the better data source applies.
        confidence = max(match, 1.0 if symbol_match else 0.0)

        # Exact name equality breaks ties, and ties are common. Searching "SMIC"
        # returns both 0981.HK, whose name IS "SMIC", and HSMD.SI, "h SMIC HK
        # SDR 5to1" - a Singapore depositary receipt. Both contain every word of
        # the query, so both scored 1.0, and the winner was decided by whatever
        # order the search happened to return that day. Preferring the exact
        # match picks the primary listing deterministically.
        exact_name = _tokens(name) == _tokens(display)

        score = (
            confidence
            + (0.5 if is_us else 0.0)
            + (0.3 if exact_name else 0.0)
        )
        scored.append((
            score,
            ResolvedCompany(
                ticker=ticker,
                name=display,
                exchange=exchange,
                currency="",  # filled in when fundamentals are fetched
                is_us=is_us,
            ),
        ))

    if not scored:
        return None

    # VERIFY the winner rather than trusting the search result's own metadata,
    # which is wrong often enough to matter. Searching "SpaceX" returns SPCF
    # labelled quoteType=EQUITY, but the ticker itself reports quoteType=ETF and
    # legalType="Exchange Traded Fund" - it is ProShares Ultra SpaceX, a
    # leveraged fund, not a company. Analysing an ETF's "fundamentals" would
    # produce numbers that look real and mean nothing.
    #
    # Candidates are checked best-first, so a rejected top hit falls through to
    # the next rather than losing the company entirely.
    for _, candidate in sorted(scored, key=lambda pair: -pair[0])[:MAX_VERIFY_ATTEMPTS]:
        info = _verified_info(candidate.ticker, use_cache)
        if info is None:
            continue
        return replace(
            candidate,
            industry=info.get("industry"),
            sector=info.get("sector"),
        )

    return None


def _verified_info(ticker: str, use_cache: bool) -> dict | None:
    """Return the ticker's record if it is a real company, else None."""
    try:
        info = _ticker_info(ticker, use_cache)
    except CompanyDataError:
        return None

    quote_type = (info.get("quoteType") or "").upper()
    if quote_type and quote_type != "EQUITY":
        return None
    if info.get("legalType"):
        # Populated for funds and trusts; None for operating companies.
        return None

    # Independent of the metadata, because the metadata proved unreliable.
    display = info.get("shortName") or info.get("longName") or ""
    return None if _looks_like_a_fund(display) else info


# --- Fundamentals: FMP (US) --------------------------------------------------


def _fmp_get(path: str, use_cache: bool, **params) -> list[dict]:
    settings = get_settings()
    if settings.fmp_api_key is None:
        raise CompanyDataError("FMP_API_KEY is not set. Add it to .env.")

    cache_key = f"{path}:{json.dumps(params, sort_keys=True)}"
    cache_path = _cache_path("fmp", cache_key)

    cached = _read_cache(cache_path, settings.company_cache_ttl_hours) if use_cache else None
    if cached is not None:
        return cached

    try:
        response = requests.get(
            f"{FMP_BASE}/{path}",
            params={**params, "apikey": settings.fmp_api_key.get_secret_value()},
            timeout=settings.llm_timeout_seconds,
        )
    except requests.RequestException as exc:
        raise CompanyDataError(f"Could not reach FMP: {exc}") from exc

    if response.status_code == 401:
        raise CompanyDataError("FMP rejected the key. Check FMP_API_KEY.")
    if response.status_code == 402:
        # The free tier is US-only, and this is how it says so. It should never
        # be reached, since non-US symbols are routed to yfinance.
        raise CompanyDataError(
            f"FMP free tier does not cover this symbol ({params.get('symbol')}). "
            "Non-US companies should be routed to yfinance."
        )
    if response.status_code == 429:
        raise CompanyDataError("FMP rate limit reached (free tier is 250/day).")
    if response.status_code != 200:
        raise CompanyDataError(f"FMP returned HTTP {response.status_code}.")

    try:
        payload = response.json()
    except ValueError as exc:
        raise CompanyDataError("FMP returned a non-JSON response.") from exc

    rows = payload if isinstance(payload, list) else []
    _write_cache(cache_path, rows)
    return rows


def _first(rows: list[dict]) -> dict:
    return rows[0] if rows else {}


def _parse_date(value) -> date | None:
    try:
        return datetime.fromisoformat(str(value)).date()
    except (TypeError, ValueError):
        return None


def _fetch_fmp(ticker: str, use_cache: bool) -> Fundamentals:
    """Four calls: ratios, growth, cash flow, income."""
    ratios = _first(_fmp_get("ratios-ttm", use_cache, symbol=ticker))
    growth = _first(_fmp_get("financial-growth", use_cache, symbol=ticker, limit=1))
    cash = _first(_fmp_get("cash-flow-statement", use_cache, symbol=ticker, limit=1))
    income = _first(_fmp_get("income-statement", use_cache, symbol=ticker, limit=1))

    return Fundamentals(
        comparable=ComparableMetrics(
            revenue_growth=growth.get("revenueGrowth"),
            gross_margin=_sane_margin(_unreported_if_zero(ratios.get("grossProfitMarginTTM"))),
            operating_margin=_sane_margin(_unreported_if_zero(ratios.get("operatingProfitMarginTTM"))),
            # FMP already reports this as a ratio, unlike yfinance.
            debt_to_equity=ratios.get("debtToEquityRatioTTM"),
        ),
        amounts=CurrencyAmounts(
            currency=cash.get("reportedCurrency") or income.get("reportedCurrency") or "USD",
            net_income=income.get("netIncome"),
            free_cash_flow=cash.get("freeCashFlow"),
        ),
        source="fmp",
        as_of=_parse_date(cash.get("date") or income.get("date")),
    )


# --- Fundamentals: yfinance (everything else) --------------------------------


def _ticker_info(ticker: str, use_cache: bool) -> dict:
    """yfinance's record for one ticker, cached.

    Shared by resolution (to verify a candidate is an operating company) and by
    the non-US fundamentals path, so a verified company costs no extra call.
    """
    path = _cache_path("yfinfo", ticker)
    settings = get_settings()

    info = _read_cache(path, settings.company_cache_ttl_hours) if use_cache else None
    if info is not None:
        return info

    import yfinance as yf

    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as exc:  # noqa: BLE001
        raise CompanyDataError(f"yfinance failed for {ticker}: {exc}") from exc

    _write_cache(path, info)
    return info


def _unreported_if_zero(value: float | None) -> float | None:
    """Treat an exact 0.0 margin as NOT REPORTED rather than as a real figure.

    Both providers return a literal 0.0 where a margin simply does not exist for
    the business. Banks have no cost of goods, so gross margin is meaningless for
    them; pre-revenue biotechs have no revenue to take a margin on. Accepted at
    face value, that placeholder scores at the very bottom of the ramp, so the
    ranking reports "terrible" where the truth is "not applicable".

    That inverts the rule the scoring code is built on - a missing metric is
    unknown, not bad - so the correction belongs here, at the provider boundary,
    rather than leaving every consumer to guess.

    Observed in IDBI Bank, CervoMed and ProMIS Neurosciences: three companies
    across two unrelated sectors, so this is a provider convention, not a quirk
    of one sector. A margin of EXACTLY 0.0 to full float precision is a
    placeholder; a real business landing precisely on break-even does not occur.
    """
    return None if value == 0.0 else value


def _sane_margin(value: float | None) -> float | None:
    """Reject a margin above 1.0, which is arithmetically impossible.

    A margin is profit divided by revenue, so it cannot exceed 1.0 - that would
    mean earning more than everything you sold. yfinance reported PowerBank's
    operating margin as 168.38, i.e. 16,838%.

    It went undetected through two agents because the ranking CLIPS: the ramp
    maps anything above 0.40 to a perfect 1.0, so a garbage number and an
    excellent one become the same score. Agent 4's rules only look for NEGATIVE
    margins, so they were silent too. It surfaced only when Agent 5 wrote
    "operating_margin falls below 150" into a brief and a human read it.

    Third instance of the same lesson: a metric that clips cannot also serve as
    its own data-quality alarm. The check has to sit upstream of the clipping.

    Only the upper bound is rejected. A deeply NEGATIVE margin is real - a
    pre-revenue biotech legitimately reports -94 - and Agent 3's screen already
    treats that as disqualifying.
    """
    return None if value is not None and value > 1.0 else value


def _market_price(info: dict) -> MarketPrice | None:
    """The share price from a yfinance ``info`` payload, if it carries one.

    Three fields tried in order. Measured across the 48 yfinance responses on
    disk: ``regularMarketPrice`` and ``previousClose`` appear in all 48,
    ``currentPrice`` in 47. Preferring the freshest and falling back means the
    one company missing it still gets a price rather than a blank.

    The currency is ``currency``, NOT ``financialCurrency``. Those are different
    fields for different things - what the share trades in versus what the
    accounts are reported in - and the file already records that they disagree
    often enough to matter. A price labelled with the statement currency would
    be a wrong label on a right number, which is the harder kind to notice.
    """
    for field in ("currentPrice", "regularMarketPrice", "previousClose"):
        amount = info.get(field)
        # A price of 0 is not a price, and MarketPrice rejects it anyway.
        if amount is None or amount <= 0:
            continue
        currency = info.get("currency")
        if not currency:
            return None
        return MarketPrice(
            amount=amount,
            currency=currency,
            as_of=datetime.now(timezone.utc),
        )
    return None


def _fetch_yfinance(ticker: str, use_cache: bool) -> Fundamentals:
    """One call. ``info`` carries every metric we need."""
    info = _ticker_info(ticker, use_cache)

    # THE UNIT FIX. yfinance reports debtToEquity as a percentage; FMP reports
    # it as a ratio. Verified against AMD's balance sheet: yfinance says 6.36
    # where debt/equity is genuinely 0.0611. Left unconverted, every non-US
    # company would screen as catastrophically leveraged next to a US one.
    raw_de = info.get("debtToEquity")
    debt_to_equity = raw_de / 100 if raw_de is not None else None

    return Fundamentals(
        comparable=ComparableMetrics(
            revenue_growth=info.get("revenueGrowth"),
            gross_margin=_sane_margin(_unreported_if_zero(info.get("grossMargins"))),
            operating_margin=_sane_margin(_unreported_if_zero(info.get("operatingMargins"))),
            debt_to_equity=debt_to_equity,
        ),
        price=_market_price(info),
        amounts=CurrencyAmounts(
            # THE CURRENCY FIX. yfinance carries two currencies: "currency" is
            # what the SHARE trades in, "financialCurrency" is what the
            # STATEMENTS are reported in. The amounts below are statement
            # figures, so they must be labelled with the latter. SK hynix's ADR
            # trades in USD while it reports in KRW, so the quote currency
            # labelled 162 trillion won as dollars. FMP's path already uses
            # reportedCurrency, so this makes the field mean one thing.
            currency=(
                info.get("financialCurrency")
                or info.get("currency")
                or "UNKNOWN"
            ),
            net_income=info.get("netIncomeToCommon"),
            free_cash_flow=info.get("freeCashflow"),
        ),
        source="yfinance",
        as_of=None,
    )


def _with_price(fundamentals: Fundamentals, ticker: str, use_cache: bool) -> Fundamentals:
    """Fill in a share price for fundamentals that arrived without one.

    FMP's four calls - ratios, growth, cash flow, income - carry no market
    price, and a fifth endpoint would spend a request against a 250-a-day budget
    for a number yfinance already returns inside a payload this file fetches
    anyway. So the fundamentals come from FMP and the price from yfinance.

    That mixes sources within one object, which is worth being explicit about:
    it is fine BECAUSE they are different kinds of measurement. The statement
    figures cover a reported period and are compared between companies; a price
    is a quote from a moment and is only ever displayed. They were never going
    to agree on a timestamp whichever provider supplied them.

    A failure here is not an error. The company keeps its fundamentals and the
    brief simply shows no price, which is the same outcome as a provider that
    reports none.
    """
    if fundamentals.price is not None:
        return fundamentals

    try:
        info = _ticker_info(ticker, use_cache)
    except CompanyDataError:
        return fundamentals

    price = _market_price(info)
    if price is None:
        return fundamentals
    return fundamentals.model_copy(update={"price": price})


# --- Public interface --------------------------------------------------------


def fetch_fundamentals(
    company: ResolvedCompany,
    *,
    use_cache: bool = True,
) -> Fundamentals:
    """Fetch fundamentals from whichever provider covers this company.

    Raises:
        CompanyDataError: The provider was unreachable or refused the request.
    """
    if not company.is_us:
        return _fetch_yfinance(company.ticker, use_cache)

    try:
        return _with_price(_fetch_fmp(company.ticker, use_cache),
                           company.ticker, use_cache)
    except CompanyDataError:
        # FMP's free tier does not cover every US symbol - not merely every
        # non-US one. Verified on live calls: AMD, NVDA, MSFT, INTC and PFE
        # return data, while SNPS and MRVL, both major Nasdaq companies, return
        # 402. The covered set is arbitrary from our side, so a US ticker
        # failing at FMP is expected rather than exceptional.
        #
        # yfinance covers US listings too, so falling back keeps the company
        # rather than dropping a real candidate over a provider's pricing tier.
        # Units differ between the two providers and are normalised in
        # _fetch_yfinance, so the fallback is safe to rank alongside FMP data.
        return _fetch_yfinance(company.ticker, use_cache)


def resolve_and_fetch(
    name: str,
    *,
    use_cache: bool = True,
) -> tuple[ResolvedCompany, Fundamentals] | None:
    """Resolve a name and fetch its fundamentals in one step.

    Returns None when the name is not a listed company. Raises only when a
    provider genuinely misbehaves, so callers can distinguish "this company is
    not investable" from "the data source is down".
    """
    company = resolve_company(name, use_cache=use_cache)
    if company is None:
        return None

    fundamentals = fetch_fundamentals(company, use_cache=use_cache)

    # The currency is only known once the numbers arrive.
    company = replace(company, currency=fundamentals.amounts.currency)
    return company, fundamentals
