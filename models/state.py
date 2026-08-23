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

from models.companies import CompanyFindings
from models.decision import Decision
from models.risk import RiskFindings
from models.profile import InvestorProfile
from models.research import ResearchFindings
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

    # --- Agent 2 -------------------------------------------------------------

    research_findings: ResearchFindings
    """Themes and supporting articles from the research agent.

    A snapshot, replaced on each run. ``found_nothing`` being True is a valid
    result, not a failure: it means no theme cleared the evidence bar. Agent 3
    must check it rather than assuming themes always exist.
    """

    # --- Agent 3 -------------------------------------------------------------

    company_findings: CompanyFindings
    """Ranked investable companies from the company agent.

    A snapshot, replaced on each run. ``found_nothing`` being True is a valid
    result: the themes may be real while no company mentioned alongside them is
    both investable and genuinely exposed. ``drop_summary`` records where every
    examined company went.
    """

    # --- Agent 4 -------------------------------------------------------------

    risk_findings: RiskFindings
    """Grounded criticism of Agent 3's candidates, from the risk critic.

    A snapshot, replaced on each run. ``found_nothing`` being True means no risk
    was found against any candidate — a legitimate outcome, but one Agent 5
    should treat with suspicion rather than relief: it is far more often a sign
    that retrieval returned nothing than that every candidate is sound. Reading
    ``was_critiqued`` on each critique is what tells those apart.
    """

    # --- Agent 5 -------------------------------------------------------------

    decision: Decision
    """The final recommendation, or the reasoned absence of one.

    A snapshot, replaced on each run. ``recommended_nothing`` being True is a
    legitimate and important outcome, not a failure - and unlike the other
    agents' empty results, this one always carries
    ``no_recommendation_reason``, because "every candidate was disqualified" and
    "none of them were ever examined" call for completely different responses
    from whoever is reading.
    """

    # --- Workflow ------------------------------------------------------------

    error: str
    """Why the workflow could not produce a usable profile, if it could not.

    Set when the model call fails after its retries, or when the user has been
    asked to clarify the maximum number of times without resolution. If this is
    present at the end of a run, ``investor_profile`` must NOT be used by
    downstream agents.
    """
