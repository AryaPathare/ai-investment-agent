"""Tests for the Agent 1 eval set itself.

An eval is an instrument, and an instrument can be wrong. Nothing here runs a
model — these check the parts of the eval that are ordinary code, plus the
properties of the case set that would quietly make its number meaningless:

* a scoring rule that mismeasures (the substring trap, below)
* a hard set that is not actually hard to pass
* an expectation attached to a case that can never exercise it

The score this set produces is used to decide whether a prompt change helped.
If the instrument is wrong, every one of those decisions is wrong too, and
nothing downstream would reveal it.
"""

from collections import Counter

import pytest

from evals.cases import CASES, EvalCase, _mentions, check_expectations
from models.profile import InvestorProfile
from models.user_input import UserInput


def _profile(sectors=(), restrictions=(), status="valid") -> InvestorProfile:
    return InvestorProfile(
        age=30,
        investment_experience="intermediate",
        risk_tolerance="moderate",
        investment_amount=5000.0,
        investment_window="within 3 months",
        holding_period="3-5 years",
        sectors_of_interest=list(sectors),
        restrictions=list(restrictions),
        status=status,
    )


def _case(**overrides) -> EvalCase:
    base = dict(
        name="t",
        why="t",
        user=UserInput(
            age=30,
            investment_experience="intermediate",
            risk_tolerance="moderate",
            investment_amount=5000.0,
            investment_window="within 3 months",
            holding_period="3-5 years",
            sectors_of_interest=["technology"],
            restrictions=[],
        ),
        expected_status="valid",
    )
    return EvalCase(**{**base, **overrides})


# --- Matching terms ----------------------------------------------------------


def test_a_term_is_found_as_a_whole_word():
    assert _mentions(["Do not invest in technology companies"], "technology")


def test_matching_ignores_case():
    assert _mentions(["No Technology Companies"], "technology")


def test_a_term_inside_a_longer_word_does_not_count():
    """THE reason this is a regex and not `in`.

    "technology" is a substring of "biotechnology", so a naive check would read
    a biotech restriction as a technology restriction and mark a CORRECT model
    answer as wrong. The project already shipped one naive-substring bug in the
    exclusion check; an instrument carrying the same flaw would generate false
    failures and send someone off fixing a prompt that was fine.
    """
    assert not _mentions(["No biotechnology companies"], "technology")
    assert not _mentions(["No nanotechnology"], "technology")


def test_a_term_is_found_among_several_entries():
    assert _mentions(["sports", "technology", "healthcare"], "technology")


def test_an_empty_field_mentions_nothing():
    assert not _mentions([], "technology")


# --- Checking expectations ---------------------------------------------------


def test_no_expectations_means_nothing_to_report():
    assert check_expectations(_case(), _profile(sectors=["anything"])) == []


def test_a_required_term_that_is_missing_is_reported():
    case = _case(expect_sectors_include=("sports",))
    problems = check_expectations(case, _profile(sectors=["technology"]))
    assert len(problems) == 1
    assert "should still mention 'sports'" in problems[0]


def test_a_forbidden_term_that_is_present_is_reported():
    case = _case(expect_restrictions_exclude=("technology",))
    problems = check_expectations(
        case, _profile(restrictions=["Do not invest in technology companies"])
    )
    assert len(problems) == 1
    assert "should no longer mention 'technology'" in problems[0]


def test_the_two_fields_are_checked_independently():
    """The whole point of splitting them. Dropping the interest and dropping
    the restriction are opposite resolutions of the same conflict, and a check
    over the combined text could not tell them apart."""
    case = _case(
        expect_sectors_exclude=("technology",),
        expect_restrictions_include=("technology",),
    )
    resolved = _profile(
        sectors=["sports"], restrictions=["Do not invest in technology companies"]
    )
    assert check_expectations(case, resolved) == []


def test_every_failing_expectation_is_reported_not_just_the_first():
    """A run costs quota. Reporting one problem at a time would mean paying for
    another run to discover the next one."""
    case = _case(
        expect_sectors_include=("sports",),
        expect_sectors_exclude=("technology",),
        expect_restrictions_include=("crypto",),
    )
    problems = check_expectations(case, _profile(sectors=["technology"]))
    assert len(problems) == 3


def test_the_problem_message_shows_the_actual_values():
    """Without them the reader cannot tell a model failure from a bad label."""
    case = _case(expect_sectors_include=("sports",))
    problems = check_expectations(case, _profile(sectors=["technology", "energy"]))
    assert "technology" in problems[0] and "energy" in problems[0]


# --- Properties of the case set ----------------------------------------------


def test_case_names_are_unique():
    """Results are keyed by name; a duplicate would silently overwrite one."""
    names = [c.name for c in CASES]
    duplicates = [n for n, count in Counter(names).items() if count > 1]
    assert not duplicates


def test_every_case_says_why_it_exists():
    """The `why` is what lets a future reader tell a real model failure from a
    label that was wrong all along."""
    for case in CASES:
        assert len(case.why) > 30, case.name


def test_every_case_carries_at_least_one_tag():
    """An untagged case contributes to the overall number and to no category,
    which is where a systematic failure would hide."""
    for case in CASES:
        assert case.tags, case.name


def test_the_hard_set_is_balanced_between_both_verdicts():
    """THE property that makes the hard set worth having.

    An agent that flags everything, or nothing, must not be able to score well
    on it. Balanced six/six, either degenerate strategy scores exactly 50%.

    The original eighteen were 13 valid to 5 needs_clarification, so answering
    "valid" every single time scored 72% there without reading anything.
    """
    hard = [c for c in CASES if "hard" in c.tags]
    counts = Counter(c.expected_status for c in hard)

    assert len(hard) >= 10, "too few hard cases to measure anything stable"
    assert counts["valid"] == counts["needs_clarification"], counts


def test_every_hard_case_also_carries_a_category_tag():
    """`hard` says how difficult, not what kind. Both are needed to tell
    "misses real conflicts" from "invents conflicts"."""
    categories = {"true-positive", "false-positive", "clarification"}
    for case in CASES:
        if "hard" in case.tags:
            assert categories & set(case.tags), case.name


def test_regressions_are_never_relabelled_as_hard():
    """A regression is a bug that already happened once; it must stay a hard
    failure of its own. Tagging one `hard` would blur it into a set that is
    expected to fail sometimes."""
    for case in CASES:
        if "regression" in case.tags:
            assert "hard" not in case.tags, case.name


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_field_expectations_only_appear_where_they_can_be_exercised(case):
    """An expectation on a case with no clarification is dead weight: the
    profile is copied from the input unchanged, so the check either passes
    trivially or fails for a reason that has nothing to do with the model."""
    has_expectations = any(
        (
            case.expect_sectors_include,
            case.expect_sectors_exclude,
            case.expect_restrictions_include,
            case.expect_restrictions_exclude,
        )
    )
    if has_expectations:
        assert case.clarifications, (
            f"{case.name} asserts on revised fields but sends no clarification, "
            "so nothing can revise them"
        )


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_expectations_do_not_contradict_the_case_input(case):
    """A term required to SURVIVE must have been there to begin with.

    Catches the copy-paste error where a case is adapted from another and an
    expectation is left pointing at a sector the new case never had - which
    would fail forever and look like a model defect.
    """
    for term in case.expect_sectors_include:
        assert _mentions(case.user.sectors_of_interest, term), (
            f"{case.name} expects {term!r} to survive in sectors_of_interest, "
            f"but the input never contained it: {case.user.sectors_of_interest}"
        )
    for term in case.expect_restrictions_include:
        assert _mentions(case.user.restrictions, term), (
            f"{case.name} expects {term!r} to survive in restrictions, but the "
            f"input never contained it: {case.user.restrictions}"
        )
