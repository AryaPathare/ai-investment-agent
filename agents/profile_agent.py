"""Agent 1 — Investor Profile & Validation.

Reviews the investor information the user supplied and decides whether it is
internally coherent. It does not recommend investments and does not rewrite the
user's answers; see models/profile.py for why that separation matters.
"""

from collections.abc import Sequence
from functools import lru_cache

from agents.structured import invoke_structured
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

3. Check whether any restriction directly conflicts with a stated sector.
   For example:
     sectors_of_interest = ["technology"]
     restrictions = ["Do not invest in technology companies"]
   This needs clarification, because the system must not research an area the
   user has also explicitly prohibited.

4. Do not flag harmless differences as contradictions.

5. Never recommend stocks or give investment advice. You only validate.

EXAMPLES THAT NEED CLARIFICATION

- risk_tolerance = "low" while another answer explicitly asks for extremely
  speculative or very high-risk investments.
- sectors_of_interest includes "technology" while restrictions explicitly say not to
  invest in technology companies.

EXAMPLES THAT DO NOT NEED CLARIFICATION

- investment_window = "within 1 month" and holding_period = "3-5 years"
- beginner experience combined with a long holding period

APPLYING A CLARIFICATION

If the user has replied to previous clarification requests, use their answers to
resolve the conflict and return status = "valid".

To record the resolution, set only the fields that actually changed:
  - revised_sectors_of_interest
  - revised_restrictions
  - revised_risk_tolerance

Leave every revised_* field null when nothing changed. Never use them to tidy
up wording, reorder items, or make edits the user did not ask for. They exist
solely to record what a clarification resolved.

WHICH SIDE OF A CONFLICT MAY BE RESOLVED AWAY

A restriction and an interest are not equal. An interest is something the user
would like; a restriction is something they refused. When a clarification
resolves a conflict between them WITHOUT saying which to keep, narrow the
sectors and leave the restriction standing. Never the reverse.

Only remove a restriction when the user's own reply is about that restriction
and withdraws it — "actually I don't mind technology". A reply that hands the
decision back is not a withdrawal.

HANDING THE DECISION BACK IS NOT A RESOLUTION

"Either way is fine", "you choose", "whatever you think", "I don't mind, you
decide" — none of these resolve a conflict between two things the user
themselves stated. Only they can say which of their own answers to keep, and
choosing for them silently overrides one of them. Keep
status = "needs_clarification" and ask which one they want to keep, naming both.

If their replies do not actually resolve the conflict — for example they are
off-topic, or say they are unsure — keep status = "needs_clarification" and
write a clarification_reason that asks more specifically.
"""


def create_investor_profile(
    user_input: UserInput,
    clarifications: Sequence[str] | None = None,
) -> InvestorProfile:
    """Validate a user's investor information and return a usable profile.

    Args:
        user_input: The investor's own answers, already validated by Pydantic.
        clarifications: Every reply the user has given to previous clarification
            requests, oldest first. All of them are sent, not just the latest —
            a later answer may only make sense in light of an earlier one, and
            sending just the most recent caused the agent to forget context and
            re-raise conflicts the user had already resolved.

    Returns:
        An InvestorProfile assembled from ``user_input``, carrying the model's
        verdict. If it needs clarification, ``profile.needs_clarification`` is
        True and ``clarification_reason`` explains why.

    Raises:
        Exception: Propagated from the model call if it fails after its
            configured retries. The workflow catches this; see workflow.py.
    """
    user_message = (
        f"Review this investor information:\n"
        f"{user_input.model_dump_json(indent=2)}"
    )

    if clarifications:
        numbered = "\n".join(
            f"{i}. {text}" for i, text in enumerate(clarifications, start=1)
        )
        user_message += (
            f"\n\nThe user has already answered {len(clarifications)} "
            f"clarification request(s), oldest first:\n{numbered}\n\n"
            "Use these to resolve the conflict. They override the conflicting "
            "original answers. Record the resulting changes using the revised_* "
            "fields, and do not change unrelated information. If they still do "
            "not resolve the conflict, ask again more specifically."
        )

    messages = [
        ("system", SYSTEM_PROMPT),
        ("human", user_message),
    ]

    # ProfileAssessment wraps no list, so there is no bare-list case to
    # recover; salvage still helps when the model returns a valid object that
    # the provider rejected for envelope reasons. No empty_default: a blank
    # verdict on a profile is never correct.
    assessment = invoke_structured(
        _structured_llm(), messages, ProfileAssessment
    )

    # The model returned a judgment. Python builds the actual profile, copying
    # every field the model was not permitted to touch. The clarifications go
    # too: dropping a restriction is checked against what the USER said, not
    # against the model's account of it.
    return build_profile(user_input, assessment, clarifications or ())
