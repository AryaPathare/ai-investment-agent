"""Tests for the company client: resolution, provider routing, unit normalisation.

Every one of the three resolution bugs found on live runs is a regression test
here. They were all silent failures - the pipeline produced plausible candidates
while quietly discarding real companies - so nothing else would catch them
coming back.
"""

import pytest
import requests

from clients import companies as C
from clients.companies import (
    CompanyDataError,
    ResolvedCompany,
    _looks_like_a_fund,
    _name_match_score,
    _symbol_matches_query,
    fetch_fundamentals,
    resolve_company,
)


def hit(symbol="AMD", name="Advanced Micro Devices, Inc.", exchange="NMS",
        quote_type="EQUITY"):
    return {"symbol": symbol, "shortname": name, "exchange": exchange,
            "quoteType": quote_type}


@pytest.fixture
def fake_search(monkeypatch):
    """Control what the provider search returns."""
    def _install(hits):
        monkeypatch.setattr(C, "_search_raw", lambda name, use_cache: hits)
    return _install


@pytest.fixture
def fake_info(monkeypatch):
    """Control the per-ticker record used for verification and yfinance data."""
    def _install(records):
        def fake(ticker, use_cache):
            if ticker not in records:
                raise CompanyDataError(f"no record for {ticker}")
            return records[ticker]
        monkeypatch.setattr(C, "_ticker_info", fake)
    return _install


EQUITY_RECORD = {"quoteType": "EQUITY", "legalType": None,
                 "shortName": "Advanced Micro Devices, Inc.",
                 "industry": "Semiconductors", "sector": "Technology"}


# --- Name matching -----------------------------------------------------------


def test_word_matching_rejects_substring_coincidences():
    """"smic" is inside "cosmic" but is not one of its words. This is what
    stopped a cryptocurrency being returned for SMIC."""
    assert _name_match_score("SMIC", "Cosmic Coin USD") == 0.0


def test_word_matching_accepts_a_real_name():
    assert _name_match_score("Nvidia", "NVIDIA Corporation") == 1.0


def test_corporate_suffixes_do_not_inflate_a_match():
    assert _name_match_score("Waaree Energies", "Waaree Energies Limited") == 1.0


# --- Symbol matching (regression: bug 1) -------------------------------------


@pytest.mark.parametrize(
    "query,ticker",
    [("AMD", "AMD"), ("amd", "AMD"), ("Google", "GOOG"), ("Meta", "META"),
     ("NVDA", "NVDA.NE")],
)
def test_a_company_is_recognised_by_its_symbol(query, ticker):
    """REGRESSION: "AMD" shares no word with "Advanced Micro Devices, Inc." and
    "Google" shares none with "Alphabet Inc.". Both were silently dropped."""
    assert _symbol_matches_query(ticker, query)


@pytest.mark.parametrize(
    "query,ticker",
    [("SpaceX", "SPCX"), ("Pfizer", "PFE"), ("Apple", "AAPL"), ("X", "XOM")],
)
def test_unrelated_symbols_do_not_match(query, ticker):
    assert not _symbol_matches_query(ticker, query)


def test_short_tickers_need_an_exact_match():
    """Without a length floor, a two-letter ticker would match almost anything."""
    assert not _symbol_matches_query("GO", "Google")
    assert _symbol_matches_query("GO", "GO")


# --- Fund detection ----------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["ProShares Ultra SpaceX", "Tradr 2X Short SpaceX Daily ETF",
     "Direxion Daily SpaceX Bear 2X Shares", "iShares Semiconductor ETF"],
)
def test_funds_are_detected_by_name(name):
    assert _looks_like_a_fund(name)


@pytest.mark.parametrize(
    "name",
    ["Northern Trust Corporation", "Ultra Clean Holdings", "NVIDIA Corporation",
     "SMIC", "Franklin Electric Co."],
)
def test_real_companies_are_not_mistaken_for_funds(name):
    """A filter that rejects real companies is worse than the leak it fixes."""
    assert not _looks_like_a_fund(name)


def test_a_fund_is_rejected_even_when_metadata_says_equity(fake_search, fake_info):
    """REGRESSION: Yahoo reported SPCF as quoteType=ETF one hour and
    quoteType=EQUITY the next. Metadata alone is not trustworthy."""
    fake_search([hit(symbol="SPCF", name="ProShares Ultra SpaceX", exchange="PCX")])
    fake_info({"SPCF": {"quoteType": "EQUITY", "legalType": None,
                        "shortName": "ProShares Ultra SpaceX"}})
    assert resolve_company("SpaceX") is None


# --- Resolution scoring ------------------------------------------------------


def test_a_us_listing_is_preferred_over_a_foreign_one(fake_search, fake_info):
    """Searching "Pfizer" returns Germany first and NYSE fourth."""
    fake_search([
        hit(symbol="PFE.DE", name="Pfizer Inc.", exchange="GER"),
        hit(symbol="PFE.BA", name="Pfizer Inc.", exchange="BUE"),
        hit(symbol="PFE", name="Pfizer Inc.", exchange="NYQ"),
    ])
    fake_info({t: {**EQUITY_RECORD, "shortName": "Pfizer Inc."}
               for t in ("PFE.DE", "PFE.BA", "PFE")})
    assert resolve_company("Pfizer").ticker == "PFE"


def test_exact_name_equality_breaks_ties(fake_search, fake_info):
    """REGRESSION: "SMIC" matched both 0981.HK ("SMIC") and HSMD.SI ("h SMIC HK
    SDR 5to1") perfectly, so the winner depended on search order, which changed
    between runs. Nondeterminism that yields a plausible answer is the worst
    kind - it does not look like a bug."""
    fake_search([
        hit(symbol="HSMD.SI", name="h SMIC HK SDR 5to1", exchange="SES"),
        hit(symbol="0981.HK", name="SMIC", exchange="HKG"),
    ])
    fake_info({"HSMD.SI": {**EQUITY_RECORD, "shortName": "h SMIC HK SDR 5to1"},
               "0981.HK": {**EQUITY_RECORD, "shortName": "SMIC"}})
    assert resolve_company("SMIC").ticker == "0981.HK"


def test_non_equities_are_skipped(fake_search, fake_info):
    fake_search([
        hit(symbol="EURAMD=X", name="EUR/AMD", exchange="CCY", quote_type="CURRENCY"),
        hit(symbol="AMDCOIN", name="AMD Coin", quote_type="CRYPTOCURRENCY"),
        hit(symbol="AMD", exchange="NMS"),
    ])
    fake_info({"AMD": EQUITY_RECORD})
    assert resolve_company("AMD").ticker == "AMD"


def test_a_rejected_top_hit_falls_through_to_the_next(fake_search, fake_info):
    """Losing the top candidate must not lose the company."""
    fake_search([
        hit(symbol="AMDX", name="Amd Ultra Fund ETF", exchange="NMS"),
        hit(symbol="AMD", exchange="NMS"),
    ])
    fake_info({"AMD": EQUITY_RECORD})
    assert resolve_company("AMD").ticker == "AMD"


def test_nothing_matching_resolves_to_none(fake_search):
    fake_search([])
    assert resolve_company("Zzzqqq Nonexistent Corp") is None


def test_resolution_carries_industry_and_sector(fake_search, fake_info):
    """Exposure judgement needs the industry, and it costs nothing here."""
    fake_search([hit()])
    fake_info({"AMD": EQUITY_RECORD})
    resolved = resolve_company("AMD")
    assert resolved.industry == "Semiconductors"
    assert resolved.sector == "Technology"


# --- Provider routing and units ----------------------------------------------


def us_company(ticker="AMD"):
    return ResolvedCompany(ticker=ticker, name="X", exchange="NMS",
                           currency="", is_us=True)


def foreign_company(ticker="0981.HK"):
    return ResolvedCompany(ticker=ticker, name="X", exchange="HKG",
                           currency="", is_us=False)


def test_non_us_companies_go_to_yfinance(monkeypatch, fake_info):
    monkeypatch.setattr(C, "_fmp_get", lambda *a, **k: pytest.fail("FMP must not be called"))
    fake_info({"0981.HK": {"debtToEquity": 37.0, "revenueGrowth": 0.36,
                           "grossMargins": 0.22, "operatingMargins": 0.18,
                           "currency": "HKD"}})
    assert fetch_fundamentals(foreign_company()).source == "yfinance"


def test_yfinance_percentages_are_normalised_to_ratios(fake_info):
    """REGRESSION: yfinance reports debtToEquity as a percentage and FMP as a
    ratio - exactly 100x apart. Unconverted, every yfinance-sourced company
    would screen as catastrophically leveraged beside an FMP one."""
    fake_info({"0981.HK": {"debtToEquity": 37.0, "currency": "HKD"}})
    got = fetch_fundamentals(foreign_company())
    assert got.comparable.debt_to_equity == pytest.approx(0.37)


def test_a_zero_margin_is_treated_as_unreported_not_as_terrible(fake_info):
    """REGRESSION: both providers return a literal 0.0 where a margin does not
    apply - banks have no cost of goods, pre-revenue biotechs have no revenue.
    Taken at face value it scores at the bottom of the ramp, so the ranking said
    "terrible" where the truth was "not applicable". Observed in IDBI Bank,
    CervoMed and ProMIS Neurosciences."""
    fake_info({"0981.HK": {"grossMargins": 0.0, "operatingMargins": 0.0,
                           "revenueGrowth": 0.1, "currency": "HKD"}})
    got = fetch_fundamentals(foreign_company()).comparable
    assert got.gross_margin is None
    assert got.operating_margin is None
    assert got.revenue_growth == pytest.approx(0.1)


def test_a_real_margin_of_zero_point_something_survives(fake_info):
    """Only an EXACT 0.0 is a placeholder. Real margins must pass through."""
    fake_info({"0981.HK": {"grossMargins": 0.01, "operatingMargins": -0.5,
                           "currency": "HKD"}})
    got = fetch_fundamentals(foreign_company()).comparable
    assert got.gross_margin == pytest.approx(0.01)
    assert got.operating_margin == pytest.approx(-0.5)


def test_a_missing_leverage_figure_stays_none(fake_info):
    fake_info({"0981.HK": {"currency": "HKD"}})
    assert fetch_fundamentals(foreign_company()).comparable.debt_to_equity is None


def test_amounts_are_labelled_with_the_reporting_currency(fake_info):
    """REGRESSION: yfinance carries two currencies. "currency" is what the share
    trades in; "financialCurrency" is what the statements are reported in.
    net_income and free_cash_flow are statement figures, so labelling them with
    the quote currency called SK hynix's 162 trillion won 162 trillion dollars.
    FMP's path already reports the statement currency - both must agree."""
    fake_info({"000660.KS": {"currency": "USD", "financialCurrency": "KRW",
                             "netIncomeToCommon": 161_965_397_770_240}})
    got = fetch_fundamentals(foreign_company("000660.KS"))
    assert got.amounts.currency == "KRW"


def test_the_quote_currency_is_used_when_no_reporting_currency_is_given(fake_info):
    """Most records carry both. When only the quote currency is present it is
    better than UNKNOWN, so it stays the fallback rather than being discarded."""
    fake_info({"0981.HK": {"currency": "HKD"}})
    assert fetch_fundamentals(foreign_company()).amounts.currency == "HKD"


def test_us_companies_fall_back_to_yfinance_when_fmp_cannot_serve_them(
    monkeypatch, fake_info
):
    """REGRESSION: FMP's free tier covers only a SUBSET of US symbols. SNPS and
    MRVL, both major Nasdaq companies, return 402 while AMD and NVDA work."""
    def refuse(*args, **kwargs):
        raise CompanyDataError("FMP free tier does not cover this symbol (SNPS).")

    monkeypatch.setattr(C, "_fmp_get", refuse)
    fake_info({"SNPS": {"debtToEquity": 30.0, "revenueGrowth": 0.1,
                        "currency": "USD"}})

    got = fetch_fundamentals(us_company("SNPS"))
    assert got.source == "yfinance"
    assert got.comparable.debt_to_equity == pytest.approx(0.30)


def test_fmp_ratios_are_used_as_is(monkeypatch):
    """FMP already reports debt/equity as a ratio; converting would break it."""
    def rows(path, use_cache, **params):
        return {
            "ratios-ttm": [{"grossProfitMarginTTM": 0.53,
                            "operatingProfitMarginTTM": 0.16,
                            "debtToEquityRatioTTM": 0.0636}],
            "financial-growth": [{"revenueGrowth": 0.34}],
            "cash-flow-statement": [{"freeCashFlow": 1.0, "reportedCurrency": "USD",
                                     "date": "2025-12-27"}],
            "income-statement": [{"netIncome": 2.0, "reportedCurrency": "USD"}],
        }[path]

    monkeypatch.setattr(C, "_fmp_get", rows)
    got = fetch_fundamentals(us_company())

    assert got.source == "fmp"
    assert got.comparable.debt_to_equity == pytest.approx(0.0636)
    assert got.amounts.currency == "USD"
    assert got.as_of is not None


# --- Error handling ----------------------------------------------------------


@pytest.mark.parametrize(
    "status,expected",
    [(401, "key"), (402, "does not cover"), (429, "rate limit"), (500, "HTTP 500")],
)
def test_fmp_errors_become_actionable_messages(monkeypatch, status, expected):
    class Response:
        status_code = status
        text = "nope"
        def json(self): return []

    monkeypatch.setattr(C.requests, "get", lambda *a, **k: Response())
    with pytest.raises(CompanyDataError, match=expected):
        C._fmp_get("ratios-ttm", False, symbol="AMD")


def test_network_failure_becomes_a_company_data_error(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("no route")
    monkeypatch.setattr(C.requests, "get", boom)
    with pytest.raises(CompanyDataError, match="Could not reach"):
        C._fmp_get("ratios-ttm", False, symbol="AMD")
