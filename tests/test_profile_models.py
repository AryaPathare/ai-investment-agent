"""Tests for the Agent 1 output models.

Two things are being protected here:

1. ProfileAssessment is a TRUST BOUNDARY. Its contents come from an LLM and are
   used to steer control flow, so incoherent combinations must be rejected
   before they can reach the workflow.
2. build_profile must never let the model alter user data outside the narrow
   whitelist of fields a clarification can legitimately change.
"""

import pytest
from pydantic import ValidationError

from models.profile import InvestorProfile, ProfileAssessment, build_profile
from models.user_input import UserInput

# --- ProfileAssessment: the trust boundary ----------------------------------


def test_valid_assessment_needs_no_reason():
    assert ProfileAssessment(status="valid").clarification_reason is None


def test_clarification_requires_a_reason():
    """Without this, the user would be shown a prompt reading literally 'None'."""
    with pytest.raises(ValidationError, match="clarification_reason is required"):
        ProfileAssessment(status="needs_clarification")


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_clarification_reason_cannot_be_blank(blank):
    with pytest.raises(ValidationError, match="clarification_reason is required"):
        ProfileAssessment(status="needs_clarification", clarification_reason=blank)


def test_valid_status_cannot_carry_a_reason():
    with pytest.raises(ValidationError, match="must be null"):
        ProfileAssessment(status="valid", clarification_reason="something")


def test_rejects_unknown_status():
    with pytest.raises(ValidationError):
        ProfileAssessment(status="maybe")


def test_model_cannot_emit_user_data_fields():
    """The core protection: fields outside the whitelist do not exist here.

    Age and investment_amount are silently dropped rather than stored, so there
    is no path by which the LLM can propose a change to them.
    """
    assessment = ProfileAssessment(status="valid", age=99, investment_amount=1)
    dumped = assessment.model_dump()
    assert "age" not in dumped
    assert "investment_amount" not in dumped


# --- build_profile: composing the trusted result ----------------------------


def test_untouchable_fields_are_copied_verbatim(conflicted_user):
    """Even a model trying to revise everything cannot alter these."""
    assessment = ProfileAssessment(
        status="valid",
        revised_sectors_of_interest=["completely", "different"],
        revised_restrictions=["nothing"],
        revised_risk_tolerance="high",
    )
    profile = build_profile(conflicted_user, assessment)

    for field in (
        "age",
        "investment_experience",
        "investment_amount",
        "investment_window",
        "holding_period",
    ):
        assert getattr(profile, field) == getattr(conflicted_user, field)


def test_omitted_revisions_leave_fields_unchanged(conflicted_user):
    profile = build_profile(conflicted_user, ProfileAssessment(status="valid"))
    assert profile.sectors_of_interest == conflicted_user.sectors_of_interest
    assert profile.restrictions == conflicted_user.restrictions
    assert profile.risk_tolerance == conflicted_user.risk_tolerance


# The restriction cases pass a clarification that withdraws the restriction by
# name. Removing one is authorised by the USER's words, so a test about the
# revision MECHANISM has to supply them or it is really testing the guard.
WITHDRAWN = ("I no longer mind technology, drop that one.",)


@pytest.mark.parametrize(
    "revision,field,expected,clarifications",
    [
        ({"revised_restrictions": []}, "restrictions", [], WITHDRAWN),
        ({"revised_sectors_of_interest": ["sports"]}, "sectors_of_interest", ["sports"], ()),
        ({"revised_risk_tolerance": "high"}, "risk_tolerance", "high", ()),
    ],
)
def test_whitelisted_revisions_are_applied(
    conflicted_user, revision, field, expected, clarifications
):
    profile = build_profile(
        conflicted_user, ProfileAssessment(status="valid", **revision), clarifications
    )
    assert getattr(profile, field) == expected


def test_empty_revised_list_is_distinct_from_no_revision(conflicted_user):
    """[] means 'clear it'; None means 'leave it alone'. They must not be confused."""
    cleared = build_profile(
        conflicted_user,
        ProfileAssessment(status="valid", revised_restrictions=[]),
        WITHDRAWN,
    )
    untouched = build_profile(conflicted_user, ProfileAssessment(status="valid"))
    assert cleared.restrictions == []
    assert untouched.restrictions == conflicted_user.restrictions


def test_verdict_carries_into_the_profile(conflicted_user):
    profile = build_profile(
        conflicted_user,
        ProfileAssessment(status="needs_clarification", clarification_reason="conflict"),
    )
    assert profile.status == "needs_clarification"
    assert profile.clarification_reason == "conflict"


# --- The derived property ----------------------------------------------------


def test_needs_clarification_is_derived_from_status(clean_user):
    """One fact, one source of truth — the two can never disagree."""
    blocked = InvestorProfile(
        **clean_user.model_dump(),
        status="needs_clarification",
        clarification_reason="why",
    )
    assert blocked.needs_clarification is True
    assert InvestorProfile(**clean_user.model_dump(), status="valid").needs_clarification is False


# --- Unauthorised removal of a restriction -----------------------------------
#
# From the hard eval case hard_clarification_defers_the_choice_back, run
# against the real model for the first time on 2026-08-24. Told "Either way is
# fine, you choose", it returned revised_restrictions=[] with status "valid" -
# deleting a prohibition the user had stated, recording no reason, and sending
# every downstream agent to research the forbidden sector.


def test_a_restriction_survives_a_reply_that_never_mentions_it(conflicted_user):
    """THE case. The user handed the decision back; that is not a withdrawal."""
    profile = build_profile(
        conflicted_user,
        ProfileAssessment(status="valid", revised_restrictions=[]),
        ("Either way is fine, you choose.",),
    )
    assert profile.restrictions == conflicted_user.restrictions


def test_a_restriction_survives_when_there_were_no_clarifications_at_all(
    conflicted_user,
):
    """Nothing the user said can authorise a removal if they said nothing."""
    profile = build_profile(
        conflicted_user, ProfileAssessment(status="valid", revised_restrictions=[])
    )
    assert profile.restrictions == conflicted_user.restrictions


def test_the_model_cannot_authorise_its_own_deletion(conflicted_user):
    """The check reads the USER's replies, never the model's account of them.

    A fluent clarification_reason naming the restriction must not count, or the
    guard is one sentence of generated text away from being useless.
    """
    profile = build_profile(
        conflicted_user,
        ProfileAssessment(
            status="valid",
            revised_restrictions=[],
            clarification_reason=None,
        ),
        (),
    )
    assert profile.restrictions == conflicted_user.restrictions


def test_a_real_withdrawal_is_honoured(conflicted_user):
    """The guard must not trap a user who genuinely changed their mind."""
    profile = build_profile(
        conflicted_user,
        ProfileAssessment(status="valid", revised_restrictions=[]),
        ("Actually I don't mind technology after all.",),
    )
    assert profile.restrictions == []


def test_only_the_restriction_the_user_raised_is_removable():
    """Two restrictions, one mentioned. The other is not collateral."""
    user = UserInput(
        age=30,
        investment_experience="intermediate",
        risk_tolerance="moderate",
        investment_amount=5000.0,
        investment_window="within 3 months",
        holding_period="3-5 years",
        sectors_of_interest=["technology"],
        restrictions=["Do not invest in technology companies", "No tobacco"],
    )
    profile = build_profile(
        user,
        ProfileAssessment(status="valid", revised_restrictions=[]),
        ("I don't mind technology now.",),
    )
    assert profile.restrictions == ["No tobacco"]


def test_adding_a_restriction_needs_no_authorisation(conflicted_user):
    """Removals are the dangerous direction. Additions are not gated."""
    profile = build_profile(
        conflicted_user,
        ProfileAssessment(
            status="valid",
            revised_restrictions=[*conflicted_user.restrictions, "No tobacco"],
        ),
    )
    assert "No tobacco" in profile.restrictions
    assert set(conflicted_user.restrictions) <= set(profile.restrictions)
