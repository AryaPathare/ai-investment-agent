"""Tests for the Agent 5 schema — the structural guarantees.

These assert that certain mistakes cannot be EXPRESSED. Three matter most:

  * a recommendation with no way out of it
  * an empty result that does not say which kind of empty it is
  * an exit condition nobody could ever check

Each guards a design decision that a well-meaning future edit could undo without
anything else complaining.
"""

import pytest
from pydantic import ValidationError

from models.decision import (
    MAX_RECOMMENDATIONS,
    Decision,
    ExcludedCompany,
    ExitCondition,
    Recommendation,
    CompanyBrief,
)


def condition(**overrides):
    base = dict(
        condition="The FTC probe results in a fine.",
        article_ids=["uuid-1"],
    )
    return ExitCondition(**{**base, **overrides})


def recommendation(**overrides):
    base = dict(
        ticker="AAA",
        name="Acme Motors",
        thesis="It builds the batteries the grid-storage theme depends on.",
        exit_conditions=[condition()],
        screen_score=0.72,
        verdict="survives",
        exposure="direct",
    )
    return Recommendation(**{**base, **overrides})


# --- Exit conditions must be checkable ---------------------------------------


def test_an_exit_condition_citing_nothing_is_rejected():
    """"If fundamentals deteriorate" is a sentence, not a condition — nobody
    can ever tell whether it has happened."""
    with pytest.raises(ValidationError, match="no way to monitor it"):
        ExitCondition(condition="If the fundamentals deteriorate.")


def test_an_article_alone_grounds_a_condition():
    assert condition().article_ids == ["uuid-1"]


def test_a_metric_alone_grounds_a_condition():
    got = condition(article_ids=[], metric="debt_to_equity")
    assert got.metric == "debt_to_equity"


# --- A recommendation must carry a way out -----------------------------------


def test_a_recommendation_without_an_exit_condition_is_rejected():
    """A position with no plan. This is the part that has to be decided BEFORE,
    and a schema permitting its omission guarantees it is sometimes omitted."""
    with pytest.raises(ValidationError, match="no exit condition"):
        recommendation(exit_conditions=[])


def test_a_recommendation_carries_its_provenance():
    """Score and verdict are carried through, not recomputed, so Agent 5 cannot
    quietly disagree with the stages that produced them."""
    got = recommendation(screen_score=0.9, verdict="weakened")
    assert got.screen_score == pytest.approx(0.9)
    assert got.verdict == "weakened"


# --- Nothing must explain itself ---------------------------------------------


def test_an_empty_decision_must_say_why():
    """"Every candidate was disqualified", "none were examined" and "there were
    no candidates at all" are three findings an empty list renders identical."""
    with pytest.raises(ValidationError, match="must say why"):
        Decision()


def test_an_empty_decision_with_a_reason_is_valid():
    got = Decision(no_recommendation_reason="Every candidate carried a critical risk.")
    assert got.recommended_nothing
    assert got.no_recommendation_reason


def test_a_reason_cannot_be_set_alongside_actual_recommendations():
    """Otherwise the output says both "here are two companies" and "here is why
    there are none", and a reader has to guess which is true."""
    with pytest.raises(ValidationError, match="does\\s+recommend something"):
        Decision(
            recommendations=[recommendation()],
            no_recommendation_reason="nothing cleared the bar",
        )


def test_recommending_something_needs_no_reason():
    got = Decision(recommendations=[recommendation()])
    assert not got.recommended_nothing


# --- The cap -----------------------------------------------------------------


def test_more_than_three_recommendations_is_rejected():
    too_many = [recommendation(ticker=f"T{i}") for i in range(MAX_RECOMMENDATIONS + 1)]
    with pytest.raises(ValidationError, match="exceeds the maximum"):
        Decision(recommendations=too_many)


def test_exactly_three_is_allowed():
    ok = [recommendation(ticker=f"T{i}") for i in range(MAX_RECOMMENDATIONS)]
    assert len(Decision(recommendations=ok).recommendations) == 3


# --- Exclusions --------------------------------------------------------------


def test_exclusions_are_summarised_by_reason():
    """The equivalent of Agent 3's drop_summary. If everything reads
    not_critiqued, the critique cap is too tight rather than the candidates
    being poor — invisible from the output alone."""
    decision = Decision(
        recommendations=[recommendation()],
        excluded=[
            ExcludedCompany(ticker="B", name="B", reason="not_critiqued"),
            ExcludedCompany(ticker="C", name="C", reason="not_critiqued"),
            ExcludedCompany(ticker="D", name="D", reason="disqualified_by_risk"),
        ],
    )
    assert decision.exclusion_summary == {"not_critiqued": 2, "disqualified_by_risk": 1}


def test_an_exclusion_records_a_reason_from_the_fixed_vocabulary():
    with pytest.raises(ValidationError):
        ExcludedCompany(ticker="B", name="B", reason="did not feel right")


# --- What the model is allowed to return -------------------------------------


def test_the_model_returns_prose_only():
    """It does not choose, order, score, or see the other companies. Anything
    it could get wrong structurally is something it was never handed."""
    brief = CompanyBrief(thesis="t", exit_conditions=[condition()])

    assert not hasattr(brief, "ticker")
    assert not hasattr(brief, "screen_score")


def test_the_model_cannot_return_an_ungroundable_exit_condition():
    """The guarantee has to hold on the model's own envelope, not only after
    Python has assembled the output."""
    with pytest.raises(ValidationError):
        CompanyBrief(
            thesis="t",
            exit_conditions=[{"condition": "If things get worse."}],
        )


# --- The envelope, not the answer --------------------------------------------


def test_null_article_ids_is_treated_as_none_cited():
    """REGRESSION: the model wrote {"condition": "debt_to_equity rises above
    3.0", "article_ids": null, "metric": "debt_to_equity"} — a correct,
    metric-grounded condition, exactly what the prompt asks for. Pydantic
    rejected the whole brief over how the absence was spelled.

    It could not be salvaged either: the failure arrives as a client-side parse
    error with no rejected payload, unlike a provider 400."""
    got = ExitCondition(condition="debt_to_equity rises above 3.0",
                        article_ids=None, metric="debt_to_equity")
    assert got.article_ids == []
    assert got.metric == "debt_to_equity"


def test_null_article_ids_still_needs_a_metric_to_be_valid():
    """The transport is loosened; the contract is not. A condition citing
    nothing is still refused."""
    with pytest.raises(ValidationError, match="no way to monitor it"):
        ExitCondition(condition="If things get worse.", article_ids=None)
