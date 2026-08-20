from pydantic import BaseModel, Field
from typing import Literal


class UserInput(BaseModel):

    age: int = Field(
        gt=0,
        le=120,
        description="The age of the investor."
    )

    investment_experience: Literal[
        "beginner",
        "intermediate",
        "advanced"
    ]

    risk_tolerance: Literal[
        "low",
        "moderate",
        "high"
    ]

    investment_amount: float = Field(gt=0)

    investment_window: str

    holding_period: str

    interests: list[str]

    restrictions: list[str]