"""Tests for the shared description of a run.

render.py exists to stop two front ends deciding separately what a reader is
told. So these tests are mostly about CONTENT - which article grounds a
condition, what a machine name is called in English, whether an empty result is
stated rather than implied - and one of them is about the boundary itself: that
no terminal layout has leaked back in.
"""

import json
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from backend import render
from backend.models.companies import CompanyFindings, MarketPrice
from backend.models.decision import Decision, ExcludedCompany, ExitCondition, Recommendation
from backend.models.research import Article, ResearchFindings
from backend.models.risk import CandidateCritique, Risk, RiskFindings


def _article(uuid="u1", source="reuters.com") -> Article:
    return Article(
        uuid=uuid,
        title="Waaree wins a battery order",
        description="d",
        snippet="s",
        url="https://reuters.com/" + uuid,
        source=source,
        published_at=datetime(2026, 8, 17, tzinfo=timezone.utc),
    )


def _recommendation(**overrides) -> Recommendation:
    base = dict(
        ticker="WAAREE",
        name="Waaree Energies",
        thesis="Makes the solar modules the grid buildout consumes.",
        exit_conditions=[
            ExitCondition(
                condition="debt_to_equity rises above 3.0", metric="debt_to_equity"
            ),
            ExitCondition(condition="the order is cancelled", article_ids=["u1"]),
        ],
        screen_score=0.72,
        verdict="survives",
        exposure="direct",
        themes=["grid storage buildout"],
        known_risks=["Concentrated in one customer"],
    )
    return Recommendation(**{**base, **overrides})


@pytest.fixture
def state(clean_user):
    return {
        "user_input": clean_user,
        "research_findings": ResearchFindings(
            articles_retrieved=4, articles=[_article()]
        ),
        "decision": Decision(recommendations=[_recommendation()]),
    }


# --- The three outcomes ------------------------------------------------------


def test_a_failed_run_says_so_and_carries_its_reason(clean_user):
    described = render.describe_run(
        {"user_input": clean_user, "error": "Research failed: ConnectionError: down"}
    )

    assert described["status"] == "failed"
    assert "ConnectionError" in described["error"]
    assert described["decision"] is None
    # The hint travels with the error rather than being written into a front
    # end, because "this may be the daily ceiling" is something the reader is
    # told, not a layout choice.
    assert "daily ceiling" in described["error_hint"]

    # But it carries NO command. This is the hint a browser gets, and the shared
    # daily ceiling is what usually ends a run on the deployed site, so it is
    # the sentence most visitors will ever read. Telling them to open a shell
    # they do not have is the one thing it must not do.
    assert "check_setup" not in described["error_hint"]
    assert "python -m" not in described["error_hint"]


def test_the_cli_hint_keeps_the_step_a_terminal_reader_can_take():
    """The command is not deleted, only moved off the shared path.

    Somebody at a prompt CAN tell a configuration problem from an outage, and
    that is worth saying to them. Both texts live in render.py; which one to
    show is the front end's call, in the same way layout is.
    """
    assert render.RATE_LIMIT_HINT in render.RATE_LIMIT_HINT_CLI
    assert "check_setup" in render.RATE_LIMIT_HINT_CLI


def test_a_run_with_neither_decision_nor_error_is_reported_not_blank(clean_user):
    """Unreachable in principle - every path sets one or the other. Saying so
    beats rendering an empty page if it ever happens."""
    described = render.describe_run({"user_input": clean_user})

    assert described["status"] == "no_decision"
    assert described["state_reached"] == ["user_input"]


def test_recommending_nothing_is_a_stated_answer(clean_user):
    described = render.describe_run(
        {
            "user_input": clean_user,
            "decision": Decision(no_recommendation_reason="Nothing cleared the bar."),
        }
    )["decision"]

    assert described["recommended_nothing"] is True
    assert described["no_recommendation_reason"] == "Nothing cleared the bar."
    assert "not a failure" in described["nothing_explanation"]


def test_the_computed_properties_a_dump_would_lose_are_all_stated(state):
    """The whole reason this file exists rather than a model_dump.

    ``recommended_nothing`` is a property, so a dumped Decision does not carry
    it and a front end would re-derive it from a list length.
    """
    described = render.describe_run(state)["decision"]

    assert described["recommended_nothing"] is False
    assert described["recommendations"][0]["verdict"] == "survives"


# --- Grounding ---------------------------------------------------------------


def test_a_metric_condition_is_named_in_english(state):
    grounds = render.grounds_for(
        ExitCondition(condition="x", metric="debt_to_equity"), state
    )

    assert grounds == [
        {"kind": "metric", "text": "the company's reported debt-to-equity"}
    ]


def test_a_cited_article_carries_what_a_reader_would_check(state):
    grounds = render.grounds_for(
        ExitCondition(condition="x", article_ids=["u1"]), state
    )

    assert grounds[0]["kind"] == "article"
    assert grounds[0]["title"] == "Waaree wins a battery order"
    assert grounds[0]["source"] == "reuters.com"
    assert grounds[0]["published_on"] == "17 Aug 2026"
    assert grounds[0]["url"].startswith("https://")


def test_an_id_in_neither_store_says_so_rather_than_showing_a_hex_string(state):
    """"The source was not kept" is information. A bare uuid is not."""
    grounds = render.grounds_for(
        ExitCondition(condition="x", article_ids=["deadbeefcafe"]), state
    )

    assert grounds[0]["kind"] == "missing"
    assert "deadbeef" in grounds[0]["text"]


def test_a_bear_case_article_is_found_as_well_as_a_theme_article(clean_user):
    """Two stores can hold the cited article and neither knows about the other."""
    state = {
        "user_input": clean_user,
        "risk_findings": RiskFindings(articles=[_article("bear1")]),
        "research_findings": ResearchFindings(articles=[_article("theme1")]),
    }

    for uuid in ("bear1", "theme1"):
        grounds = render.grounds_for(
            ExitCondition(condition="x", article_ids=[uuid]), state
        )
        assert grounds[0]["kind"] == "article", uuid


def test_the_schema_refuses_a_condition_grounded_in_nothing(state):
    """Why grounds_for's "none" branch is unreachable in practice.

    A condition citing neither an article nor a metric cannot be constructed at
    all - the schema is the trust boundary, not the renderer. The branch stays
    as defence for any condition-shaped object, and this records that it is the
    MODEL doing the work, so nobody later reads the branch as evidence that
    ungrounded conditions reach a reader.
    """
    with pytest.raises(ValidationError, match="cites neither"):
        ExitCondition(condition="x")


# --- Words a reader gets instead of machine names ----------------------------


def test_field_names_and_citation_labels_are_stripped_from_prose():
    assert render.plain("operating_margin falls [A1] below 0.2") == (
        "operating margin falls below 0.2"
    )


def test_an_exclusion_reason_is_translated_and_its_bookkeeping_hidden():
    """The detail is worth showing for the two reasons that describe the
    COMPANY. For the ranking reasons it carries the screen score, which
    agents/screening.py records as unreadable as a grade."""
    ranked = render._describe_exclusion(
        ExcludedCompany(
            ticker="INTC", name="Intel", reason="outside_top_three",
            detail="ranked 4 of 5 eligible (weakened, score 0.997)",
        )
    )
    blocked = render._describe_exclusion(
        ExcludedCompany(
            ticker="NVDA", name="NVIDIA", reason="restriction_violation",
            detail="industry Semiconductors matches 'semiconductor'",
        )
    )

    assert ranked["reason_text"] == "Ranked just outside the top three."
    assert ranked["detail"] is None, "the score must not reach a reader"
    assert blocked["detail"] is not None


def test_the_profile_says_no_restrictions_rather_than_leaving_a_blank(clean_user):
    """A blank there reads as a question nobody answered."""
    assert render.profile_parts(clean_user)["restrictions"] == "no restrictions"


def test_the_profile_is_described_in_pieces_a_front_end_joins(clean_user):
    """Not one pre-joined block: the newlines and indent are a terminal's."""
    parts = render.profile_parts(clean_user)

    assert set(parts) == {"headline", "sectors", "restrictions"}
    assert not any(chr(10) in value for value in parts.values())


# --- The price and what it would buy -----------------------------------------


def _priced(currency="USD", shares=4, own=None):
    return _recommendation(
        price=MarketPrice(
            amount=217.09, currency=currency,
            as_of=datetime(2026, 8, 28, tzinfo=timezone.utc),
        ),
        shares_affordable=shares,
        price_in_investor_currency=own,
    )


def test_the_price_is_shown_in_the_readers_money_only_when_it_differs(clean_user):
    """"CNY 373.00" tells a reader almost nothing on its own - and the same
    currency printed twice is noise rather than information."""
    user = clean_user.model_copy(update={"investment_currency": "USD"})

    same = render._price(_priced(currency="USD", own=217.09), user)
    different = render._price(_priced(currency="CNY", own=30.11), user)

    assert same["in_investor_currency"] is None
    assert different["in_investor_currency"] == 30.11
    assert different["investor_currency"] == "USD"


def test_no_stated_currency_means_no_conversion_line(clean_user):
    """A reader who never said what their money is in cannot be told what it
    would buy, and a guess is the one direction of error that matters here."""
    described = render._price(_priced(currency="CNY", own=30.11), clean_user)

    assert described["in_investor_currency"] is None


def test_zero_shares_is_an_answer_rather_than_a_silence(clean_user):
    user = clean_user.model_copy(
        update={"investment_currency": "USD", "investment_amount": 1000}
    )

    assert render.affordable_sentence(_priced(shares=0), user) == (
        "One share costs more than your USD 1,000."
    )


# --- The counts a run reports as it goes -------------------------------------


def test_withheld_sources_keep_the_count_separate_from_the_names():
    """Four articles withheld from one publisher is the shape of a filter that
    is too aggressive; four from four is a thin week. Collapsing the count into
    the deduplicated name list would erase the difference."""
    detail = render.stage_detail(
        "risk_critic",
        {
            "risk_findings": RiskFindings(
                critiques=[
                    CandidateCritique(
                        ticker="WAAREE", name="Waaree", risks=[],
                        queries_used=["q"], articles_reviewed=1,
                        sources_withheld=["a.com", "a.com", "b.com"],
                    )
                ]
            )
        },
    )

    assert detail["critiques"][0]["sources_withheld"] == ["a.com", "b.com"]
    assert detail["critiques"][0]["sources_withheld_count"] == 3


def test_a_stage_that_found_nothing_says_so_explicitly():
    """``found_nothing`` is a property, so a front end reading the raw update
    would have to infer it from an empty list."""
    detail = render.stage_detail(
        "companies", {"company_findings": CompanyFindings(companies_examined=6)}
    )

    assert detail["found_nothing"] is True
    assert detail["candidates"] == []
    assert detail["companies_examined"] == 6


def test_an_unknown_node_describes_nothing_rather_than_guessing():
    assert render.stage_detail("something_new", {"whatever": 1}) == {}


# --- The boundary itself -----------------------------------------------------


def test_nothing_described_carries_terminal_layout(state):
    """The guard on the content/layout split.

    If a banner, a bullet or a wrapped line ever appears in what render.py
    returns, the two front ends have started sharing a TERMINAL rather than a
    description, and the browser inherits 78-column line breaks.
    """
    blob = json.dumps(render.describe_run(state))

    assert "===" not in blob
    assert "\\n  " not in blob, "no indentation"
    assert "•" not in blob, "no bullets"


def test_everything_described_survives_json(state):
    """No Pydantic objects, no datetimes, no enums - the failure would land
    after a paid run had already completed."""
    blob = json.dumps(render.describe_run(state))

    assert "17 Aug 2026" in blob
    assert "2026-08-17" in blob


def test_the_review_date_is_three_months_out_not_the_holding_period(state):
    """Deliberately not derived from holding_period: it is free text, and
    someone holding for five years should not first check back in five years."""
    described = render.describe_run(state, today=date(2026, 8, 26))["decision"]

    assert described["next_review"] == "2026-11-25"
    assert described["next_review_on"] == "25 Nov 2026"


# --- The form contract -------------------------------------------------------
#
# `form_fields()` had no test before F8 changed it, which is why these exist.
# The rule the whole function is built on is that the MODEL is the single source
# for what it offers - options from Literal types, bounds from constraints, and
# now which answers may be left alone. A front end that keeps its own copy of
# any of those has given it two homes and one of them no test.


def test_which_menus_may_be_left_blank_comes_from_the_model():
    """`investment_currency` is `Literal[...] | None` and the other two are not.

    F8 made the page start every menu blank. Blank is then a legal answer for
    currency and a 422 for the other two, and the page has to tell them apart -
    so the difference is derived from the annotation rather than listed in
    JavaScript. Retype that list in the front end and this stops being true
    silently.
    """
    by_name = {f["name"]: f for f in render.form_fields()}

    assert by_name["investment_currency"]["required"] is False
    assert by_name["investment_experience"]["required"] is True
    assert by_name["risk_tolerance"]["required"] is True


def test_every_choice_field_says_whether_it_is_required():
    """A menu with no `required` key renders as optional by accident, because
    `field.required` is undefined in JavaScript and undefined is falsy. A
    required question that silently became optional is exactly the failure this
    catches."""
    for field in render.form_fields():
        if field["kind"] == "choice":
            assert "required" in field, field["name"]
            assert isinstance(field["required"], bool)


def test_no_sector_example_is_long_enough_to_wrap_its_row():
    """Name plus example has to fit one row of the sector grid.

    This is a proxy for a pixel measurement and says so. The grid track is
    21rem; every sector at 42 characters or fewer fits, and "Consumer
    Defensive" with "food producers, household goods" came to 49 and was the
    only cell in the grid that wrapped - seven clear of the next longest, which
    is what made shortening it the fix rather than widening the track.

    The ceiling is deliberately just above the pack rather than at it, so an
    example can be reworded without a test failing for no reason - but a new
    one long enough to reintroduce the wrap fails here instead of in a
    screenshot nobody takes.
    """
    longest = max(render.SECTORS, key=lambda pair: len(pair[0]) + len(pair[1]))
    combined = len(longest[0]) + len(longest[1])
    assert combined <= 44, f"{longest[0]} + {longest[1]!r} is {combined} chars"
