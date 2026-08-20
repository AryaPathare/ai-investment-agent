"""Reliable structured output, working around two real provider failures.

THE PROBLEM
-----------
Asking a model for a schema-shaped answer fails in ways that are not the model
getting the ANSWER wrong. Both of these were hit while building Agents 2 and 3:

1. The model emits the right data in the wrong envelope.

   Every schema here wraps a single list - ``MentionExtraction{mentions: [...]}``,
   ``ThemeProposal{themes: [...]}`` - and the model regularly returns the bare
   list instead of the wrapping object, sometimes inside a ```json fence. Groq
   then rejects it and the whole call fails.

   This is not a passing glitch. It failed three identical retries on the same
   input, and it happens under BOTH structured-output methods, merely on
   different schemas: function_calling failed on MentionExtraction while
   json_schema failed on ThemeProposal.

   The extracted data in those failures was CORRECT. Throwing away a correct
   answer because of an envelope mistake wastes a call, and on a rate-limited
   free tier that matters.

2. The model returns nothing at all.

   Reported as 400 "Tool choice is required, but model did not call a tool" with
   an EMPTY generation. Intermittent, and handled by retrying - unlike case 1,
   there is nothing to salvage.

WHY NOT JUST RETRY
------------------
Retrying is already in place and does not fix case 1, because the behaviour is
deterministic for a given input. Salvaging recovers the answer the model
actually produced; retrying just spends another call to be told the same thing.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
Salvaged data is validated against the schema exactly like a normal response.
Nothing is accepted that would not have been accepted through the normal path, so
this loosens the transport, never the contract. If the salvaged payload does not
validate, the original error is raised unchanged.
"""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

# Matches the provider's report of what the model produced before rejecting it.
_FAILED_GENERATION = re.compile(r"'failed_generation':\s*'(.*?)'\}\}", re.DOTALL)

# Models often wrap JSON in a markdown fence even when asked not to.
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def failed_generation(exc: Exception) -> str | None:
    """Pull the rejected output out of a provider error, if it is there."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and "failed_generation" in error:
            return error["failed_generation"]

    # Fall back to the string form, since not every client exposes .body.
    match = _FAILED_GENERATION.search(str(exc))
    if match:
        return match.group(1).encode().decode("unicode_escape")
    return None


def salvage(exc: Exception, schema: type[T], list_field: str | None) -> T | None:
    """Rebuild a valid response from output the provider rejected.

    Returns None when there is nothing usable, in which case the caller should
    re-raise. Never returns anything that fails schema validation.
    """
    raw = failed_generation(exc)
    if not raw or not raw.strip():
        return None

    text = _FENCE.sub("", raw.strip())

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None

    candidates: list[dict] = []
    if isinstance(parsed, dict):
        candidates.append(parsed)
    elif isinstance(parsed, list) and list_field:
        # The bare-list case: the model returned the contents without the
        # envelope the schema asks for.
        candidates.append({list_field: parsed})

    for candidate in candidates:
        try:
            return schema.model_validate(candidate)
        except ValidationError:
            continue
    return None


def invoke_structured(
    runnable,
    messages,
    schema: type[T],
    *,
    list_field: str | None = None,
    empty_default: T | None = None,
) -> T:
    """Invoke a structured-output runnable, recovering from envelope failures.

    Args:
        runnable: The model already wired to ``schema``.
        messages: Messages to send.
        schema: The expected response model, used to validate any salvage.
        list_field: Name of the schema's single list field, if it has one. Set
            this to allow recovery when the model returns a bare list.
        empty_default: What to return when the model produced NOTHING at all.
            Only pass this where "nothing" is a meaningful answer - no themes
            cleared the bar, no companies were named. Where it is not, leave it
            None so the failure propagates.

    Raises:
        Exception: The provider's original error, when nothing can be recovered.
    """
    try:
        return runnable.invoke(messages)
    except Exception as exc:  # noqa: BLE001 - narrowed by what we can recover
        recovered = salvage(exc, schema, list_field)
        if recovered is not None:
            return recovered

        raw = failed_generation(exc)
        if empty_default is not None and raw is not None and not raw.strip():
            # The model produced nothing. For these calls that is a real answer.
            return empty_default

        raise
