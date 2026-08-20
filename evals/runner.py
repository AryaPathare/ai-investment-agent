"""Run the Agent 1 eval set against the real model and score the results.

    python -m evals.runner                 # run every case once
    python -m evals.runner --repeat 3      # measure consistency across runs
    python -m evals.runner --tag regression  # only the must-never-break cases
    python -m evals.runner --delay 1.0     # slow down if rate limited

HOW TO READ THE OUTPUT
----------------------
This is NOT a pass/fail test suite. Model output is probabilistic, so accuracy
is a measurement, not a guarantee. Treat the percentage as a number to compare
across prompt changes: run it, change the prompt, run it again, see which way
it moved.

The exception is REGRESSION cases. Those are bugs that were already found and
fixed, so any failure there is a real problem and the runner exits non-zero.

WHY ACCURACY IS SPLIT BY TAG
----------------------------
An agent that flags everything scores 100% on true-positives and 0% on
false-positives. One that flags nothing does the reverse. A single overall
number hides both failures, so the two are reported separately.
"""

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from agents.profile_agent import create_investor_profile
from config import PROJECT_ROOT, get_settings
from evals.cases import CASES, EvalCase

RESULTS_DIR = PROJECT_ROOT / "evals" / "results"


def run_case(case: EvalCase) -> dict:
    """Run one case and record what happened.

    Never raises: a model failure is recorded as an error result so one bad
    call cannot abandon the rest of the run.
    """
    started = time.perf_counter()
    try:
        profile = create_investor_profile(case.user, list(case.clarifications))
    except Exception as exc:  # noqa: BLE001 - a failed call is a result, not a crash
        return {
            "name": case.name,
            "tags": list(case.tags),
            "expected": case.expected_status,
            "actual": None,
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}",
            "seconds": round(time.perf_counter() - started, 2),
        }

    return {
        "name": case.name,
        "tags": list(case.tags),
        "expected": case.expected_status,
        "actual": profile.status,
        "passed": profile.status == case.expected_status,
        "reason": profile.clarification_reason,
        "interests": profile.interests,
        "restrictions": profile.restrictions,
        "error": None,
        "seconds": round(time.perf_counter() - started, 2),
    }


def summarise(results: list[dict]) -> dict:
    """Aggregate results overall and per tag."""
    by_tag: dict[str, Counter] = defaultdict(Counter)
    for r in results:
        for tag in r["tags"]:
            by_tag[tag]["total"] += 1
            by_tag[tag]["passed"] += int(r["passed"])

    passed = sum(r["passed"] for r in results)
    return {
        "total": len(results),
        "passed": passed,
        "accuracy": round(100 * passed / len(results), 1) if results else 0.0,
        "by_tag": {
            tag: {
                "passed": c["passed"],
                "total": c["total"],
                "accuracy": round(100 * c["passed"] / c["total"], 1),
            }
            for tag, c in sorted(by_tag.items())
        },
    }


def print_report(results: list[dict], summary: dict, repeat: int) -> None:
    print()
    print("=" * 72)
    print("RESULTS")
    print("=" * 72)

    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        flag = "  <-- REGRESSION" if not r["passed"] and "regression" in r["tags"] else ""
        print(f"  [{mark}] {r['name']:<44} {r['seconds']:>5.1f}s{flag}")
        if not r["passed"]:
            if r["error"]:
                print(f"         error: {r['error']}")
            else:
                print(f"         expected {r['expected']!r}, got {r['actual']!r}")
                if r.get("reason"):
                    print(f"         model said: {r['reason']}")

    print()
    print("-" * 72)
    print(f"  Overall accuracy: {summary['passed']}/{summary['total']}"
          f"  ({summary['accuracy']}%)")
    if repeat > 1:
        print(f"  (each case run {repeat} times; a case counts as passed only if"
              f" every run agreed)")
    print()
    print("  By category:")
    for tag, stats in summary["by_tag"].items():
        print(f"    {tag:<16} {stats['passed']:>2}/{stats['total']:<3}"
              f" ({stats['accuracy']}%)")
    print("-" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Agent 1 eval set.")
    parser.add_argument("--tag", help="only run cases carrying this tag")
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help=(
            "run each case N times. Measures consistency: with temperature 0 the "
            "model should agree with itself, and disagreement is itself a finding."
        ),
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="seconds to wait between calls, to stay under rate limits",
    )
    parser.add_argument("--no-save", action="store_true", help="do not write a results file")
    args = parser.parse_args()

    cases = [c for c in CASES if not args.tag or args.tag in c.tags]
    if not cases:
        print(f"No cases carry the tag {args.tag!r}.")
        return 1

    settings = get_settings()
    total_calls = len(cases) * args.repeat
    print(f"Running {len(cases)} case(s) x {args.repeat} = {total_calls} model calls")
    print(f"Model: {settings.groq_model} @ temperature {settings.llm_temperature}")
    print()

    results = []
    inconsistent = []

    for i, case in enumerate(cases, start=1):
        runs = []
        for _ in range(args.repeat):
            runs.append(run_case(case))
            if args.delay:
                time.sleep(args.delay)

        # A case only passes if EVERY run got it right. Anything else is either
        # a wrong answer or an unstable one, and both matter.
        merged = runs[0]
        merged["passed"] = all(r["passed"] for r in runs)
        answers = {r["actual"] for r in runs}
        if len(answers) > 1:
            inconsistent.append((case.name, answers))
            merged["inconsistent"] = sorted(str(a) for a in answers)

        results.append(merged)
        mark = "PASS" if merged["passed"] else "FAIL"
        print(f"  {i:>2}/{len(cases)}  [{mark}]  {case.name}")

    summary = summarise(results)
    print_report(results, summary, args.repeat)

    if inconsistent:
        print()
        print("  INCONSISTENT (same input, different answers across runs):")
        for name, answers in inconsistent:
            print(f"    {name}: {sorted(str(a) for a in answers)}")
        print("  Non-determinism at temperature 0 means these cases sit close to")
        print("  the model's decision boundary. They are the ones worth clarifying")
        print("  in the prompt.")

    if not args.no_save:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = RESULTS_DIR / f"{stamp}.json"
        path.write_text(
            json.dumps(
                {
                    "timestamp": stamp,
                    "model": settings.groq_model,
                    "temperature": settings.llm_temperature,
                    "repeat": args.repeat,
                    "summary": summary,
                    "results": results,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n  Saved to {path.relative_to(PROJECT_ROOT)}")

    # Regressions are hard failures: they are bugs that were already fixed once.
    failed_regressions = [
        r for r in results if not r["passed"] and "regression" in r["tags"]
    ]
    if failed_regressions:
        print(f"\n  {len(failed_regressions)} REGRESSION(S) FAILED - a previously"
              f" fixed bug has come back.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
