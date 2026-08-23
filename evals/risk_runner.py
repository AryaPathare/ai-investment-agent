"""Run Agent 4 against real Agent 3 output and score process quality.

    python -m evals.risk_runner
    python -m evals.risk_runner --case semiconductors_high_risk
    python -m evals.risk_runner --limit 2      # fewer profiles, less quota

WHAT IS BEING MEASURED

Not "did it find the right risks" - there is no right answer, and finding out
would mean waiting to see which companies disappointed. These are properties
that must hold whichever risks it found.

The failure this agent is built to avoid is not missing a danger. It is
MANUFACTURING one, fluently, in a way that reads exactly like analysis. So most
of what follows is aimed at that: is every risk traceable, is any of it generic
enough to be true of any company, and did the model cite things that were never
retrieved.

HARD FAILURES (a bug, not an opinion)
    grounding      every risk cites a retrievable article or a named metric
    resolvable     every cited uuid appears in the findings' own article list
    attribution    every risk sits under the candidate it names
    accounting     every Agent 3 candidate is critiqued or recorded as skipped
    cap            no more candidates critiqued than the configured cap
    verdict        the recorded verdict matches the severity arithmetic
    no invention   no critique names a company Agent 3 never produced

SOFT SIGNALS (report and compare across changes)
    risk yield      risks per critiqued candidate - zero everywhere means the
                    retrieval or the prompt is not working
    generic claims  claims matching phrases that are true of any company, which
                    is manufactured criticism surviving the prompt
    claims          every claim printed with the SOURCE behind it. Counting
                    cannot tell you whether a finding is worth reading; two
                    material risks against Pfizer passed every check while
                    resting on a commentary blog
    discarded       risks citing articles that were never retrieved; a number
                    climbing here means the model is inventing sources
    dry retrieval   candidates for which no bear-case article was found at all
    type mix        all one type would mean the prompt is steering
    severity mix    all critical is miscalibration; all minor is toothlessness
    verdicts        how many candidates end disqualified, weakened, survived
    source mix      news-derived versus fundamentals-derived risks

BUDGET
Each profile runs Agents 2, 3 and 4. Agent 4 alone costs up to
``max_critique_candidates`` model calls plus two news requests per candidate, so
this is the most expensive eval in the project. Profiles are paced apart.
"""

import argparse
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone

from config import PROJECT_ROOT, get_settings
from evals.research_cases import CASES, ResearchCase
from models.companies import CompanyFindings
from models.risk import RiskFindings

RESULTS_DIR = PROJECT_ROOT / "evals" / "results"

# Phrases that are true of essentially any listed company. A claim containing
# one is criticism that survived the prompt's ban without saying anything, and
# it is the signature of a critic filling a quota rather than reporting.
#
# Soft, not hard: a genuine claim can legitimately contain "competition" while
# also naming a mechanism, so this counts suspicion rather than declaring a bug.
GENERIC_PHRASES = [
    "competition is intense",
    "faces competition",
    "highly competitive",
    "valuation",
    "macro",
    "market conditions",
    "share price",
    "stock price",
    "could fall",
    "uncertainty",
    "may underperform",
    "investors should",
]


def _force_utf8_output() -> None:
    """The Windows console is cp1252 and cannot encode what the model emits."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def _is_generic(claim: str) -> bool:
    text = claim.lower()
    return any(phrase in text for phrase in GENERIC_PHRASES)


def score_run(
    case: ResearchCase,
    companies: CompanyFindings,
    risks: RiskFindings,
) -> dict:
    """Turn one profile's run into a row of measurements."""
    settings = get_settings()

    critiqued = [c for c in risks.critiques if c.was_critiqued]
    skipped = [c for c in risks.critiques if not c.was_critiqued]
    all_risks = [r for c in risks.critiques for r in c.risks]

    known_uuids = {a.uuid for a in risks.articles}
    unresolvable = [
        (r.ticker, uuid)
        for r in all_risks
        for uuid in r.article_ids
        if uuid not in known_uuids
    ]

    # The schema forbids constructing one, so this fires only if something
    # downstream built a Risk by a route that bypassed validation.
    ungrounded = [
        r.ticker for r in all_risks if not r.article_ids and r.metric is None
    ]

    misattributed = [
        (c.ticker, r.ticker)
        for c in risks.critiques
        for r in c.risks
        if r.ticker != c.ticker
    ]

    candidate_tickers = {c.ticker for c in companies.candidates}
    critique_tickers = [c.ticker for c in risks.critiques]
    invented = [t for t in critique_tickers if t not in candidate_tickers]
    unaccounted = sorted(candidate_tickers - set(critique_tickers))

    over_cap = len(critiqued) > settings.max_critique_candidates

    # Recompute the verdict independently of the property, so a future edit that
    # loosens the arithmetic is caught rather than silently blessed.
    verdict_mismatches = []
    for c in risks.critiques:
        counts = c.severity_counts
        expected = (
            "disqualified" if counts["critical"] >= 1
            else "weakened" if counts["material"] >= 2
            else "survives"
        )
        if c.verdict != expected:
            verdict_mismatches.append((c.ticker, c.verdict, expected))

    generic = [r.claim[:70] for r in all_risks if _is_generic(r.claim)]
    dry = [c.ticker for c in critiqued if c.articles_reviewed == 0]

    return {
        "case": case.name,
        "candidates": len(companies.candidates),
        "critiqued": len(critiqued),
        "skipped": len(skipped),
        "risks": len(all_risks),
        # hard
        "unresolvable_citations": unresolvable,
        "ungrounded_risks": ungrounded,
        "misattributed_risks": misattributed,
        "invented_candidates": invented,
        "unaccounted_candidates": unaccounted,
        "over_cap": over_cap,
        "verdict_mismatches": verdict_mismatches,
        # soft
        "risks_per_critiqued": (
            round(len(all_risks) / len(critiqued), 2) if critiqued else 0.0
        ),
        "generic_claims": generic,
        # The actual claims, with their evidence. Every other measurement here
        # counts something; none of them can tell you whether the output is
        # worth reading. Two MATERIAL risks against Pfizer were specific,
        # correctly cited and passed every check while resting on a commentary
        # blog - which was only visible by reading them.
        "claims": [
            {
                "ticker": r.ticker,
                "severity": r.severity,
                "type": r.risk_type,
                "claim": r.claim,
                "source": (
                    r.metric if r.is_fundamental
                    else ", ".join(
                        a.source for a in (
                            risks.article_by_id(i) for i in r.article_ids
                        ) if a
                    )
                ),
            }
            for r in all_risks
        ],
        "risks_discarded": risks.risks_discarded,
        "dry_retrieval": dry,
        "articles_retrieved": risks.articles_retrieved,
        "articles_cited": len(risks.articles),
        "types": dict(Counter(r.risk_type for r in all_risks)),
        "severities": dict(Counter(r.severity for r in all_risks)),
        "verdicts": dict(Counter(c.verdict for c in risks.critiques)),
        "sources": {
            "news": sum(1 for r in all_risks if not r.is_fundamental),
            "fundamental": sum(1 for r in all_risks if r.is_fundamental),
        },
        "notes": risks.notes,
        "error": None,
    }


def hard_failures(row: dict) -> list[str]:
    problems = []
    if row["error"]:
        problems.append(f"run failed: {row['error']}")
    if row["unresolvable_citations"]:
        problems.append(f"risks citing unretrievable articles: {row['unresolvable_citations']}")
    if row["ungrounded_risks"]:
        problems.append(f"risks grounded in nothing: {row['ungrounded_risks']}")
    if row["misattributed_risks"]:
        problems.append(f"risks filed under the wrong candidate: {row['misattributed_risks']}")
    if row["invented_candidates"]:
        problems.append(f"critiques of companies Agent 3 never produced: {row['invented_candidates']}")
    if row["unaccounted_candidates"]:
        problems.append(f"candidates neither critiqued nor recorded as skipped: {row['unaccounted_candidates']}")
    if row["over_cap"]:
        problems.append("more candidates critiqued than the configured cap")
    if row["verdict_mismatches"]:
        problems.append(f"verdict does not match the severity arithmetic: {row['verdict_mismatches']}")
    return problems


def print_case(row: dict) -> None:
    problems = hard_failures(row)
    print(f"\n  [{'PROBLEM' if problems else 'OK'}] {row['case']}")

    if row["error"]:
        print(f"      ERROR: {row['error']}")
        return

    print(f"      {row['candidates']} candidates -> {row['critiqued']} critiqued "
          f"({row['skipped']} skipped) -> {row['risks']} risks")
    print(f"      articles {row['articles_retrieved']} retrieved / "
          f"{row['articles_cited']} cited")

    if row["risks"]:
        print(f"      types {row['types']}")
        print(f"      severity {row['severities']}  source {row['sources']}")
    print(f"      verdicts {row['verdicts']}   risks per critiqued: {row['risks_per_critiqued']}")

    if row["dry_retrieval"]:
        print(f"      no bear-case articles found for: {row['dry_retrieval']}")
    if row["risks_discarded"]:
        print(f"      discarded {row['risks_discarded']} risk(s) citing nothing retrieved")
    for claim in row["generic_claims"]:
        print(f"      GENERIC? {claim}")
    for c in row.get("claims", []):
        print(f"      [{c['severity']:8}] {c['type']:20} ({c['source'][:28]})")
        print(f"        {c['claim'][:96]}")
    if row["notes"]:
        print(f"      notes: {row['notes'][:100]}")

    for problem in problems:
        print(f"      FAIL {problem}")


def summarise(rows: list[dict]) -> dict:
    scored = [r for r in rows if not r["error"]]

    types: Counter = Counter()
    severities: Counter = Counter()
    verdicts: Counter = Counter()
    for r in scored:
        types.update(r["types"])
        severities.update(r["severities"])
        verdicts.update(r["verdicts"])

    total_risks = sum(r["risks"] for r in scored)
    return {
        "cases": len(rows),
        "errored": sum(1 for r in rows if r["error"]),
        "candidates": sum(r["candidates"] for r in scored),
        "critiqued": sum(r["critiqued"] for r in scored),
        "total_risks": total_risks,
        "hard_failures": sum(len(hard_failures(r)) for r in rows),
        "generic_claims": sum(len(r["generic_claims"]) for r in scored),
        "risks_discarded": sum(r["risks_discarded"] for r in scored),
        "dry_retrieval": sum(len(r["dry_retrieval"]) for r in scored),
        "cases_finding_no_risk": sum(1 for r in scored if r["risks"] == 0),
        "types": dict(types.most_common()),
        "severities": dict(severities),
        "verdicts": dict(verdicts),
        "sources": {
            "news": sum(r["sources"]["news"] for r in scored),
            "fundamental": sum(r["sources"]["fundamental"] for r in scored),
        },
    }


def print_summary(s: dict) -> None:
    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"  cases run                {s['cases']}  ({s['errored']} errored)")
    print(f"  candidates -> critiqued  {s['candidates']} -> {s['critiqued']}")
    print(f"  risks found              {s['total_risks']}")
    print(f"  cases finding no risk    {s['cases_finding_no_risk']}/{s['cases']}")
    print()
    print(f"  HARD FAILURES            {s['hard_failures']}   (any non-zero is a bug)")
    print()
    print("  SOFT SIGNALS")
    print(f"    generic claims         {s['generic_claims']}   (manufactured criticism)")
    print(f"    risks discarded        {s['risks_discarded']}   (model invented a source)")
    print(f"    dry retrieval          {s['dry_retrieval']}   (no bear-case articles found)")
    print(f"    risk types             {s['types']}")
    print(f"    severities             {s['severities']}")
    print(f"    verdicts               {s['verdicts']}")
    print(f"    news vs fundamental    {s['sources']}")
    print("=" * 72)


def main() -> int:
    _force_utf8_output()
    parser = argparse.ArgumentParser(description="Score Agent 4 on process quality.")
    parser.add_argument("--case", help="run only this profile")
    parser.add_argument("--limit", type=int, default=2,
                        help="how many profiles to run (default 2 - this is the "
                             "most expensive eval in the project)")
    parser.add_argument("--delay", type=float, default=45.0)
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
    from agents.risk_agent import critique_companies

    print(f"Running Agent 2 -> 3 -> 4 for {len(cases)} profile(s).")
    print(f"Pacing {args.delay}s apart to stay inside the free tier's quotas.\n")

    rows: list[dict] = []
    for index, case in enumerate(cases, start=1):
        print(f"  {index}/{len(cases)}  {case.name} ...", flush=True)
        try:
            research = research_themes(case.profile, use_cache=not args.no_cache)
            time.sleep(min(args.delay, 30))
            companies = analyse_companies(research, use_cache=not args.no_cache)
            time.sleep(min(args.delay, 30))
            risks = critique_companies(companies, use_cache=not args.no_cache)
            rows.append(score_run(case, companies, risks))
        except Exception as exc:  # noqa: BLE001 - a failed run is a result
            rows.append({
                "case": case.name, "error": f"{type(exc).__name__}: {exc}",
                "candidates": 0, "critiqued": 0, "skipped": 0, "risks": 0,
                "unresolvable_citations": [], "ungrounded_risks": [],
                "misattributed_risks": [], "invented_candidates": [],
                "unaccounted_candidates": [], "over_cap": False,
                "verdict_mismatches": [], "risks_per_critiqued": 0.0,
                "generic_claims": [], "claims": [], "risks_discarded": 0,
                "dry_retrieval": [],
                "articles_retrieved": 0, "articles_cited": 0, "types": {},
                "severities": {}, "verdicts": {},
                "sources": {"news": 0, "fundamental": 0}, "notes": None,
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
        path = RESULTS_DIR / f"risks-{stamp}.json"
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
