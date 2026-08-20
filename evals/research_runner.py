"""Run Agent 2 against the eval profiles and score process quality.

    python -m evals.research_runner
    python -m evals.research_runner --case renewables_excluding_fossil_fuels
    python -m evals.research_runner --no-url-check     # skip live URL checks
    python -m evals.research_runner --delay 90         # slower, if rate limited

WHAT IS BEING MEASURED
----------------------
Not "did it pick the right themes" — there is no right answer. These are
properties that must hold whichever themes it chose.

HARD FAILURES (a bug, not an opinion)
    citation integrity  every cited id resolves to a retrieved article
    dead sources        cited URLs return 404/410
    restrictions        a theme in an area the investor explicitly ruled out

SOFT SIGNALS (report and compare over time)
    padding             hitting the theme cap with thin single-source themes
    stance diversity    does it ever record evidence that WEAKENS a theme
    confidence spread   is confidence calibrated, or is everything "high"
    citation depth      average sources per theme

RATE LIMITS
Groq's free tier allows 8000 tokens per minute, and one research run costs about
6100 of them. Runs are therefore paced apart by default; without the delay the
second profile fails with a 413.
"""

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone

import requests

from config import PROJECT_ROOT, get_settings
from evals.research_cases import CASES, ResearchCase
from models.research import ResearchFindings

RESULTS_DIR = PROJECT_ROOT / "evals" / "results"
URL_CHECK_TIMEOUT = 10

# 404 and 410 mean the article is not there. A 403 or 405 usually means the
# publisher blocks automated requests, which says nothing about whether the
# article exists — counting those as dead would report false failures.
DEAD_STATUSES = {404, 410}


def _theme_text(theme) -> str:
    """Everything the model wrote about a theme, lowercased, for term matching."""
    return " ".join(
        [theme.name, theme.why_it_matters, *theme.industries]
    ).lower()


def check_urls(findings: ResearchFindings) -> dict:
    """Verify cited articles actually exist on the web.

    This is the strongest available check against fabricated sources. The schema
    makes inventing one structurally impossible, so a dead URL here would mean
    the news API returned something stale rather than the model inventing it —
    but it is worth knowing either way, since Agent 3 will try to use these.
    """
    dead, unreachable, alive = [], [], 0

    for article in findings.articles:
        try:
            response = requests.head(
                article.url,
                timeout=URL_CHECK_TIMEOUT,
                allow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ai-investment-agent)"},
            )
            if response.status_code in DEAD_STATUSES:
                dead.append((article.url, response.status_code))
            else:
                alive += 1
        except requests.RequestException:
            # Network trouble on our side is not evidence about the article.
            unreachable.append(article.url)

    return {"alive": alive, "dead": dead, "unreachable": unreachable}


def score(case: ResearchCase, findings: ResearchFindings, url_report: dict | None) -> dict:
    """Turn one run into a row of measurements."""
    settings = get_settings()
    themes = findings.themes

    # --- hard: does every citation resolve? ---------------------------------
    citations = [e.article_id for t in themes for e in t.evidence]
    unresolved = [c for c in citations if findings.article_by_id(c) is None]

    # --- hard: were restrictions respected? ---------------------------------
    violations = [
        (t.name, term)
        for t in themes
        for term in case.forbidden_terms
        if term in _theme_text(t)
    ]

    # --- soft: padding ------------------------------------------------------
    single_source = [t.name for t in themes if len(t.evidence) == 1]
    low_confidence = [t.name for t in themes if t.confidence == "low"]
    at_cap = len(themes) >= settings.research_max_themes

    # --- soft: is the evidence one-sided? -----------------------------------
    stances = Counter(e.stance for t in themes for e in t.evidence)

    # --- soft: does anything relate to what they asked about? ---------------
    on_topic = [
        t.name
        for t in themes
        if any(term in _theme_text(t) for term in case.expected_terms)
    ]

    return {
        "case": case.name,
        "themes": len(themes),
        "articles_retrieved": findings.articles_retrieved,
        "articles_cited": len(findings.articles),
        "citations": len(citations),
        "unresolved_citations": unresolved,
        "restriction_violations": violations,
        "dead_urls": (url_report or {}).get("dead", []),
        "unreachable_urls": len((url_report or {}).get("unreachable", [])),
        "at_theme_cap": at_cap,
        "single_source_themes": single_source,
        "low_confidence_themes": low_confidence,
        "avg_citations_per_theme": (
            round(len(citations) / len(themes), 2) if themes else 0.0
        ),
        "stances": dict(stances),
        "confidences": dict(Counter(t.confidence for t in themes)),
        "timeframes": dict(Counter(t.timeframe for t in themes)),
        "on_topic_themes": len(on_topic),
        "found_nothing": findings.found_nothing,
        "theme_names": [t.name for t in themes],
        "notes": findings.notes,
        "error": None,
    }


def print_case(row: dict) -> None:
    status = "OK"
    if row["error"] or row["unresolved_citations"] or row["restriction_violations"] or row["dead_urls"]:
        status = "PROBLEM"

    print(f"\n  [{status}] {row['case']}")

    if row["error"]:
        print(f"      ERROR: {row['error']}")
        return

    print(f"      {row['articles_retrieved']} retrieved -> "
          f"{row['themes']} themes, {row['articles_cited']} cited, "
          f"{row['avg_citations_per_theme']} sources/theme")

    for name in row["theme_names"]:
        print(f"        - {name}")

    if row["unresolved_citations"]:
        print(f"      FAIL unresolved citations: {row['unresolved_citations']}")
    if row["restriction_violations"]:
        for theme, term in row["restriction_violations"]:
            print(f"      FAIL restriction breach: {theme!r} mentions {term!r}")
    if row["dead_urls"]:
        for url, code in row["dead_urls"]:
            print(f"      FAIL dead source ({code}): {url[:70]}")

    print(f"      confidences {row['confidences']}  stances {row['stances']}")
    if row["at_theme_cap"]:
        print(f"      NOTE at the theme cap; {len(row['single_source_themes'])} "
              f"single-source, {len(row['low_confidence_themes'])} low-confidence")
    if row["found_nothing"]:
        print(f"      returned nothing: {row['notes']}")


def summarise(rows: list[dict]) -> dict:
    scored = [r for r in rows if not r["error"]]
    themes_total = sum(r["themes"] for r in scored)

    return {
        "cases": len(rows),
        "errored": sum(1 for r in rows if r["error"]),
        "themes_total": themes_total,
        "unresolved_citations": sum(len(r["unresolved_citations"]) for r in scored),
        "restriction_violations": sum(len(r["restriction_violations"]) for r in scored),
        "dead_urls": sum(len(r["dead_urls"]) for r in scored),
        "cases_at_cap": sum(1 for r in scored if r["at_theme_cap"]),
        "single_source_themes": sum(len(r["single_source_themes"]) for r in scored),
        "cases_with_dissenting_evidence": sum(
            1 for r in scored
            if r["stances"].get("weakens", 0) or r["stances"].get("complicates", 0)
        ),
        "cases_returning_nothing": sum(1 for r in scored if r["found_nothing"]),
        "on_topic_themes": sum(r["on_topic_themes"] for r in scored),
    }


def print_summary(s: dict) -> None:
    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"  cases run                  {s['cases']}  ({s['errored']} errored)")
    print(f"  themes produced            {s['themes_total']}")
    print(f"  themes on topic            {s['on_topic_themes']}/{s['themes_total']}")
    print()
    print("  HARD CHECKS (any non-zero is a bug)")
    print(f"    unresolved citations     {s['unresolved_citations']}")
    print(f"    restriction violations   {s['restriction_violations']}")
    print(f"    dead source URLs         {s['dead_urls']}")
    print()
    print("  SOFT SIGNALS (compare across changes)")
    print(f"    cases hitting theme cap  {s['cases_at_cap']}/{s['cases']}")
    print(f"    single-source themes     {s['single_source_themes']}/{s['themes_total']}")
    print(f"    cases citing dissent     {s['cases_with_dissenting_evidence']}/{s['cases']}")
    print(f"    cases returning nothing  {s['cases_returning_nothing']}/{s['cases']}")
    print("=" * 72)


def _force_utf8_output() -> None:
    """Make stdout able to print model output on Windows.

    The Windows console defaults to cp1252, which cannot encode characters the
    model routinely produces - non-breaking hyphens, curly quotes, en dashes.
    Printing a theme name containing one raises UnicodeEncodeError and kills the
    run, losing results that were already computed. Any script that displays
    model output needs this.
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def main() -> int:
    _force_utf8_output()
    parser = argparse.ArgumentParser(description="Score Agent 2 on process quality.")
    parser.add_argument("--case", help="run only the case with this name")
    parser.add_argument(
        "--delay",
        type=float,
        default=60.0,
        help=(
            "Seconds between profiles. One run costs ~6100 of the free tier's "
            "8000 tokens per minute, so back-to-back runs fail with 413."
        ),
    )
    parser.add_argument("--no-url-check", action="store_true",
                        help="skip checking that cited URLs resolve")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--no-cache", action="store_true",
                        help="force live news searches instead of cached results")
    args = parser.parse_args()

    cases = [c for c in CASES if not args.case or c.name == args.case]
    if not cases:
        print(f"No case named {args.case!r}.")
        return 1

    # Import here so --help works without an API key.
    from agents.research_agent import research_themes

    print(f"Running {len(cases)} research case(s) against the live model and news API.")
    print(f"Pacing {args.delay}s apart to stay inside the free tier's token quota.\n")

    rows: list[dict] = []
    for index, case in enumerate(cases, start=1):
        print(f"  {index}/{len(cases)}  {case.name} ...", flush=True)
        try:
            findings = research_themes(case.profile, use_cache=not args.no_cache)
        except Exception as exc:  # noqa: BLE001 - a failed run is a result
            rows.append({
                "case": case.name, "error": f"{type(exc).__name__}: {exc}",
                "themes": 0, "unresolved_citations": [], "restriction_violations": [],
                "dead_urls": [], "found_nothing": True, "theme_names": [],
                "stances": {}, "confidences": {}, "at_theme_cap": False,
                "single_source_themes": [], "low_confidence_themes": [],
                "articles_retrieved": 0, "articles_cited": 0, "citations": 0,
                "avg_citations_per_theme": 0.0, "on_topic_themes": 0,
                "notes": None, "unreachable_urls": 0, "timeframes": {},
            })
            print(f"       ERROR: {type(exc).__name__}")
            continue

        url_report = None if args.no_url_check else check_urls(findings)
        rows.append(score(case, findings, url_report))

        if index < len(cases) and args.delay:
            time.sleep(args.delay)

    for row in rows:
        print_case(row)

    summary = summarise(rows)
    print_summary(summary)

    if not args.no_save:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = RESULTS_DIR / f"research-{stamp}.json"
        path.write_text(
            json.dumps({"timestamp": stamp, "summary": summary, "results": rows}, indent=2),
            encoding="utf-8",
        )
        print(f"\n  Saved to {path.relative_to(PROJECT_ROOT)}")

    hard_failures = (
        summary["unresolved_citations"]
        + summary["restriction_violations"]
        + summary["dead_urls"]
    )
    if hard_failures:
        print(f"\n  {hard_failures} hard failure(s) - these are bugs, not opinions.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
