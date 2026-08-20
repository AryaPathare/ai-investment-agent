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
        investment_window="within 1 month",
        holding_period="3-5 years",
        interests=["technology"],
        restrictions=[],
    )
    return {**base, **overrides}


def test_accepts_valid_input():
    user = UserInput(**_fields())
    assert user.age == 30
    assert user.interests == ["technology"]


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
