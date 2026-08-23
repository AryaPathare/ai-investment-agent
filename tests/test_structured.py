"""Tests for the structured-output salvage layer.

Every case here is a real provider failure seen while building Agents 2, 3 and
4: the model produced the RIGHT DATA in the WRONG ENVELOPE, and the call failed
anyway. Salvage exists to recover the answer rather than spend another call on a
rate-limited free tier being told the same thing.

The last two tests matter most. Salvage must never accept something the normal
path would have rejected — it loosens the transport, never the contract.
"""

import json

import pytest
from pydantic import BaseModel, Field

from agents.structured import failed_generation, invoke_structured, salvage


class Item(BaseModel):
    name: str


class Envelope(BaseModel):
    items: list[Item] = Field(default_factory=list)
    notes: str | None = None


def provider_error(failed: str) -> Exception:
    """A Groq-style 400 carrying what the model produced before rejection."""
    exc = Exception("400 tool_use_failed")
    exc.body = {"error": {"failed_generation": failed}}
    return exc


# --- Pulling the rejected payload out ----------------------------------------


def test_the_rejected_generation_is_read_from_the_error_body():
    exc = provider_error('{"items": []}')
    assert failed_generation(exc) == '{"items": []}'


def test_an_error_carrying_nothing_yields_none():
    assert failed_generation(Exception("connection reset")) is None


# --- The envelopes actually seen ---------------------------------------------


def test_a_bare_list_is_rewrapped_in_the_schema_envelope():
    """Seen on MentionExtraction and ThemeProposal: the model returns the
    contents without the object the schema asks for."""
    exc = provider_error('[{"name": "a"}, {"name": "b"}]')
    got = salvage(exc, Envelope, "items")

    assert [i.name for i in got.items] == ["a", "b"]


def test_a_bare_list_is_not_rewrapped_when_no_list_field_is_declared():
    """Guessing which field a list belongs to would be inventing structure."""
    exc = provider_error('[{"name": "a"}]')
    assert salvage(exc, Envelope, None) is None


def test_a_markdown_fence_is_stripped():
    """Models wrap JSON in a fence even when asked not to."""
    exc = provider_error('```json\n{"items": [{"name": "a"}]}\n```')
    assert salvage(exc, Envelope, "items").items[0].name == "a"


def test_a_whole_tool_call_is_unwrapped_to_its_arguments():
    """REGRESSION (Agent 4): the model returned the entire tool call rather
    than its arguments — {"name": "functions.Schema", "arguments": {...}}. The
    payload inside was correct; only the wrapper was wrong."""
    exc = provider_error(json.dumps({
        "name": "functions.Envelope",
        "arguments": {"items": [{"name": "a"}], "notes": "n"},
    }))
    got = salvage(exc, Envelope, "items")

    assert [i.name for i in got.items] == ["a"]
    assert got.notes == "n"


def test_tool_call_arguments_encoded_as_a_json_string_are_decoded():
    """Some responses double-encode the arguments."""
    exc = provider_error(json.dumps({
        "name": "functions.Envelope",
        "arguments": json.dumps({"items": [{"name": "a"}]}),
    }))
    assert salvage(exc, Envelope, "items").items[0].name == "a"


def test_a_plain_object_still_salvages_without_an_arguments_key():
    exc = provider_error('{"items": [{"name": "a"}]}')
    assert salvage(exc, Envelope, "items").items[0].name == "a"


# --- What cannot be recovered ------------------------------------------------


def test_truncated_json_is_not_salvaged():
    """REGRESSION (Agent 4): with max_tokens too low the generation was cut off
    mid-sentence, so there was no valid JSON left. The fix is a bigger budget,
    NOT guessing at the missing half."""
    exc = provider_error('{"items": [{"name": "a"}, {"name": "Pfizer\'s non')
    assert salvage(exc, Envelope, "items") is None


def test_an_empty_generation_is_not_salvaged():
    assert salvage(provider_error("   "), Envelope, "items") is None


# --- The contract is never loosened ------------------------------------------


def test_a_payload_that_fails_validation_is_refused():
    """THE guarantee. Salvaged data is validated exactly like a normal
    response, so nothing gets in that would not have got in anyway."""
    exc = provider_error('{"items": [{"wrong_field": 1}]}')
    assert salvage(exc, Envelope, "items") is None


def test_the_original_error_is_raised_when_nothing_can_be_recovered():
    def boom(_messages):
        raise provider_error('{"items": [{"wrong_field": 1}]}')

    runnable = type("R", (), {"invoke": staticmethod(boom)})()

    with pytest.raises(Exception, match="tool_use_failed"):
        invoke_structured(runnable, [], Envelope, list_field="items")


# --- Empty responses ---------------------------------------------------------


def test_an_empty_generation_returns_the_default_where_nothing_is_an_answer():
    """Only where "the model found nothing" is a real answer — no themes
    cleared the bar, no risks in these articles."""
    def boom(_messages):
        raise provider_error("")

    runnable = type("R", (), {"invoke": staticmethod(boom)})()
    default = Envelope(notes="nothing found")

    got = invoke_structured(runnable, [], Envelope, list_field="items",
                            empty_default=default)
    assert got.notes == "nothing found"


def test_a_successful_call_is_returned_untouched():
    expected = Envelope(items=[Item(name="a")])
    runnable = type("R", (), {"invoke": staticmethod(lambda _m: expected)})()

    assert invoke_structured(runnable, [], Envelope, list_field="items") is expected


def test_the_wrapper_is_never_preferred_over_its_own_arguments():
    """REGRESSION: every schema here has defaults, so the OUTER tool-call dict
    validates perfectly well as an EMPTY result — pydantic ignores the unknown
    "name"/"arguments" keys and fills the rest in from defaults. Checking the
    wrapper first therefore "succeeds", returning nothing while the real payload
    sits one level down. Silent data loss that looks like a clean answer."""
    exc = provider_error(json.dumps({
        "name": "functions.Envelope",
        "arguments": {"items": [{"name": "a"}, {"name": "b"}]},
    }))
    got = salvage(exc, Envelope, "items")

    assert len(got.items) == 2, "the wrapper was validated instead of its arguments"
