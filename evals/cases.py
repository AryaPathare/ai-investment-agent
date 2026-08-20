"""Labelled test cases for Agent 1.

WHY THIS EXISTS
---------------
The pytest suite proves the CODE is correct. It cannot tell you whether the
MODEL makes good judgments, because model output is not deterministic and
cannot be asserted on.

This file is the other half: profiles with a known correct answer, run against
the real model and scored for accuracy. It is what lets you change the prompt
and find out whether you improved things or quietly broke something.

The most valuable cases are the REGRESSIONS — bugs already found and fixed.
Nothing else in the codebase stops those from silently coming back.

HOW TO ADD A CASE
-----------------
Every time the agent gets something wrong, add it here with the answer it
should have given. The set only becomes more valuable over time.
"""

from dataclasses import dataclass

from models.profile import ProfileStatus
from models.user_input import UserInput


@dataclass(frozen=True)
class EvalCase:
    """One profile with a known correct verdict."""

    name: str
    why: str
    user: UserInput
    expected_status: ProfileStatus
    clarifications: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


def _user(**overrides) -> UserInput:
    """A reasonable baseline investor; each case overrides what it cares about."""
    base = dict(
        age=30,
        investment_experience="intermediate",
        risk_tolerance="moderate",
        investment_amount=5000.0,
        investment_window="within 3 months",
        holding_period="3-5 years",
        interests=["technology"],
        restrictions=[],
    )
    return UserInput(**{**base, **overrides})


CASES: list[EvalCase] = [
    # -----------------------------------------------------------------------
    # REGRESSIONS — bugs already found and fixed. These must never fail again.
    # -----------------------------------------------------------------------
    EvalCase(
        name="window_vs_holding_period",
        why=(
            "REGRESSION: the agent used to call these contradictory. They are "
            "different concepts - when you buy vs how long you hold."
        ),
        user=_user(investment_window="within 1 month", holding_period="3-5 years"),
        expected_status="valid",
        tags=("regression", "false-positive"),
    ),
    EvalCase(
        name="interest_vs_restriction_conflict",
        why=(
            "REGRESSION: the agent used to MISS this. Researching an area the "
            "user explicitly prohibited is exactly what must not happen."
        ),
        user=_user(
            interests=["sports", "technology"],
            restrictions=["Do not invest in technology companies"],
        ),
        expected_status="needs_clarification",
        tags=("regression", "true-positive"),
    ),
    EvalCase(
        name="beginner_with_long_horizon",
        why="REGRESSION: inexperience and a long holding period are compatible.",
        user=_user(investment_experience="beginner", holding_period="10+ years"),
        expected_status="valid",
        tags=("regression", "false-positive"),
    ),
    # -----------------------------------------------------------------------
    # Should be VALID. The agent must not invent conflicts. Over-flagging is
    # the more annoying failure mode: it interrogates users who gave perfectly
    # sensible answers.
    # -----------------------------------------------------------------------
    EvalCase(
        name="plain_uncontroversial_profile",
        why="Baseline sanity check: nothing here conflicts with anything.",
        user=_user(),
        expected_status="valid",
        tags=("false-positive",),
    ),
    EvalCase(
        name="restriction_unrelated_to_interests",
        why="A restriction touching none of the interests is not a conflict.",
        user=_user(
            interests=["technology"],
            restrictions=["No tobacco companies", "No gambling companies"],
        ),
        expected_status="valid",
        tags=("false-positive",),
    ),
    EvalCase(
        name="high_risk_with_speculative_interest",
        why="High risk tolerance and speculative interests AGREE with each other.",
        user=_user(risk_tolerance="high", interests=["cryptocurrency", "biotech"]),
        expected_status="valid",
        tags=("false-positive",),
    ),
    EvalCase(
        name="low_risk_with_conservative_interests",
        why="Low risk tolerance and conservative interests also agree.",
        user=_user(risk_tolerance="low", interests=["utilities", "dividend stocks"]),
        expected_status="valid",
        tags=("false-positive",),
    ),
    EvalCase(
        name="small_amount_young_investor",
        why="A small amount is a constraint, not a contradiction.",
        user=_user(age=19, investment_amount=100.0, investment_experience="beginner"),
        expected_status="valid",
        tags=("false-positive",),
    ),
    EvalCase(
        name="older_investor_short_horizon",
        why="Near-retirement age with a short horizon is coherent.",
        user=_user(age=68, risk_tolerance="low", holding_period="1-2 years"),
        expected_status="valid",
        tags=("false-positive",),
    ),
    EvalCase(
        name="large_amount_low_risk",
        why="Investing a lot cautiously is a normal combination.",
        user=_user(investment_amount=250000.0, risk_tolerance="low"),
        expected_status="valid",
        tags=("false-positive",),
    ),
    EvalCase(
        name="no_interests_given",
        why="An empty interests list is under-specified, not self-contradictory.",
        user=_user(interests=[]),
        expected_status="valid",
        tags=("edge", "false-positive"),
    ),
    EvalCase(
        name="broad_interests_narrow_restriction",
        why="Restricting one of several interests still leaves work to do.",
        user=_user(
            interests=["technology", "healthcare", "energy"],
            restrictions=["No fossil fuel companies"],
        ),
        expected_status="valid",
        tags=("false-positive",),
    ),
    # -----------------------------------------------------------------------
    # Should NEED CLARIFICATION — genuine contradictions.
    # -----------------------------------------------------------------------
    EvalCase(
        name="low_risk_wants_speculative",
        why="Stated low risk tolerance directly contradicts wanting speculation.",
        user=_user(
            risk_tolerance="low",
            interests=["extremely speculative penny stocks", "high-risk crypto"],
        ),
        expected_status="needs_clarification",
        tags=("true-positive",),
    ),
    EvalCase(
        name="restriction_blocks_every_interest",
        why="If everything they want is forbidden, there is nothing left to research.",
        user=_user(
            interests=["renewable energy"],
            restrictions=["Do not invest in renewable energy or energy companies"],
        ),
        expected_status="needs_clarification",
        tags=("true-positive",),
    ),
    EvalCase(
        name="restriction_contradicts_one_of_two_interests",
        why="A conflict on one interest still needs resolving before research.",
        user=_user(
            interests=["healthcare", "pharmaceuticals"],
            restrictions=["Never invest in pharmaceutical companies"],
        ),
        expected_status="needs_clarification",
        tags=("true-positive",),
    ),
    # -----------------------------------------------------------------------
    # Clarification handling — the second pass through the agent.
    # -----------------------------------------------------------------------
    EvalCase(
        name="clarification_resolves_conflict",
        why="A clear answer must resolve the conflict and produce a valid profile.",
        user=_user(
            interests=["sports", "technology"],
            restrictions=["Do not invest in technology companies"],
        ),
        clarifications=(
            "I do want to invest in technology companies. Remove the restriction.",
        ),
        expected_status="valid",
        tags=("clarification",),
    ),
    EvalCase(
        name="unhelpful_clarification_keeps_asking",
        why=(
            "A non-answer must NOT be treated as resolution. Accepting it would "
            "let a contradictory profile through to Agent 2."
        ),
        user=_user(
            interests=["sports", "technology"],
            restrictions=["Do not invest in technology companies"],
        ),
        clarifications=("I do not know", "not sure"),
        expected_status="needs_clarification",
        tags=("clarification", "edge"),
    ),
    EvalCase(
        name="clarification_drops_the_interest_instead",
        why="A conflict can be resolved either way; dropping the interest is valid.",
        user=_user(
            interests=["sports", "technology"],
            restrictions=["Do not invest in technology companies"],
        ),
        clarifications=(
            "Keep the restriction. I do not want technology. Only sports.",
        ),
        expected_status="valid",
        tags=("clarification",),
    ),
]
