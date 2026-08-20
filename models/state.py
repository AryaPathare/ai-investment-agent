"""Shared state carried through the LangGraph workflow.

Every node reads from this dict and returns a partial update to it. LangGraph
merges each update into the running state.

How a field is merged depends on its type annotation:

* A plain field is REPLACED by whatever a node returns for it.
* A field annotated with a reducer, e.g. ``Annotated[list[str], add]``, is
  COMBINED with the existing value using that function.

Choosing between the two is a real design decision. For each field, ask:
"is this a snapshot, or a log?" A snapshot (the current profile) should be
replaced. A log (everything the user has told us) must accumulate — otherwise
each new entry destroys the previous one.
"""

from operator import add
from typing import Annotated, TypedDict

from models.profile import InvestorProfile
from models.user_input import UserInput


class InvestmentState(TypedDict, total=False):
    """State for the investment research workflow.

    ``total=False`` means every key is optional, so the graph can start with
    only ``user_input`` present and fill the rest in as it runs.
    """

    # --- Input ---------------------------------------------------------------

    user_input: UserInput
    """The investor's original answers. Never modified once set."""

    # --- Agent 1 -------------------------------------------------------------

    investor_profile: InvestorProfile
    """Latest profile from the profile agent. A snapshot: replaced each run."""

    clarification_responses: Annotated[list[str], add]
    """Every clarification the user has given, oldest first.

    A log, not a snapshot — hence the ``add`` reducer, which concatenates lists
    instead of overwriting. This field used to be a single ``str``, which meant
    a second clarification erased the first: the agent would forget what the
    user had already told it and could re-raise a conflict they had just
    resolved, feeding the very loop we now bound below.
    """

    clarification_attempts: int
    """How many times we have asked the user to clarify.

    Compared against ``max_clarification_attempts`` in config.py to guarantee
    the clarification loop terminates. A snapshot, so it is replaced (each node
    computes the new total) rather than accumulated.
    """

    # --- Workflow ------------------------------------------------------------

    error: str
    """Why the workflow could not produce a usable profile, if it could not.

    Set when the model call fails after its retries, or when the user has been
    asked to clarify the maximum number of times without resolution. If this is
    present at the end of a run, ``investor_profile`` must NOT be used by
    downstream agents.
    """
