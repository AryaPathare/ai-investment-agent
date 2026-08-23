"""Run Agent 5 against real output from the whole pipeline and score it.

    python -m evals.decision_runner
    python -m evals.decision_runner --case banking_excluding_crypto
    python -m evals.decision_runner --limit 1     # the most expensive eval here

WHAT IS BEING MEASURED

Not "were these the right companies" - that would take years to find out. These
are properties that must hold whichever companies were chosen.

This is the last stage, and the only one whose output a person reads directly.
That changes what can go wrong. Everywhere upstream a weakness hid behind a
plausible-looking FIELD; here it hides inside plausible-looking PROSE, which is
far harder to see and far easier to act on. So the checks are aimed less at the
selection - that is deterministic and already tested - and more at whether the
writing says anything a reader could check.

HARD FAILURES (a bug, not an opinion)
    traceable      every recommendation is a company Agent 3 actually produced
    earned         no disqualified or never-critiqued company is recommended
    restrictions   no recommendation breaches a limit the investor set
    cap            at most three recommendations
    accounting     every candidate is recommended or recorded as excluded
    grounded       every exit condition cites a retrievable article or a real
                   metric
    provenance     score and verdict match what the earlier agents said, so this
                   stage cannot quietly disagree with them
    nothing        an empty result carries the reason it is empty

SOFT SIGNALS (report and compare across changes)
    briefs          every thesis and exit condition printed. Counting cannot
                    tell you whether prose is worth reading
    unfalsifiable   conditions matching phrases nobody could ever check
    discarded       conditions the model wrote that cited nothing checkable
    advice language allocation, sizing or price talk, which this system is not
                    licensed to produce
    tolerance fit   weakened or materially risky companies recommended to an
                    investor who said their risk tolerance is low
    exclusions      why candidates fell out; all "not_critiqued" would mean the
                    critique cap is too tight rather than the field being poor

BUDGET
Each profile runs Agents 2, 3, 4 AND 5 - up to three more model calls on top of
the risk eval. This is the most expensive thing in the project.
"""

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone

from agents.decide_agent import KNOWN_METRICS
from agents.selection import restriction_terms
from config import PROJECT_ROOT
from evals.research_cases import CASES, ResearchCase
from models.companies import CompanyFindings
from models.decision import MAX_RECOMMENDATIONS, Decision
from models.risk import RiskFindings

RESULTS_DIR = PROJECT_ROOT / "evals" / "results"

# Phrases that cannot be checked. An exit condition containing one is advice
# shaped like a plan: it survives review because it sounds prudent, and nobody
# can ever answer "has this happened yet?"
UNFALSIFIABLE_PHRASES = [
    "monitor",
    "keep an eye",
    "deteriorate",
    "underperform",
    "fails to execute",
    "loses momentum",
    "sentiment",
    "significantly",
    "as expected",
    "no longer attractive",
]

# Language that crosses from research into advice. The schema has nowhere to put
# a position size, so this catches it leaking into prose instead.
ADVICE_PHRASES = [
    "allocate",
    "allocation",
    "% of your",
    "percent of your",
    "portfolio weight",
    "position size",
    "price target",
    "fair value",
    "should buy",
    "we recommend buying",
    "invest $",
]


def _force_utf8_output() -> None:
    """The Windows console is cp1252 and cannot encode what the model emits."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def _matches(text: str, phrases: list[str]) -> list[str]:
    lowered = text.lower()
    return [p for p in phrases if p in lowered]


def score_run(
    case: ResearchCase,
    companies: CompanyFindings,
    risks: RiskFindings,
    decision: Decision,
) -> dict:
    """Turn one profile's run into a row of measurements."""
    recs = decision.recommendations
    conditions = [c for r in recs for c in r.exit_conditions]

    candidate_by_ticker = {c.ticker: c for c in companies.candidates}

    untraceable = [r.ticker for r in recs if r.ticker not in candidate_by_ticker]

    unearned = []
    for rec in recs:
        critique = risks.critique_for(rec.ticker)
        if critique is None or not critique.was_critiqued:
            unearned.append((rec.ticker, "never critiqued"))
        elif critique.verdict == "disqualified":
            unearned.append((rec.ticker, "disqualified"))

    # Both lists, deliberately. `restriction_terms` is what PRODUCTION sees, and
    # it is a naive matcher: "No cryptocurrency..." yields the term
    # "cryptocurrency", which does not match a thesis saying "crypto exposure".
    # The case's `forbidden_terms` are the shorter stems written for the eval, so
    # checking both makes this stricter than the code under test rather than
    # merely agreeing with it - which is the only way a check catches anything.
    terms = restriction_terms(list(case.profile.restrictions))
    terms += [t.lower() for t in case.forbidden_terms]
    breaches = [
        (rec.ticker, term)
        for rec in recs
        for term in terms
        if term in f"{rec.name} {rec.thesis} {' '.join(rec.themes)}".lower()
    ]

    known_uuids = {a.uuid for a in risks.articles}
    ungrounded = [
        (c.condition[:50], c.metric)
        for c in conditions
        if not (
            any(uuid in known_uuids for uuid in c.article_ids)
            or c.metric in KNOWN_METRICS
        )
    ]

    # A condition on a metric that has ALREADY crossed its threshold is true the
    # moment it is written, so it can never tell a reader anything. Hard,
    # because it is a defect rather than a matter of taste - and because the
    # unfalsifiable check cannot see it: these conditions ARE falsifiable.
    already_met = []
    for rec in recs:
        critique = risks.critique_for(rec.ticker)
        spent = {
            r.metric for r in (critique.risks if critique else [])
            if r.is_fundamental and r.metric
        }
        already_met += [
            (rec.ticker, c.metric) for c in rec.exit_conditions
            if c.metric and c.metric in spent
        ]

    # Agent 5 carries score and verdict through rather than recomputing them.
    # Checked independently so a future edit that starts adjusting them is
    # caught rather than silently accepted.
    provenance = []
    for rec in recs:
        source = candidate_by_ticker.get(rec.ticker)
        critique = risks.critique_for(rec.ticker)
        if source and abs(source.screen_score - rec.screen_score) > 1e-9:
            provenance.append((rec.ticker, "screen_score"))
        if critique and critique.verdict != rec.verdict:
            provenance.append((rec.ticker, "verdict"))

    accounted = {r.ticker for r in recs} | {e.ticker for e in decision.excluded}
    unaccounted = sorted(set(candidate_by_ticker) - accounted)

    nothing_unexplained = (
        decision.recommended_nothing and not decision.no_recommendation_reason
    )

    unfalsifiable = [
        (c.condition[:60], hits)
        for c in conditions
        if (hits := _matches(c.condition, UNFALSIFIABLE_PHRASES))
    ]
    advice = [
        (rec.ticker, hits)
        for rec in recs
        if (hits := _matches(
            rec.thesis + " " + " ".join(c.condition for c in rec.exit_conditions),
            ADVICE_PHRASES,
        ))
    ]

    # Soft, as agreed: a low-tolerance investor being handed a company that only
    # survived criticism weakly, or that carries a material risk, is worth
    # seeing. It is not automatically wrong - the brief is asked to say so - but
    # it is the shape of the Agent 3 failure where two pre-revenue biotechs went
    # to a 66-year-old.
    tolerance_flags = []
    if case.profile.risk_tolerance == "low":
        for rec in recs:
            critique = risks.critique_for(rec.ticker)
            severe = [
                r.claim[:40] for r in (critique.risks if critique else [])
                if r.severity in ("critical", "material")
            ]
            if rec.verdict != "survives" or severe:
                tolerance_flags.append((rec.ticker, rec.verdict, len(severe)))

    return {
        "case": case.name,
        "candidates": len(companies.candidates),
        "recommended": len(recs),
        "excluded": len(decision.excluded),
        "conditions": len(conditions),
        # hard
        "untraceable": untraceable,
        "unearned": unearned,
        "restriction_breaches": breaches,
        "over_cap": len(recs) > MAX_RECOMMENDATIONS,
        "unaccounted": unaccounted,
        "ungrounded_conditions": ungrounded,
        "provenance_mismatches": provenance,
        "nothing_unexplained": nothing_unexplained,
        "already_met_conditions": already_met,
        # soft
        "conditions_citing_articles": sum(1 for c in conditions if c.article_ids),
        "conditions_per_rec": (
            round(len(conditions) / len(recs), 2) if recs else 0.0
        ),
        "unfalsifiable": unfalsifiable,
        "advice_language": advice,
        "tolerance_flags": tolerance_flags,
        "conditions_discarded": decision.conditions_discarded,
        "articles_available": len(risks.articles),
        "exclusion_summary": decision.exclusion_summary,
        "recommended_nothing": decision.recommended_nothing,
        "no_recommendation_reason": decision.no_recommendation_reason,
        "briefs": [
            {
                "ticker": r.ticker,
                "verdict": r.verdict,
                "score": round(r.screen_score, 3),
                "thesis": r.thesis,
                "conditions": [
                    {"condition": c.condition,
                     "grounded_in": c.metric or ", ".join(c.article_ids)}
                    for c in r.exit_conditions
                ],
            }
            for r in recs
        ],
        "notes": decision.notes,
        "error": None,
    }


def hard_failures(row: dict) -> list[str]:
    problems = []
    if row["error"]:
        problems.append(f"run failed: {row['error']}")
    if row["untraceable"]:
        problems.append(f"recommended companies Agent 3 never produced: {row['untraceable']}")
    if row["unearned"]:
        problems.append(f"recommended without earning it: {row['unearned']}")
    if row["restriction_breaches"]:
        problems.append(f"recommendations breach a stated restriction: {row['restriction_breaches']}")
    if row["over_cap"]:
        problems.append("more recommendations than the maximum")
    if row["unaccounted"]:
        problems.append(f"candidates neither recommended nor recorded as excluded: {row['unaccounted']}")
    if row["ungrounded_conditions"]:
        problems.append(f"exit conditions nobody could check: {row['ungrounded_conditions']}")
    if row["provenance_mismatches"]:
        problems.append(f"score or verdict changed by the decision stage: {row['provenance_mismatches']}")
    if row.get("already_met_conditions"):
        problems.append(f"exit conditions that are already true: {row['already_met_conditions']}")
    if row["nothing_unexplained"]:
        problems.append("recommended nothing without saying why")
    return problems


def print_case(row: dict) -> None:
    problems = hard_failures(row)
    print(f"\n  [{'PROBLEM' if problems else 'OK'}] {row['case']}")

    if row["error"]:
        print(f"      ERROR: {row['error']}")
        return

    print(f"      {row['candidates']} candidates -> {row['recommended']} recommended "
          f"({row['excluded']} excluded), {row['conditions']} exit conditions")

    if row["recommended_nothing"]:
        print(f"      NOTHING: {row['no_recommendation_reason']}")
    if row["exclusion_summary"]:
        print(f"      excluded: {row['exclusion_summary']}")

    for brief in row["briefs"]:
        print(f"\n      {brief['ticker']}  ({brief['verdict']}, score {brief['score']})")
        print(f"        {brief['thesis'][:150]}")
        for c in brief["conditions"]:
            print(f"        EXIT [{c['grounded_in'][:26]}] {c['condition'][:88]}")

    if row["conditions_discarded"]:
        print(f"\n      discarded {row['conditions_discarded']} condition(s) citing nothing checkable")
    for condition, hits in row["unfalsifiable"]:
        print(f"      UNFALSIFIABLE? {hits} {condition}")
    for ticker, hits in row["advice_language"]:
        print(f"      ADVICE LANGUAGE {ticker}: {hits}")
    for ticker, verdict, severe in row["tolerance_flags"]:
        print(f"      LOW-TOLERANCE FIT? {ticker} is {verdict} with {severe} material+ risk(s)")

    for problem in problems:
        print(f"      FAIL {problem}")


def summarise(rows: list[dict]) -> dict:
    scored = [r for r in rows if not r["error"]]
    exclusions: Counter = Counter()
    for r in scored:
        exclusions.update(r["exclusion_summary"])

    return {
        "cases": len(rows),
        "errored": sum(1 for r in rows if r["error"]),
        "candidates": sum(r["candidates"] for r in scored),
        "recommended": sum(r["recommended"] for r in scored),
        "conditions": sum(r["conditions"] for r in scored),
        "hard_failures": sum(len(hard_failures(r)) for r in rows),
        "cases_recommending_nothing": sum(1 for r in scored if r["recommended_nothing"]),
        "unfalsifiable": sum(len(r["unfalsifiable"]) for r in scored),
        "conditions_citing_articles": sum(r["conditions_citing_articles"] for r in scored),
        "advice_language": sum(len(r["advice_language"]) for r in scored),
        "tolerance_flags": sum(len(r["tolerance_flags"]) for r in scored),
        "conditions_discarded": sum(r["conditions_discarded"] for r in scored),
        "exclusions": dict(exclusions.most_common()),
    }


def print_summary(s: dict) -> None:
    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"  cases run                {s['cases']}  ({s['errored']} errored)")
    print(f"  candidates -> recommended {s['candidates']} -> {s['recommended']}")
    print(f"  exit conditions          {s['conditions']}")
    print(f"  recommended nothing      {s['cases_recommending_nothing']}/{s['cases']}")
    print()
    print(f"  HARD FAILURES            {s['hard_failures']}   (any non-zero is a bug)")
    print()
    print("  SOFT SIGNALS")
    print(f"    unfalsifiable exits    {s['unfalsifiable']}")
    print(f"    conditions citing an article  {s['conditions_citing_articles']}/{s['conditions']}"
          "   (all-metric means the articles went unread)")
    print(f"    advice language        {s['advice_language']}   (not licensed to give it)")
    print(f"    low-tolerance fit      {s['tolerance_flags']}")
    print(f"    conditions discarded   {s['conditions_discarded']}")
    print(f"    exclusions             {s['exclusions']}")
    print("=" * 72)


def main() -> int:
    _force_utf8_output()
    parser = argparse.ArgumentParser(description="Score Agent 5 on process quality.")
    parser.add_argument("--case", help="run only this profile")
    parser.add_argument("--limit", type=int, default=2,
                        help="how many profiles (default 2 - the most expensive "
                             "eval in the project)")
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
    from agents.decide_agent import decide
    from agents.research_agent import research_themes
    from agents.risk_agent import critique_companies

    print(f"Running Agent 2 -> 3 -> 4 -> 5 for {len(cases)} profile(s).")
    print(f"Pacing {args.delay}s apart to stay inside the free tier's quotas.\n")

    rows: list[dict] = []
    for index, case in enumerate(cases, start=1):
        print(f"  {index}/{len(cases)}  {case.name} ...", flush=True)
        try:
            cache = not args.no_cache
            research = research_themes(case.profile, use_cache=cache)
            time.sleep(min(args.delay, 30))
            companies = analyse_companies(research, use_cache=cache)
            time.sleep(min(args.delay, 30))
            risks = critique_companies(companies, use_cache=cache)
            time.sleep(min(args.delay, 30))
            decision = decide(companies, risks, case.profile)
            rows.append(score_run(case, companies, risks, decision))
        except Exception as exc:  # noqa: BLE001 - a failed run is a result
            rows.append({
                "case": case.name, "error": f"{type(exc).__name__}: {exc}",
                "candidates": 0, "recommended": 0, "excluded": 0, "conditions": 0,
                "untraceable": [], "unearned": [], "restriction_breaches": [],
                "over_cap": False, "unaccounted": [], "ungrounded_conditions": [],
                "provenance_mismatches": [], "nothing_unexplained": False,
                "already_met_conditions": [], "conditions_citing_articles": 0,
                "articles_available": 0,
                "conditions_per_rec": 0.0, "unfalsifiable": [],
                "advice_language": [], "tolerance_flags": [],
                "conditions_discarded": 0, "exclusion_summary": {},
                "recommended_nothing": False, "no_recommendation_reason": None,
                "briefs": [], "notes": None,
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
        path = RESULTS_DIR / f"decisions-{stamp}.json"
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
