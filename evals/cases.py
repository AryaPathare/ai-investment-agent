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

import re
from dataclasses import dataclass

from models.profile import InvestorProfile, ProfileStatus
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

    # --- What the clarification should have CHANGED --------------------------
    #
    # The status alone is not enough for a clarification case. "valid" means the
    # model says the conflict is resolved; it does not mean the model actually
    # resolved it. A profile that still lists technology as an interest AND
    # forbids technology, returned as valid, scores as correct against status
    # alone — and it is precisely the failure that would send a contradictory
    # profile to Agent 2, which is what Agent 1 exists to prevent.
    #
    # Terms are matched against the FINAL profile, one field at a time, because
    # "technology gone from restrictions" and "technology gone from interests"
    # are opposite resolutions of the same conflict and both are legitimate.

    expect_sectors_include: tuple[str, ...] = ()
    expect_sectors_exclude: tuple[str, ...] = ()
    expect_restrictions_include: tuple[str, ...] = ()
    expect_restrictions_exclude: tuple[str, ...] = ()


def _mentions(items: list[str], term: str) -> bool:
    """Does any entry mention ``term`` as a whole word?

    Word boundaries, not plain substrings. "technology" is a substring of
    "biotechnology", so a naive check would read "No biotechnology companies" as
    a restriction on technology and score a correct answer as wrong. The project
    has already been bitten once by naive substring matching in the exclusion
    check; there is no reason to repeat it in the instrument that measures it.
    """
    pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
    return any(pattern.search(item) for item in items)


def check_expectations(case: EvalCase, profile: InvestorProfile) -> list[str]:
    """Every way the resulting profile failed the case's field expectations.

    Returns an empty list when there is nothing to check or nothing wrong, so a
    case that only cares about the status is unaffected.
    """
    problems: list[str] = []
    checks = (
        ("sectors_of_interest", profile.sectors_of_interest,
         case.expect_sectors_include, case.expect_sectors_exclude),
        ("restrictions", profile.restrictions,
         case.expect_restrictions_include, case.expect_restrictions_exclude),
    )

    for field, values, required, forbidden in checks:
        for term in required:
            if not _mentions(values, term):
                problems.append(f"{field} should still mention {term!r}: {values}")
        for term in forbidden:
            if _mentions(values, term):
                problems.append(f"{field} should no longer mention {term!r}: {values}")

    return problems


def _user(**overrides) -> UserInput:
    """A reasonable baseline investor; each case overrides what it cares about."""
    base = dict(
        age=30,
        investment_experience="intermediate",
        risk_tolerance="moderate",
        investment_amount=5000.0,
        investment_window="within 3 months",
        holding_period="3-5 years",
        sectors_of_interest=["technology"],
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
            sectors_of_interest=["sports", "technology"],
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
        why="A restriction touching none of the sectors_of_interest is not a conflict.",
        user=_user(
            sectors_of_interest=["technology"],
            restrictions=["No tobacco companies", "No gambling companies"],
        ),
        expected_status="valid",
        tags=("false-positive",),
    ),
    EvalCase(
        name="high_risk_with_speculative_interest",
        why="High risk tolerance and speculative sectors_of_interest AGREE with each other.",
        user=_user(risk_tolerance="high", sectors_of_interest=["cryptocurrency", "biotech"]),
        expected_status="valid",
        tags=("false-positive",),
    ),
    EvalCase(
        name="low_risk_with_conservative_interests",
        why="Low risk tolerance and conservative sectors_of_interest also agree.",
        user=_user(risk_tolerance="low", sectors_of_interest=["utilities", "dividend stocks"]),
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
        why="An empty sectors_of_interest list is under-specified, not self-contradictory.",
        user=_user(sectors_of_interest=[]),
        expected_status="valid",
        tags=("edge", "false-positive"),
    ),
    EvalCase(
        name="broad_interests_narrow_restriction",
        why="Restricting one of several sectors_of_interest still leaves work to do.",
        user=_user(
            sectors_of_interest=["technology", "healthcare", "energy"],
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
            sectors_of_interest=["extremely speculative penny stocks", "high-risk crypto"],
        ),
        expected_status="needs_clarification",
        tags=("true-positive",),
    ),
    EvalCase(
        name="restriction_blocks_every_interest",
        why="If everything they want is forbidden, there is nothing left to research.",
        user=_user(
            sectors_of_interest=["renewable energy"],
            restrictions=["Do not invest in renewable energy or energy companies"],
        ),
        expected_status="needs_clarification",
        tags=("true-positive",),
    ),
    EvalCase(
        name="restriction_contradicts_one_of_two_interests",
        why="A conflict on one interest still needs resolving before research.",
        user=_user(
            sectors_of_interest=["healthcare", "pharmaceuticals"],
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
            sectors_of_interest=["sports", "technology"],
            restrictions=["Do not invest in technology companies"],
        ),
        clarifications=(
            "I do want to invest in technology companies. Remove the restriction.",
        ),
        expected_status="valid",
        # "valid" alone would also be returned by a model that left the
        # restriction in place, which is the failure that matters.
        expect_restrictions_exclude=("technology",),
        expect_sectors_include=("technology", "sports"),
        tags=("clarification",),
    ),
    EvalCase(
        name="unhelpful_clarification_keeps_asking",
        why=(
            "A non-answer must NOT be treated as resolution. Accepting it would "
            "let a contradictory profile through to Agent 2."
        ),
        user=_user(
            sectors_of_interest=["sports", "technology"],
            restrictions=["Do not invest in technology companies"],
        ),
        clarifications=("I do not know", "not sure"),
        expected_status="needs_clarification",
        tags=("clarification", "edge"),
    ),
    # =======================================================================
    # HARD CASES
    #
    # Added 2026-08-23 because the set above scored 18/18, which made it a
    # regression alarm that could not show improvement. Reading it showed why
    # it was easy: EVERY conflict case names the same word twice.
    #
    #     sectors_of_interest = ["technology"]
    #     restrictions        = ["Do not invest in technology companies"]
    #
    # and every valid case is lexically disjoint ("technology" vs tobacco).
    # The prompt gives that exact pattern as its worked example, so a model can
    # score full marks by matching strings and never judging anything.
    #
    # These break the correlation between "shares a word" and "is a conflict"
    # from both ends:
    #
    #   * conflicts with NO shared vocabulary, which a string match misses
    #   * a non-conflict that DOES repeat the sector word, which a string match
    #     flags (hard_restriction_names_the_sector_but_not_all_of_it)
    #   * non-conflicts where the restriction is merely ADJACENT to the sector,
    #     which is the trap for a model that reasons semantically: it narrows
    #     the search without emptying it, and narrow is not contradictory
    #
    # Checked against a deliberately naive string-matching stand-in, which
    # scores 12/12 on the original false-positive cases and 5/12 here. An eval
    # that cannot separate string matching from judgment is not measuring
    # judgment.
    #
    # Cases whose correct answer is genuinely arguable were deliberately left
    # out. A label that cannot be defended from the agent's own stated rules
    # makes the number less trustworthy, not more, and this set's whole job is
    # to be a trustworthy instrument.
    # --- An answer that names no sector at all -------------------------------
    # Found by a real user answering the real CLI, which is the first defect in
    # this project to arrive that way rather than from an eval.

    EvalCase(
        name="vague_sector_is_resolved_not_asked_about",
        why=(
            "REGRESSION: a real user answered 'which sectors interest you?' "
            "with a GOAL. It passed as valid and unchanged, Agent 2 read it as "
            "permission to search everything, and six companies from three "
            "unrelated industries reached Agent 3 and killed the run. Nothing "
            "here CONTRADICTS anything, so it is not a clarification - there is "
            "nothing for the user to reconcile, and asking someone to name a "
            "sector right after they said they do not know is not help."
        ),
        user=_user(sectors_of_interest=["whichever will make me the most money"]),
        expected_status="valid",
        expect_sectors_exclude=("whichever", "money"),
        tags=("regression", "false-positive"),
    ),
    EvalCase(
        name="a_broad_sector_is_left_exactly_alone",
        why=(
            "The false-positive guard for the case above, and the more likely "
            "failure of the two. 'Technology' is broad, and a model told to "
            "replace vague answers will be tempted to sharpen it into "
            "'semiconductors'. Broad is not vague: the user named a real "
            "sector and it is not the agent's to improve."
        ),
        user=_user(sectors_of_interest=["technology"]),
        expected_status="valid",
        expect_sectors_include=("technology",),
        tags=("regression", "false-positive"),
    ),

    # =======================================================================

    # --- Conflicts a string match cannot see --------------------------------
    # The restriction rules out the only interest without repeating its name.

    EvalCase(
        name="hard_restriction_blocks_interest_semantically",
        why=(
            "Coal mining is the interest and environmental damage is the "
            "restriction. Same structure as the technology case, with no word "
            "in common. Requires knowing what coal mining does."
        ),
        user=_user(
            sectors_of_interest=["coal mining"],
            restrictions=["Nothing that damages the environment"],
        ),
        expected_status="needs_clarification",
        tags=("hard", "true-positive"),
    ),
    EvalCase(
        name="hard_defence_versus_profiting_from_war",
        why=(
            "Defence primes build weapons; the restriction rules out profiting "
            "from war. Nothing lexical connects the two answers."
        ),
        user=_user(
            sectors_of_interest=["defence primes"],
            restrictions=["No companies that profit from war"],
        ),
        expected_status="needs_clarification",
        tags=("hard", "true-positive"),
    ),
    EvalCase(
        name="hard_betting_versus_addiction",
        why=(
            "Sports betting is the interest; the restriction rules out "
            "profiting from addiction. The link is real and unstated."
        ),
        user=_user(
            sectors_of_interest=["online sports betting"],
            restrictions=["Nothing that profits from addiction"],
        ),
        expected_status="needs_clarification",
        tags=("hard", "true-positive"),
    ),
    EvalCase(
        name="hard_low_risk_with_implicitly_speculative_sectors",
        why=(
            "Neither SPACs nor pre-revenue biotech contains the word "
            "speculative, unlike the easy case which says so outright. "
            "Recognising them as speculative is the judgment being tested."
        ),
        user=_user(
            risk_tolerance="low",
            sectors_of_interest=["SPACs", "pre-revenue biotech startups"],
        ),
        expected_status="needs_clarification",
        tags=("hard", "true-positive"),
    ),

    # --- Non-conflicts a string match would flag ----------------------------
    # High lexical overlap between interest and restriction, and no conflict:
    # the restriction NARROWS the search rather than emptying it. Getting these
    # wrong means interrogating users who answered perfectly sensibly.

    EvalCase(
        name="hard_restriction_narrows_energy_without_blocking_it",
        why=(
            "Fossil fuels are a subset of energy, so plenty remains to research "
            "- renewables, grid, storage. Tempting to flag because both answers "
            "are obviously about the same industry."
        ),
        user=_user(
            sectors_of_interest=["energy"],
            restrictions=["No fossil fuel companies"],
        ),
        expected_status="valid",
        tags=("hard", "false-positive"),
    ),
    EvalCase(
        name="hard_restriction_names_the_sector_but_not_all_of_it",
        why=(
            "The sharpest probe in the set, and the exact inverse of the "
            "pattern the prompt teaches. The restriction repeats the sector "
            "word - technology appears in both fields - so any string match "
            "flags it. But financial technology is one corner of technology, "
            "and semiconductors, software, hardware and media all remain. "
            "Passing this requires reading the restriction, not matching it."
        ),
        user=_user(
            sectors_of_interest=["technology"],
            restrictions=["No financial technology companies"],
        ),
        expected_status="valid",
        tags=("hard", "false-positive"),
    ),
    EvalCase(
        name="hard_restriction_excludes_one_kind_of_bank",
        why=(
            "Investment banks are one kind of bank. Retail and commercial "
            "banking are untouched, so there is still something to research."
        ),
        user=_user(
            sectors_of_interest=["banking"],
            restrictions=["No investment banks"],
        ),
        expected_status="valid",
        tags=("hard", "false-positive"),
    ),
    EvalCase(
        name="hard_restriction_is_geographic_not_sectoral",
        why=(
            "A country restriction narrows a sector severely without emptying "
            "it: TSMC, ASML, Nvidia and Samsung all remain. Narrow is not the "
            "same as contradictory, and only the user can decide it is too "
            "narrow to be worth doing."
        ),
        user=_user(
            sectors_of_interest=["semiconductors"],
            restrictions=["No companies headquartered in China"],
        ),
        expected_status="valid",
        tags=("hard", "false-positive"),
    ),
    EvalCase(
        name="hard_high_risk_tolerance_with_conservative_sectors",
        why=(
            "Risk tolerance is a CEILING, not a quota. Being willing to take "
            "risk does not oblige anyone to take it, so wanting treasuries "
            "while tolerating risk is coherent. The mirror case - low tolerance "
            "with speculative interests - IS a conflict, and telling the two "
            "apart is the point."
        ),
        user=_user(
            risk_tolerance="high",
            sectors_of_interest=["treasury bonds", "money market funds"],
        ),
        expected_status="valid",
        tags=("hard", "false-positive"),
    ),

    # --- Clarifications that do not resolve anything ------------------------

    EvalCase(
        name="hard_clarification_defers_the_choice_back",
        why=(
            "Deferring the choice back is not a resolution: only the user can "
            "say which of their two answers to keep, and picking for them would "
            "silently override something they stated. Harder than the existing "
            "off-topic case because it sounds cooperative and decisive."
        ),
        user=_user(
            sectors_of_interest=["sports", "technology"],
            restrictions=["Do not invest in technology companies"],
        ),
        clarifications=("Either way is fine, you choose.",),
        expected_status="needs_clarification",
        tags=("hard", "clarification"),
    ),
    EvalCase(
        name="hard_clarification_is_confidently_off_topic",
        why=(
            "A fluent, confident reply that answers a question nobody asked. "
            "The existing off-topic case contains uncertainty words the model "
            "can key on; this one contains none, so the judgment has to be "
            "about relevance rather than about tone."
        ),
        user=_user(
            sectors_of_interest=["sports", "technology"],
            restrictions=["Do not invest in technology companies"],
        ),
        clarifications=(
            "I have been investing for about six years and I follow the market "
            "closely every day.",
        ),
        expected_status="needs_clarification",
        tags=("hard", "clarification"),
    ),
    EvalCase(
        name="hard_second_clarification_resolves_after_a_vague_first",
        why=(
            "Tests that the WHOLE clarification history is used, not just the "
            "latest reply. This is the shape of a real bug: "
            "clarification_responses was once a single string, so a second "
            "answer erased the first. The vague first answer must not poison "
            "the clear second one."
        ),
        user=_user(
            sectors_of_interest=["sports", "technology"],
            restrictions=["Do not invest in technology companies"],
        ),
        clarifications=(
            "Hmm, I am not sure.",
            "Alright - keep the restriction and drop technology. Sports only.",
        ),
        expected_status="valid",
        expect_sectors_exclude=("technology",),
        expect_sectors_include=("sports",),
        tags=("hard", "clarification"),
    ),
    EvalCase(
        name="clarification_drops_the_interest_instead",
        why="A conflict can be resolved either way; dropping the interest is valid.",
        user=_user(
            sectors_of_interest=["sports", "technology"],
            restrictions=["Do not invest in technology companies"],
        ),
        clarifications=(
            "Keep the restriction. I do not want technology. Only sports.",
        ),
        expected_status="valid",
        # The mirror image of the case above: same conflict, opposite
        # resolution. The restriction stays and the interest goes.
        expect_sectors_exclude=("technology",),
        expect_sectors_include=("sports",),
        expect_restrictions_include=("technology",),
        tags=("clarification",),
    ),
]
