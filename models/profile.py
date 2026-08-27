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
re-emitted the user's age, amount, sectors_of_interest and restrictions on every call —
and could silently alter any of them. A dropped sector or a rounded investment
amount would have passed through unnoticed.

Now the model returns only ``ProfileAssessment``. Age, experience, amount,
investment window and holding period are copied straight from ``UserInput`` by
Python and are structurally impossible for the LLM to change.

Note that ``InvestorProfile`` still *inherits* from ``UserInput``. Inheritance
was never the problem — using it as the model's output schema was. Keeping it
avoids restating eight field definitions.
"""

import re
from collections.abc import Sequence
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
    # These are the fields where contradictions actually occur: a sector that
    # conflicts with a restriction, or a stated risk tolerance that conflicts
    # with what the user says they want. Numeric and timing fields are already
    # validated by UserInput and have no business being rewritten by an LLM.

    revised_sectors_of_interest: list[str] | None = Field(
        default=None,
        description=(
            "Updated sectors_of_interest, ONLY if a user clarification changed them. "
            "Leave null otherwise."
        ),
    )

    sectors_were_vague: bool = Field(
        default=False,
        description=(
            "True when the investor named no researchable sector at all - "
            "'anything', 'whatever makes the most money', 'you decide'. Set "
            "revised_sectors_of_interest to the concrete sectors you chose. "
            "This is NOT for a sector that is merely broad: 'technology' is a "
            "real sector and must be left alone."
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
    def check_vague_sectors_carry_a_replacement(self) -> "ProfileAssessment":
        """A claim that the sectors were vague must come with the substitute.

        The same trust boundary as the check below. "The sectors were vague"
        with nothing to research instead is not a verdict, it is a shrug - and
        it would reach Agent 2 as the original unusable answer with a flag
        nobody acts on.
        """
        if self.sectors_were_vague and not [
            sector for sector in (self.revised_sectors_of_interest or [])
            if sector.strip()
        ]:
            raise ValueError(
                "sectors_were_vague is True but revised_sectors_of_interest "
                "supplies nothing to research instead"
            )
        return self

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


# Words that appear in almost every restriction and so cannot show that a
# clarification is ABOUT one. "Do not invest in technology companies" is only
# identified by "technology"; everything else is grammar.
_RESTRICTION_BOILERPLATE = {
    "do", "does", "not", "no", "none", "never", "avoid", "exclude", "excluding",
    "invest", "investing", "investment", "investments", "in", "into", "any",
    "all", "the", "a", "an", "and", "or", "of", "with", "that", "please",
    "company", "companies", "stock", "stocks", "share", "shares", "sector",
    "sectors", "business", "businesses", "want", "dont",
}


def _subject_words(text: str) -> set[str]:
    """The words in ``text`` that could identify WHAT a restriction is about."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _RESTRICTION_BOILERPLATE}


def _user_mentioned(restriction: str, clarifications: Sequence[str]) -> bool:
    """Whether the user's own replies refer to this restriction at all.

    Deliberately generous - a single shared subject word counts - because this
    gates a SAFETY check, and the failure to avoid is refusing a withdrawal the
    user really did make. What it will not accept is a reply that never touches
    the subject, which is the case that produced the bug.
    """
    subject = _subject_words(restriction)
    if not subject:
        return True  # Nothing identifiable in it; not this guard's business.
    return any(subject & _subject_words(reply) for reply in clarifications)


def _restrictions_after_revision(
    original: list[str],
    revised: list[str],
    clarifications: Sequence[str],
) -> list[str]:
    """Apply a revision to the restrictions, refusing UNAUTHORISED removals.

    Found on 2026-08-24 by the hard eval case
    ``hard_clarification_defers_the_choice_back``. Asked to pick between an
    interest and a restriction that contradict each other, and told "Either way
    is fine, you choose", the model returned ``revised_restrictions=[]`` with
    status "valid". It deleted "Do not invest in technology companies" and every
    downstream agent then researched technology for somebody who had forbidden
    it. No reason was recorded, because nothing required one.

    Of the two ways to resolve that conflict - drop the interest or drop the
    prohibition - only one can hurt the user, and the model chose it.

    So removals are conditional and additions are not. A restriction survives
    unless the user's own replies mention what it is about. **The check is on
    the USER's words, never the model's**, which is what stops a fluent
    explanation from authorising its own deletion.

    A withdrawal the user really did make still works: "actually I don't mind
    technology" shares "technology" with the restriction and is honoured.
    """
    kept = list(revised)
    for restriction in original:
        if restriction in kept:
            continue
        if _user_mentioned(restriction, clarifications):
            continue  # The user raised it; the model may act on it.
        kept.append(restriction)
    return kept


# How many sectors a VAGUE answer may be turned into. Only that case: a user
# who names five real sectors gets five.
#
# "Anything" is an invitation to research everything, and Agent 2 accepted it
# once - six queries across AI chips, gene therapy, EV batteries, crypto and
# fintech, which handed Agent 3 six companies from three unrelated industries
# and killed the run. Breadth chosen by a model on no information is not
# coverage, it is dilution: the same request budget spread across unrelated
# fields returns three articles about each instead of a usable pool about one.
MAX_SECTORS_FROM_VAGUE = 2


def build_profile(
    user_input: UserInput,
    assessment: ProfileAssessment,
    clarifications: Sequence[str] = (),
) -> InvestorProfile:
    """Combine trusted user input with the LLM's assessment.

    Every field starts as the user's own answer. Only the three whitelisted
    fields can be overridden, and only when the assessment explicitly supplies
    a revision. The model has no path to alter anything else.

    A restriction is the one revision that can HARM the user, so it carries an
    extra condition: it may only be dropped if the user's own replies mention
    what it is about. See ``_restrictions_after_revision``.

    Sectors carry a different condition, and only when the model reports the
    user named none: the substitute is capped at ``MAX_SECTORS_FROM_VAGUE``, so
    "anything" cannot become a research budget spread across six unrelated
    industries.
    """
    data = user_input.model_dump()

    if assessment.revised_sectors_of_interest is not None:
        sectors = assessment.revised_sectors_of_interest
        # The cap applies ONLY to sectors the model substituted for a vague
        # answer. A revision that came out of a real clarification is the user's
        # own decision and is not trimmed.
        if assessment.sectors_were_vague:
            sectors = sectors[:MAX_SECTORS_FROM_VAGUE]
        data["sectors_of_interest"] = sectors

    if assessment.revised_restrictions is not None:
        data["restrictions"] = _restrictions_after_revision(
            user_input.restrictions, assessment.revised_restrictions, clarifications
        )

    if assessment.revised_risk_tolerance is not None:
        data["risk_tolerance"] = assessment.revised_risk_tolerance

    return InvestorProfile(
        **data,
        status=assessment.status,
        clarification_reason=assessment.clarification_reason,
    )
