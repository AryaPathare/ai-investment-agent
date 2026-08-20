from typing import TypedDict

from models.user_input import UserInput
from models.profile import InvestorProfile


class InvestmentState(TypedDict, total=False):
    user_input: UserInput
    investor_profile: InvestorProfile
    clarification_response: str