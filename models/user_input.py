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

    sectors_of_interest: list[str] = Field(
        default_factory=list,
        description=(
            "Sectors or fields the investor wants to invest IN, e.g. "
            "'technology', 'healthcare', 'renewable energy'. Not hobbies: the "
            "question is what part of the market to research, not what the "
            "person enjoys."
        ),
    )
    """What to research, in the investor's own words.

    Deliberately free text rather than a fixed list of sectors. A beginner
    answers "technology" and a fixed vocabulary would serve them equally well,
    but someone who knows they want "grid storage" or "semiconductor equipment"
    carries far more signal than "Technology" does - and that signal is exactly
    what Agent 2 turns into search queries.

    A fixed vocabulary was considered and rejected. Standard sector labels
    classify BUSINESS MODELS while people think in THEMES, and the two do not
    line up: a solar manufacturer is classified Technology, a solar operator
    Utilities. Constraining the input would have made the research narrower
    while guaranteeing nothing useful.
    """

    restrictions: list[str]