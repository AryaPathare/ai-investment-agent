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


@pytest.mark.parametrize(
    "revision,field,expected",
    [
        ({"revised_restrictions": []}, "restrictions", []),
        ({"revised_sectors_of_interest": ["sports"]}, "sectors_of_interest", ["sports"]),
        ({"revised_risk_tolerance": "high"}, "risk_tolerance", "high"),
    ],
)
def test_whitelisted_revisions_are_applied(conflicted_user, revision, field, expected):
    profile = build_profile(conflicted_user, ProfileAssessment(status="valid", **revision))
    assert getattr(profile, field) == expected


def test_empty_revised_list_is_distinct_from_no_revision(conflicted_user):
    """[] means 'clear it'; None means 'leave it alone'. They must not be confused."""
    cleared = build_profile(
        conflicted_user, ProfileAssessment(status="valid", revised_restrictions=[])
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
