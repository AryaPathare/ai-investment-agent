"""Agent 1 output models.

Two distinct objects live here, and the split is the important idea:

``ProfileAssessment``
    What the LLM produces. A *judgment* — is this profile coherent, and if not,
    why — plus optional revisions to the small set of fields a clarification can
    legitimately change.

``InvestorProfile``
    What the rest of the system consumes. Built by Python in ``build_profile()``
    by combining the trusted ``UserInput`` with the assessment.

Why they are separate
---------------------
``InvestorProfile`` used to be the schema handed to ``with_structured_output()``.
Because it inherits every field from ``UserInput``, that meant the model
re-emitted the user's age, amount, interests and restrictions on every call —
and could silently alter any of them. A dropped interest or a rounded investment
amount would have passed through unnoticed.

Now the model returns only ``ProfileAssessment``. Age, experience, amount,
investment window and holding period are copied straight from ``UserInput`` by
Python and are structurally impossible for the LLM to change.

Note that ``InvestorProfile`` still *inherits* from ``UserInput``. Inheritance
was never the problem — using it as the model's output schema was. Keeping it
avoids restating eight field definitions.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from models.user_input import UserInput

ProfileStatus = Literal["valid", "needs_clarification"]


class ProfileAssessment(BaseModel):
    """The LLM's verdict on a profile. Contains judgment, not user data."""

    status: ProfileStatus = Field(
        description=(
            "'valid' if the profile is coherent and can be used as-is. "
            "'needs_clarification' if two answers genuinely contradict each "
            "other and only the user can resolve it."
        )
    )

    clarification_reason: str | None = Field(
        default=None,
        description=(
            "Required when status is 'needs_clarification': one short sentence "
            "naming exactly what conflicts. Must be null when status is 'valid'."
        ),
    )

    # --- Revisions -----------------------------------------------------------
    # The ONLY fields the model may change, and only when a user clarification
    # has resolved a conflict. Everything else is copied from UserInput.
    #
    # These are the fields where contradictions actually occur: an interest that
    # conflicts with a restriction, or a stated risk tolerance that conflicts
    # with what the user says they want. Numeric and timing fields are already
    # validated by UserInput and have no business being rewritten by an LLM.

    revised_interests: list[str] | None = Field(
        default=None,
        description=(
            "Updated interests, ONLY if a user clarification changed them. "
            "Leave null otherwise."
        ),
    )

    revised_restrictions: list[str] | None = Field(
        default=None,
        description=(
            "Updated restrictions, ONLY if a user clarification changed them. "
            "Leave null otherwise."
        ),
    )

    revised_risk_tolerance: Literal["low", "moderate", "high"] | None = Field(
        default=None,
        description=(
            "Updated risk tolerance, ONLY if a user clarification changed it. "
            "Leave null otherwise."
        ),
    )

    @model_validator(mode="after")
    def check_reason_matches_status(self) -> "ProfileAssessment":
        """Reject responses where status and reason disagree.

        This is a trust boundary. LLM output steers the workflow's control flow,
        so it gets validated as strictly as any untrusted input. Without this, a
        model could return status='needs_clarification' with no reason, and the
        user would be shown a clarification prompt saying "None".
        """
        if self.status == "needs_clarification" and not (
            self.clarification_reason and self.clarification_reason.strip()
        ):
            raise ValueError(
                "clarification_reason is required when status is "
                "'needs_clarification'"
            )

        if self.status == "valid" and self.clarification_reason:
            raise ValueError(
                "clarification_reason must be null when status is 'valid'"
            )

        return self


class InvestorProfile(UserInput):
    """A validated investor profile, assembled by Python from trusted input.

    Inherits every field from ``UserInput`` and adds the validation outcome.
    Downstream agents (2 onward) consume this.
    """

    status: ProfileStatus = Field(
        description="Outcome of Agent 1's validation."
    )

    clarification_reason: str | None = Field(
        default=None,
        description="Present only when status is 'needs_clarification'.",
    )

    @property
    def needs_clarification(self) -> bool:
        """Whether the workflow must pause and ask the user.

        Derived from ``status`` rather than stored separately. The old model had
        both a ``profile_status`` field and a ``clarification_needed`` boolean,
        which meant the two could disagree — one fact, two sources of truth.
        Computing it removes that possibility entirely.
        """
        return self.status == "needs_clarification"


def build_profile(
    user_input: UserInput,
    assessment: ProfileAssessment,
) -> InvestorProfile:
    """Combine trusted user input with the LLM's assessment.

    Every field starts as the user's own answer. Only the three whitelisted
    fields can be overridden, and only when the assessment explicitly supplies
    a revision. The model has no path to alter anything else.
    """
    data = user_input.model_dump()

    if assessment.revised_interests is not None:
        data["interests"] = assessment.revised_interests

    if assessment.revised_restrictions is not None:
        data["restrictions"] = assessment.revised_restrictions

    if assessment.revised_risk_tolerance is not None:
        data["risk_tolerance"] = assessment.revised_risk_tolerance

    return InvestorProfile(
        **data,
        status=assessment.status,
        clarification_reason=assessment.clarification_reason,
    )
