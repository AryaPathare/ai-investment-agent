"""Agent 1 — Investor Profile & Validation.

Reviews the investor information the user supplied and decides whether it is
internally coherent. It does not recommend investments and does not rewrite the
user's answers; see models/profile.py for why that separation matters.
"""

from functools import lru_cache

from config import get_llm
from models.profile import InvestorProfile, ProfileAssessment, build_profile
from models.user_input import UserInput


@lru_cache(maxsize=1)
def _structured_llm():
    """Return the model wired to emit a ProfileAssessment.

    This is a function rather than a module-level variable on purpose. Writing

        structured_llm = get_llm().with_structured_output(ProfileAssessment)

    at the top of the file would call get_llm() at import time, which would
    demand an API key just to import this module — exactly the problem config.py
    was written to remove. Building it inside a cached function keeps the work
    lazy (nothing happens until the first real call) while still doing it only
    once per process.
    """
    return get_llm().with_structured_output(ProfileAssessment)


# Note what is NOT in this prompt any more: the old rule 1, "Preserve the user's
# information. Do not invent new preferences."
#
# That rule existed to stop the model corrupting user data — a risk created by
# handing it the full profile schema. The model can no longer emit those fields
# at all, so the rule is enforced by the type system instead of requested in
# English. A structural guarantee beats an instruction the model may ignore.
SYSTEM_PROMPT = """
You are the Investor Profile Agent in an investment research system.

Your job is to judge whether the investor information you are given is
internally consistent. You do not rewrite the user's answers and you do not
recommend investments.

WHAT TO DECIDE

Return status = "valid" when the profile is coherent and can be used as-is.

Return status = "needs_clarification" only when two answers genuinely cannot
both be true, so that only the user can resolve it. Then set
clarification_reason to one short sentence naming exactly what conflicts.

RULES

1. Investment window and holding period describe different things:
   - investment_window is when the user plans to buy.
   - holding_period is how long they plan to hold after buying.
   These are NOT contradictory just because the timeframes differ.

2. Only flag a contradiction when two answers genuinely cannot reasonably be
   true at the same time. Do not invent contradictions from assumptions.

3. Check whether any restriction directly conflicts with a stated interest.
   For example:
     interests = ["technology"]
     restrictions = ["Do not invest in technology companies"]
   This needs clarification, because the system must not research an area the
   user has also explicitly prohibited.

4. Do not flag harmless differences as contradictions.

5. Never recommend stocks or give investment advice. You only validate.

EXAMPLES THAT NEED CLARIFICATION

- risk_tolerance = "low" while another answer explicitly asks for extremely
  speculative or very high-risk investments.
- interests includes "technology" while restrictions explicitly say not to
  invest in technology companies.

EXAMPLES THAT DO NOT NEED CLARIFICATION

- investment_window = "within 1 month" and holding_period = "3-5 years"
- beginner experience combined with a long holding period

APPLYING A CLARIFICATION

If the user has replied to a previous clarification request, use their answer to
resolve the conflict and return status = "valid".

To record the resolution, set only the fields that actually changed:
  - revised_interests
  - revised_restrictions
  - revised_risk_tolerance

Leave every revised_* field null when nothing changed. Never use them to tidy
up wording, reorder items, or make edits the user did not ask for. They exist
solely to record what a clarification resolved.

If the user's reply does not actually resolve the conflict — for example it is
off-topic, or says they are unsure — keep status = "needs_clarification" and
write a clarification_reason that asks more specifically.
"""


def create_investor_profile(
    user_input: UserInput,
    clarification: str | None = None,
) -> InvestorProfile:
    """Validate a user's investor information and return a usable profile.

    Args:
        user_input: The investor's own answers, already validated by Pydantic.
        clarification: The user's free-text reply to a previous clarification
            request, if there was one.

    Returns:
        An InvestorProfile assembled from ``user_input``, carrying the model's
        verdict. If it needs clarification, ``profile.needs_clarification`` is
        True and ``clarification_reason`` explains why.
    """
    user_message = (
        f"Review this investor information:\n"
        f"{user_input.model_dump_json(indent=2)}"
    )

    if clarification:
        user_message += (
            f"\n\nThe user provided this clarification after a conflict was "
            f"detected:\n{clarification}\n\n"
            "Use this clarification to resolve the conflict. The clarification "
            "overrides the conflicting original answer. Record the change using "
            "the revised_* fields, and do not change unrelated information."
        )

    messages = [
        ("system", SYSTEM_PROMPT),
        ("human", user_message),
    ]

    assessment = _structured_llm().invoke(messages)

    # The model returned a judgment. Python builds the actual profile, copying
    # every field the model was not permitted to touch.
    return build_profile(user_input, assessment)
