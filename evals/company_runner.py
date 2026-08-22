"""Run Agent 3 against real research output and score process quality.

    python -m evals.company_runner
    python -m evals.company_runner --case semiconductors_high_risk
    python -m evals.company_runner --limit 2      # fewer profiles, less quota
    python -m evals.company_runner --delay 90     # slower, if rate limited

WHAT IS BEING MEASURED
----------------------
Not "did it pick the right companies" - there is no right answer, and finding
out would mean waiting years. These are properties that must hold whichever
companies it chose, and nearly all of them are checkable against a source of
truth today.

HARD FAILURES (a bug, not an opinion)
    traceability     every candidate cites an article the research retrieved
    exposure         no candidate is graded incidental; the reason it is in the
                     list must actually hold
    ranking          scores descend, and the candidate cap holds
    units            debt/equity lands in ratio range, not percentage range -
                     this is the 100x provider discrepancy coming back
    accounting       every mentioned company is a candidate or a recorded drop
    not a fund       no candidate is an ETF or trust wearing a company's name
    restrictions     no candidate breaches a limit the investor actually stated

SOFT SIGNALS (report and compare across changes)
    conversion       how many mentions survive to candidates
    drop profile     which reason dominates - the difference between good
                     filtering and a broken resolver
    grade inflation  how often exposure comes back "direct"
    saturation       how many candidates score a flat 1.0, which would mean the
                     ranking cannot separate the best from the merely good
    provider mix     how often the FMP path falls back to yfinance
    growth sanity    growth figures so large they are more likely a provider
                     artifact than a business - the ranking clips them into
                     invisibility, so they have to be caught here

BUDGET
Each profile costs four model calls and up to four FMP requests per US company,
against a free tier of 8000 tokens/minute and 250 requests/day. Profiles are
paced apart, caching is on by default, and the runner reports if a provider
starts refusing.
"""

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone

from config import PROJECT_ROOT, get_settings
from evals.research_cases import CASES, ResearchCase
from models.companies import CompanyFindings
from models.research import ResearchFindings

RESULTS_DIR = PROJECT_ROOT / "evals" / "results"

# A debt-to-equity ratio above this is almost certainly a percentage that was
# not normalised. Real leverage of 20x essentially does not occur outside
# distressed balance sheets, whereas yfinance routinely reports 37.0 for a
# company whose true ratio is 0.37.
UNIT_SANITY_CEILING = 20.0

# Revenue growth above this is almost certainly a provider artifact rather than
# a real business. Reported as a SOFT signal, not a hard failure: extraordinary
# growth genuinely happens in a memory upcycle or after an acquisition, so a
# breach means "look at this", not "this is a bug".
#
# It exists because the ranking CANNOT surface it. Every ramp clips at its cap,
# so an implausible 256% and a healthy 55% both render as 1.0 and become
# indistinguishable. Without a check upstream of the clipping, bad provider data
# is invisible precisely when it is most influential.
GROWTH_SANITY_CEILING = 1.50

# Words that would mean a fund slipped through resolution into the candidates.
FUND_WORDS = {"etf", "etn", "proshares", "direxion", "ishares", "tradr",
              "2x", "3x", "leveraged", "trust fund"}


def _force_utf8_output() -> None:
    """The Windows console is cp1252 and cannot encode what the model emits."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def score_run(
    case: ResearchCase,
    research: ResearchFindings,
    companies: CompanyFindings,
) -> dict:
    """Turn one profile's run into a row of measurements."""
    settings = get_settings()
    candidates = companies.candidates

    known_uuids = {a.uuid for a in research.articles}
    untraceable = [
        c.ticker
        for c in candidates
        for uuid in c.evidence_article_ids
        if uuid not in known_uuids
    ]

    incidental = [c.ticker for c in candidates if c.exposure == "incidental"]

    scores = [round(c.screen_score, 4) for c in candidates]
    misranked = scores != sorted(scores, reverse=True)
    over_cap = len(candidates) > settings.max_company_candidates

    unit_failures = [
        (c.ticker, c.fundamentals.comparable.debt_to_equity)
        for c in candidates
        if (c.fundamentals.comparable.debt_to_equity or 0) > UNIT_SANITY_CEILING
    ]

    funds = [
        c.ticker
        for c in candidates
        if any(word in c.name.lower() for word in FUND_WORDS)
    ]

    # A restriction the investor stated must survive all the way to the
    # candidate list. Agent 2 is already checked for this on its themes; a theme
    # can comply while the company chosen from it does not.
    restriction_violations = [
        (c.ticker, term)
        for c in candidates
        for term in case.forbidden_terms
        if term in f"{c.name} {c.exposure_rationale} {' '.join(c.themes)}".lower()
    ]

    # Soft: growth figures the ranking would clip into invisibility.
    growth_outliers = [
        (c.ticker, c.fundamentals.comparable.revenue_growth)
        for c in candidates
        if (c.fundamentals.comparable.revenue_growth or 0) > GROWTH_SANITY_CEILING
    ]

    # Every EXAMINED COMPANY must end as a candidate or a recorded rejection.
    # Balanced against companies_examined, not mentions_extracted: a mention is
    # one company in one article, so a company named in three articles produces
    # three mentions and one examination.
    accounted = len(candidates) + len(companies.dropped)
    unaccounted = companies.companies_examined - accounted

    return {
        "case": case.name,
        "themes": len(research.themes),
        "articles": len(research.articles),
        "mentions": companies.mentions_extracted,
        "companies_examined": companies.companies_examined,
        "candidates": len(candidates),
        # hard
        "untraceable_candidates": untraceable,
        "incidental_candidates": incidental,
        "misranked": misranked,
        "over_cap": over_cap,
        "unit_failures": unit_failures,
        "funds_in_candidates": funds,
        "unaccounted_mentions": unaccounted,
        "restriction_violations": restriction_violations,
        # soft
        "growth_outliers": growth_outliers,
        "drop_summary": companies.drop_summary,
        "exposures": dict(Counter(c.exposure for c in candidates)),
        "sources": dict(Counter(c.fundamentals.source for c in candidates)),
        "currencies": dict(Counter(c.currency for c in candidates)),
        "saturated": sum(1 for s in scores if s >= 0.999),
        "scores": scores,
        "tickers": [c.ticker for c in candidates],
        "avg_completeness": (
            round(
                sum(c.fundamentals.comparable.completeness for c in candidates)
                / len(candidates),
                3,
            )
            if candidates
            else 0.0
        ),
        "notes": companies.notes,
        "error": None,
    }


def hard_failures(row: dict) -> list[str]:
    problems = []
    if row["error"]:
        problems.append(f"run failed: {row['error']}")
    if row["untraceable_candidates"]:
        problems.append(f"candidates citing unknown articles: {row['untraceable_candidates']}")
    if row["incidental_candidates"]:
        problems.append(f"incidental companies survived: {row['incidental_candidates']}")
    if row["misranked"]:
        problems.append("candidates are not in descending score order")
    if row["over_cap"]:
        problems.append("more candidates than the configured cap")
    if row["unit_failures"]:
        problems.append(f"debt/equity outside ratio range: {row['unit_failures']}")
    if row["funds_in_candidates"]:
        problems.append(f"funds reached the candidate list: {row['funds_in_candidates']}")
    if row.get("restriction_violations"):
        problems.append(f"candidates violate a stated restriction: {row['restriction_violations']}")
    if row["unaccounted_mentions"] > 0:
        problems.append(f"{row['unaccounted_mentions']} examined company/companies vanished without a drop reason")
    return problems


def print_case(row: dict) -> None:
    problems = hard_failures(row)
    print(f"\n  [{'PROBLEM' if problems else 'OK'}] {row['case']}")

    if row["error"]:
        print(f"      ERROR: {row['error']}")
        return

    print(f"      {row['themes']} themes / {row['articles']} articles -> "
          f"{row['mentions']} mentions -> {row.get('companies_examined', 0)} companies"
          f" -> {row['candidates']} candidates")

    for ticker, s in zip(row["tickers"], row["scores"]):
        print(f"        {s:.3f}  {ticker}")

    if row["drop_summary"]:
        print(f"      dropped: {row['drop_summary']}")
    if row["candidates"]:
        print(f"      exposure {row['exposures']}  source {row['sources']}  "
              f"currency {row['currencies']}")
        print(f"      avg metric completeness: {row['avg_completeness']:.0%}"
              f"   saturated at 1.0: {row['saturated']}")
    if row.get("growth_outliers"):
        print(f"      growth above the sanity ceiling: {row['growth_outliers']}")
    if row["notes"]:
        print(f"      notes: {row['notes'][:100]}")

    for problem in problems:
        print(f"      FAIL {problem}")


def summarise(rows: list[dict]) -> dict:
    scored = [r for r in rows if not r["error"]]
    drops: Counter = Counter()
    for r in scored:
        drops.update(r["drop_summary"])

    total_candidates = sum(r["candidates"] for r in scored)
    exposures: Counter = Counter()
    for r in scored:
        exposures.update(r["exposures"])

    return {
        "cases": len(rows),
        "errored": sum(1 for r in rows if r["error"]),
        "total_mentions": sum(r["mentions"] for r in scored),
        "total_candidates": total_candidates,
        "hard_failures": sum(len(hard_failures(r)) for r in rows),
        "drop_profile": dict(drops.most_common()),
        "exposure_profile": dict(exposures),
        "saturated_candidates": sum(r["saturated"] for r in scored),
        "cases_finding_nothing": sum(1 for r in scored if r["candidates"] == 0),
        "growth_outliers": [o for r in scored for o in r.get("growth_outliers", [])],
        "sources": dict(
            Counter(k for r in scored for k, v in r["sources"].items() for _ in range(v))
        ),
    }


def print_summary(s: dict) -> None:
    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"  cases run                {s['cases']}  ({s['errored']} errored)")
    print(f"  mentions -> candidates   {s['total_mentions']} -> {s['total_candidates']}")
    print(f"  cases finding nothing    {s['cases_finding_nothing']}/{s['cases']}")
    print()
    print(f"  HARD FAILURES            {s['hard_failures']}   (any non-zero is a bug)")
    print()
    print("  SOFT SIGNALS")
    print(f"    drop profile           {s['drop_profile']}")
    print(f"    exposure of candidates {s['exposure_profile']}")
    print(f"    data source used       {s['sources']}")
    print(f"    scores saturated at 1  {s['saturated_candidates']}/{s['total_candidates']}")
    print(f"    growth sanity breaches {s['growth_outliers'] or 'none'}")
    print("=" * 72)


def main() -> int:
    _force_utf8_output()
    parser = argparse.ArgumentParser(description="Score Agent 3 on process quality.")
    parser.add_argument("--case", help="run only this profile")
    parser.add_argument("--limit", type=int, default=3,
                        help="how many profiles to run (default 3, to conserve quota)")
    parser.add_argument("--delay", type=float, default=45.0,
                        help="seconds between profiles, to stay inside the token quota")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    cases = [c for c in CASES if not args.case or c.name == args.case]
    if not args.case:
        cases = cases[: args.limit]
    if not cases:
        print(f"No case named {args.case!r}.")
        return 1

    # Imported here so --help works without credentials.
    from agents.company_agent import analyse_companies
    from agents.research_agent import research_themes

    print(f"Running Agent 2 -> Agent 3 for {len(cases)} profile(s).")
    print(f"Pacing {args.delay}s apart to stay inside the free tier's quotas.\n")

    rows: list[dict] = []
    for index, case in enumerate(cases, start=1):
        print(f"  {index}/{len(cases)}  {case.name} ...", flush=True)
        try:
            research = research_themes(case.profile, use_cache=not args.no_cache)
            time.sleep(min(args.delay, 30))  # both agents share the token budget
            companies = analyse_companies(research, use_cache=not args.no_cache)
            rows.append(score_run(case, research, companies))
        except Exception as exc:  # noqa: BLE001 - a failed run is a result
            rows.append({
                "case": case.name, "error": f"{type(exc).__name__}: {exc}",
                "themes": 0, "articles": 0, "mentions": 0, "candidates": 0,
                "companies_examined": 0,
                "untraceable_candidates": [], "incidental_candidates": [],
                "misranked": False, "over_cap": False, "unit_failures": [],
                "funds_in_candidates": [], "unaccounted_mentions": 0,
                "restriction_violations": [], "growth_outliers": [],
                "drop_summary": {}, "exposures": {}, "sources": {},
                "currencies": {}, "saturated": 0, "scores": [], "tickers": [],
                "avg_completeness": 0.0, "notes": None,
            })
            print(f"       ERROR: {type(exc).__name__}")

        if index < len(cases) and args.delay:
            time.sleep(args.delay)

    for row in rows:
        print_case(row)

    summary = summarise(rows)
    print_summary(summary)

    if not args.no_save:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = RESULTS_DIR / f"companies-{stamp}.json"
        path.write_text(
            json.dumps({"timestamp": stamp, "summary": summary, "results": rows},
                       indent=2, default=str),
            encoding="utf-8",
        )
        print(f"\n  Saved to {path.relative_to(PROJECT_ROOT)}")

    if summary["hard_failures"]:
        print(f"\n  {summary['hard_failures']} hard failure(s) - these are bugs.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
