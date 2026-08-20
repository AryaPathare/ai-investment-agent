from pydantic import Field
from typing import Literal

from models.user_input import UserInput


class InvestorProfile(UserInput):

    profile_status: Literal[
        "valid",
        "needs_clarification"
    ] = Field(
        description="The status of the investor profile after validation."
    )

    clarification_needed: bool = Field(
        description="Whether the user needs to clarify any information."
    )

    clarification_reason: str | None = Field(
        default=None,
        description="The reason clarification is needed, if applicable."
    )