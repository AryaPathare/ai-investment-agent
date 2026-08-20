from dotenv import load_dotenv
from langchain_groq import ChatGroq

from models.user_input import UserInput
from models.profile import InvestorProfile


load_dotenv()


llm = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0
)


structured_llm = llm.with_structured_output(InvestorProfile)


SYSTEM_PROMPT = """
You are the Investor Profile Agent in an investment research system.

Your job is to review user-provided investor information and produce
a clean InvestorProfile.

Rules:

1. Preserve the user's information. Do not invent new preferences.

2. Normalize wording when necessary.

3. Investment window and holding period describe different concepts:
   - investment_window means when the user plans to make the investment.
   - holding_period means how long the user plans to keep the investment after buying.
   These values should NOT be treated as contradictory simply because
   their timeframes are different.

4. Only flag a contradiction when two answers genuinely cannot reasonably
   be true at the same time. Do not create contradictions based on assumptions.

5. Check whether any restriction directly conflicts with an interest.
   For example:
   - interests = ["technology"]
   - restrictions = ["Do not invest in technology companies"]

   This requires clarification because the system should not research
   an investment area that the user has also explicitly prohibited.

6. Do not recommend stocks or provide investment advice.

7. If the profile is clear and internally consistent:
   - profile_status = "valid"
   - clarification_needed = false
   - clarification_reason = null

8. If there is a meaningful contradiction or ambiguity:
   - profile_status = "needs_clarification"
   - clarification_needed = true
   - clarification_reason should contain one short sentence explaining
     exactly what needs clarification.

9. Do not flag harmless differences as contradictions.

Examples of profiles that NEED clarification:

- risk_tolerance = "low" while another answer explicitly requests
  extremely speculative or very high-risk investments.

- interests includes "technology" while restrictions explicitly say
  not to invest in technology companies.

Examples that DO NOT need clarification:

- investment_window = "within 1 month" and holding_period = "3-5 years"

- beginner experience with a long holding period
"""


def create_investor_profile(
    user_input: UserInput,
    clarification: str | None = None
) -> InvestorProfile:

    user_message = (
        f"Review this investor information:\n"
        f"{user_input.model_dump_json(indent=2)}"
    )

    if clarification:
        user_message += (
            f"\n\nThe user provided this clarification after a conflict was detected:\n"
            f"{clarification}\n\n"
            "Use this clarification to resolve the conflict. "
            "The clarification overrides the conflicting original answer, "
            "but do not change unrelated information."
        )

    messages = [
        ("system", SYSTEM_PROMPT),
        ("human", user_message)
    ]

    profile = structured_llm.invoke(messages)

    return profile