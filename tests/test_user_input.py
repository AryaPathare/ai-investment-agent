"""Tests for UserInput — the boundary where raw user data enters the system.

Every check here is deterministic Python, no model involved. This is the layer
that catches obviously invalid input so the LLM never has to reason about it,
following the project's rule: Python for what Python can check.
"""

import pytest
from pydantic import ValidationError

from models.user_input import UserInput


def _fields(**overrides):
    """Valid input, with specific fields swapped out for a test."""
    base = dict(
        age=30,
        investment_experience="intermediate",
        risk_tolerance="moderate",
        investment_amount=1000.0,
        holding_period="3-5 years",
        sectors_of_interest=["technology"],
        restrictions=[],
    )
    return {**base, **overrides}


def test_accepts_valid_input():
    user = UserInput(**_fields())
    assert user.age == 30
    assert user.sectors_of_interest == ["technology"]


@pytest.mark.parametrize("age", [0, -1, 121, 200])
def test_rejects_impossible_ages(age):
    with pytest.raises(ValidationError):
        UserInput(**_fields(age=age))


@pytest.mark.parametrize("age", [1, 18, 120])
def test_accepts_ages_at_the_boundaries(age):
    assert UserInput(**_fields(age=age)).age == age


@pytest.mark.parametrize("amount", [0, -0.01, -500])
def test_rejects_non_positive_investment_amount(amount):
    """The original motivating example: investment_amount = -500 must not pass."""
    with pytest.raises(ValidationError):
        UserInput(**_fields(investment_amount=amount))


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("investment_experience", "expert"),
        ("investment_experience", "Beginner"),  # case matters
        ("risk_tolerance", "very high"),
        ("risk_tolerance", ""),
    ],
)
def test_rejects_values_outside_the_allowed_set(field, bad_value):
    with pytest.raises(ValidationError):
        UserInput(**_fields(**{field: bad_value}))


def test_rejects_missing_required_field():
    fields = _fields()
    del fields["risk_tolerance"]
    with pytest.raises(ValidationError):
        UserInput(**fields)


def test_coerces_integer_amount_to_float():
    assert isinstance(UserInput(**_fields(investment_amount=1000)).investment_amount, float)


# --- holding_period ----------------------------------------------------------


@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n"])
def test_rejects_a_blank_holding_period(blank):
    """The CLI re-asks on an empty answer; --profile goes straight to the model.

    It is the only timeframe left in the profile, and it reaches Agent 2's query
    prompt and Agent 5's brief, so an empty one must not get that far.
    """
    with pytest.raises(ValidationError):
        UserInput(**_fields(holding_period=blank))


def test_holding_period_is_trimmed():
    assert UserInput(**_fields(holding_period="  18 months  ")).holding_period == "18 months"


@pytest.mark.parametrize(
    "answer",
    ["3-5 years", "18 months", "until my daughter starts university", "a decade"],
)
def test_holding_period_stays_free_text(answer):
    """Deliberately not parsed. A fixed menu would force every answer into it."""
    assert UserInput(**_fields(holding_period=answer)).holding_period == answer


# --- restrictions: the no-op answers ----------------------------------------
#
# The dangerous direction here is the FALSE POSITIVE, so the surviving list is
# longer than the dropped one and is where a regression would actually hurt.


@pytest.mark.parametrize(
    "answer",
    [
        "no", "none", "No", "NONE", "nope", "nil", "nothing",
        "na", "n/a", "N/A", "no restrictions", "no restriction",
        "none really", "not really", "no preference", "no limits",
        "-", "--", "  none  ", "none.", "None!",
    ],
)
def test_a_no_op_restriction_is_dropped(answer):
    """People type "none" however the prompt is worded. Two runs on record did.

    A restriction is not inert: Agent 2 honours restrictions at QUERY time, so
    the literal string would be carried in as an area not to research.
    """
    assert UserInput(**_fields(restrictions=[answer])).restrictions == []


@pytest.mark.parametrize(
    "answer",
    [
        "no fossil fuels",
        "no tobacco",
        "no gambling",
        "NO GAMBLING",
        "nothing in defence",
        "none of the tobacco majors",
        "not really interested in banks",
        "no companies with a Russian parent",
        "nil-coupon bonds",
    ],
)
def test_a_real_restriction_is_never_dropped(answer):
    """THE test in this file.

    Almost every real restriction starts with one of the no-op words, so a
    prefix match here would silently research an area the investor prohibited -
    the one failure this project says must never happen. Matching is against the
    whole answer, so every one of these survives intact.
    """
    assert UserInput(**_fields(restrictions=[answer])).restrictions == [answer]


def test_a_real_restriction_survives_alongside_a_no_op_one():
    """Someone answering "no fossil fuels, none" must keep the real half."""
    user = UserInput(**_fields(restrictions=["no fossil fuels", "none"]))
    assert user.restrictions == ["no fossil fuels"]


def test_restrictions_are_trimmed():
    assert UserInput(**_fields(restrictions=["  no tobacco  "])).restrictions == ["no tobacco"]


def test_the_shipped_recording_no_longer_carries_a_no_op_restriction():
    """demo/recorded_run.json holds ["no"] - it is what that user really typed.

    The recording is left as recorded; the model normalises it on load. So the
    demo everyone is shown prints "no restrictions" rather than "will not
    hold: no", without the recording being edited to say something it did not.
    """
    import json
    from pathlib import Path

    payload = json.loads(
        Path("demo/recorded_run.json").read_text(encoding="utf-8")
    )
    assert payload["profile"]["restrictions"] == ["no"]
    assert UserInput.model_validate(payload["profile"]).restrictions == []
