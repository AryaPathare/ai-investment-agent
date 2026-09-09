"""Nothing declared "not source" may be tracked, wherever it has moved to.

WHY THIS EXISTS

`.gitignore` said `evals/results/`. A pattern containing a slash is anchored to
the directory holding the ignore file, so it matched `<root>/evals/results/` and
nothing else. Session 22 moved `evals/` into `backend/`, the pattern silently
stopped matching, and a `git add -A` committed 37 eval artifacts into a public
repository that had deliberately never tracked them - entry 40's publication
audit had recorded them as clean.

Nothing failed. The rule was still correct, still readable, and pointed at a
path that no longer existed. That is the same shape as `render.yaml` pinning a
Python version through a key Render does not define, and as the exit condition
that was already true the moment it was written: **a guard keeps looking right
long after the thing it guards has moved.**

WHAT THIS CHECKS, AND WHAT IT CANNOT

It asks git what is tracked, which is the only authority on the question - the
ignore file is a claim about intent and `git ls-files` is the outcome. It does
NOT verify that the ignore patterns are well written, only that nothing has
slipped through them. A file force-added with `git add -f` would be caught here
and would be invisible to any check that only read `.gitignore`.
"""

import subprocess

import pytest

from backend.config import PROJECT_ROOT

NOT_SOURCE = {
    "evals/results/": (
        "eval run artifacts, re-runnable; they are model output and a record of "
        "measurements, not code, and 37 of them reached a public repo once"
    ),
    ".cache/": "cached provider responses, re-fetchable",
    ".state/": "saved runs and the quota ledger, machine-local",
    "mine.json": (
        "a personal saved profile - an age, an amount of money and a risk "
        "tolerance"
    ),
}


def _tracked() -> list[str]:
    """Every path git is tracking, as forward-slash relative paths."""
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip("not a git checkout, so there is nothing to ask git about")
    return [line for line in result.stdout.splitlines() if line]


def test_git_is_tracking_something_at_all():
    """A guard whose query returns nothing would pass forever and prove nothing.

    If `git ls-files` came back empty - wrong directory, a broken checkout - then
    every assertion below would hold vacuously and this file would be evidence
    of a property it never checked.
    """
    assert len(_tracked()) > 100, "git reported almost nothing; the query is wrong"


@pytest.mark.parametrize("fragment", sorted(NOT_SOURCE))
def test_nothing_declared_not_source_is_tracked(fragment):
    """Wherever these end up in the tree, they must not be committed."""
    offenders = [path for path in _tracked() if fragment in path]

    assert not offenders, (
        f"{len(offenders)} tracked file(s) match {fragment!r} "
        f"({NOT_SOURCE[fragment]}).\n"
        f"First few: {offenders[:5]}\n"
        "Either .gitignore no longer matches where this lives - patterns with a "
        "slash are anchored to the repository root, so use **/ - or something "
        "was added with `git add -f`."
    )
