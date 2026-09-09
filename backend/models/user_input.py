from pydantic import BaseModel, Field, field_validator
from typing import Literal


# Whole answers meaning "I have no restrictions". Matched against the ENTIRE
# answer after casefolding and stripping trailing punctuation - NEVER as a
# prefix, because "no fossil fuels" and "nothing in defence" are real
# restrictions that begin with these same words.
_NO_OP_RESTRICTIONS = {
    "no", "none", "nope", "nil", "nothing", "na", "n/a", "n.a.",
    "no restrictions", "no restriction", "none really", "not really",
    "no preference", "no preferences", "no limits", "no limit",
    "", "-", "--",
}


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

    # OPTIONAL on purpose. A required field with a default would stamp a
    # currency onto every profile saved before this existed, and the first thing
    # that produces is a share count divided by a price in the wrong money.
    # Absent means "not stated", and the brief then shows prices without ever
    # converting an amount it cannot place.
    investment_currency: Literal["USD", "GBP", "EUR", "INR"] | None = Field(
        default=None,
        description=(
            "Currency the investment amount is in. Most companies this finds "
            "trade in USD."
        ),
    )

    # There used to be an investment_window field here, asking when the user
    # planned to BUY. Nothing consumed it: this pipeline researches themes and
    # companies, it never schedules a purchase. Meanwhile the CLI asked for it
    # with "When do you need the money back" - an EXIT horizon, the opposite end
    # of the trade - so users answered the same thing twice or gave up and typed
    # a bare number. The field is gone; holding_period below is the one question
    # that was ever wired into anything.
    holding_period: str = Field(
        min_length=1,
        description=(
            "How long the investor plans to keep the money invested before "
            "needing it back, in their own words, e.g. '3-5 years'."
        ),
    )
    """How long the money stays invested, in the investor's own words.

    Free text on purpose, for the same reason ``sectors_of_interest`` is: "18
    months", "until my daughter starts university" and "3-5 years" are all
    answers a person actually gives, and a fixed menu would force the last one
    onto all three.

    So there are two checks, and both are about the answer being READABLE rather
    than about its shape. The CLI already re-asks on an empty answer, but
    ``--profile file.json`` and the HTTP layer go straight to this model, and
    since this is the only timeframe in the profile a bad one reaches Agent 2's
    query prompt and Agent 5's brief unchallenged.
    """

    @field_validator("holding_period", mode="before")
    @classmethod
    def _strip_holding_period(cls, value: object) -> object:
        """Trim first, so "   " fails ``min_length`` instead of passing it."""
        return value.strip() if isinstance(value, str) else value

    @field_validator("holding_period")
    @classmethod
    def _a_number_needs_a_unit(cls, value: str) -> str:
        """Refuse "8", because nothing downstream can tell months from years.

        This project has already been bitten by this exact answer. The comment
        above records that ``investment_window`` was deleted partly because
        ``mine.json`` held a bare "8" - written when the two timeframe questions
        were confusing enough that a number looked like a plausible reply to
        whichever was being asked. The field went; the answer shape did not.

        A bare number is not a small ambiguity. Agent 2 renders the whole
        profile into its query prompt and Agent 5 writes the horizon into the
        brief in words, so "8" is resolved independently, silently, and possibly
        differently by each of them - and a beginner told a ten-month idea suits
        their eight-YEAR plan has been given the wrong answer confidently.

        The rule is deliberately narrow: digits with no letters anywhere. "8",
        "3-5" and "10+" are refused; "8 years", "18 months", "3-5 yrs", "long
        term" and "until my daughter starts university" all pass untouched. The
        free text this field exists for is not narrowed at all.

        It lives here rather than in the question's wording because wording does
        not fix this. The restrictions prompt said "blank if none" and was
        answered "none" twice by two different people, and the help beside this
        question already offers "18 months" and "3-5 years" as examples.
        """
        if any(char.isdigit() for char in value) and not any(
            char.isalpha() for char in value
        ):
            raise ValueError(
                f"holding period {value!r} could mean months or years, and "
                "nothing downstream can tell which; say which one, as in "
                f"'{value} months' or '{value} years'"
            )
        return value

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

    restrictions: list[str] = Field(
        description=(
            "Things the investor will not hold, in their own words, e.g. "
            "'no fossil fuels'. Empty means no restrictions."
        ),
    )
    """What NOT to research, in the investor's own words.

    An empty list is the normal way to say "nothing is off limits", and the
    validator below is what makes that reachable in practice.
    """

    @field_validator("restrictions", mode="after")
    @classmethod
    def _drop_no_op_restrictions(cls, values: list[str]) -> list[str]:
        """Discard answers that mean "I have no restrictions".

        The CLI prompt already says "blank if none" and people type "none"
        anyway - twice on record, in two different sessions: the shipped
        recording in ``shared/recorded_run.json`` carries ``["no"]``, and the run
        that verified the timeframe merge carried ``["none"]``. A prompt that
        has been ignored twice is not fixed by rewording it a third time.

        It matters because a restriction is not inert. Agent 2 is instructed to
        honour restrictions at QUERY time, so the literal string "none" is
        carried into that prompt as an area to avoid researching, and it prints
        in the profile line as "will not hold: none".

        THE ERROR TO FEAR HERE IS THE FALSE POSITIVE. Dropping a real
        restriction would research an area the investor explicitly prohibited -
        the one thing this project says must never happen - and it would do it
        silently. Almost every real restriction people write STARTS with "no":
        "no fossil fuels", "no tobacco", "nothing in defence". So the match is
        against the WHOLE answer, never a prefix, and only against a closed list
        of answers that can carry no other meaning.
        """
        kept: list[str] = []
        for value in values:
            cleaned = value.strip()
            if cleaned.strip(".!- ").casefold() in _NO_OP_RESTRICTIONS:
                continue
            if cleaned:
                kept.append(cleaned)
        return kept
