"""LangGraph workflow for the investment research pipeline.

Covers Agents 1 to 3: validate the investor profile, pausing to ask the user
whenever two of their answers genuinely conflict; research current themes
grounded in real news articles; then find investable companies genuinely
exposed to those themes.

    START -> profile_agent -> (valid) -----------> research -> companies -> END
                           -> (clarification) -> ask user -> back to profile_agent
                           -> (exhausted) -> give up ------> END
                           -> (failed) -------------------> END

Agent 2 runs only from the "valid" branch. Researching a profile that still
contains a contradiction would spend API requests on areas the investor may
have already ruled out.
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agents.profile_agent import create_investor_profile
from agents.company_agent import analyse_companies
from agents.decide_agent import decide
from agents.risk_agent import critique_companies
from agents.research_agent import research_themes
from config import get_settings
from models.profile import InvestorProfile
from models.companies import (
    CompanyCandidate,
    CompanyFindings,
    ComparableMetrics,
    CurrencyAmounts,
    DroppedCompany,
    Fundamentals,
)
from models.research import Article, Evidence, ResearchFindings, Theme
from models.state import InvestmentState
from models.user_input import UserInput


def profile_node(state: InvestmentState) -> dict:
    """Run Agent 1 over the user's input plus any clarifications so far."""
    user_input = state["user_input"]

    # Every clarification the user has given, not just the most recent one.
    clarifications = state.get("clarification_responses", [])

    try:
        profile = create_investor_profile(user_input, clarifications)
    except Exception as exc:  # noqa: BLE001 - deliberately broad; see below
        # The model client already retried with exponential backoff (see
        # llm_max_retries in config.py). Reaching here means those retries were
        # exhausted, or the response failed schema validation. Either way there
        # is nothing left to try, so the workflow ends cleanly with a readable
        # reason instead of crashing with a traceback in the user's face.
        return {
            "error": (
                f"Could not validate the profile: {type(exc).__name__}: {exc}"
            )
        }

    return {"investor_profile": profile}


def route_profile(state: InvestmentState) -> str:
    """Decide what happens after the profile agent runs.

    This is a trust boundary: it turns model output into control flow. Every
    branch must terminate, and the ordering below matters — failures and the
    attempt limit are checked before we consider looping again.
    """
    if state.get("error"):
        return "failed"

    profile = state["investor_profile"]

    if not profile.needs_clarification:
        return "valid"

    # The loop bound. Without this, profile_agent -> clarification ->
    # profile_agent could cycle forever: if the model keeps flagging a conflict,
    # or the user keeps giving unhelpful answers, nothing would ever stop it.
    # Never rely on an LLM to decide when to stop looping.
    attempts = state.get("clarification_attempts", 0)
    if attempts >= get_settings().max_clarification_attempts:
        return "exhausted"

    return "clarification"


def clarification_node(state: InvestmentState) -> dict:
    """Pause the graph and ask the user to resolve the conflict.

    ``interrupt`` suspends execution and saves state via the checkpointer. The
    graph resumes from exactly here when invoked with ``Command(resume=...)``.
    """
    profile = state["investor_profile"]
    attempts = state.get("clarification_attempts", 0)
    max_attempts = get_settings().max_clarification_attempts

    response = interrupt(
        {
            "reason": profile.clarification_reason,
            "question": "Please clarify your preference.",
            "attempt": attempts + 1,
            "max_attempts": max_attempts,
        }
    )

    return {
        # A list, because clarification_responses uses an `add` reducer that
        # appends. Returning a bare string would append its characters.
        "clarification_responses": [response],
        "clarification_attempts": attempts + 1,
    }


def clarification_exhausted_node(state: InvestmentState) -> dict:
    """Give up after too many unsuccessful clarification rounds.

    A bounded loop needs a defined outcome, not just a stop. The profile keeps
    status 'needs_clarification', and `error` records why we stopped so callers
    know the profile must not be used downstream.
    """
    profile = state["investor_profile"]
    attempts = state.get("clarification_attempts", 0)

    return {
        "error": (
            f"Could not resolve the profile after {attempts} clarification "
            f"attempt(s). Unresolved issue: {profile.clarification_reason}"
        )
    }


def research_node(state: InvestmentState) -> dict:
    """Run Agent 2 over the validated profile.

    Reached only when the profile is valid, so the contract research_themes()
    enforces should already hold; it is still allowed to raise, and that is
    handled the same way a profile failure is.
    """
    profile = state["investor_profile"]

    try:
        findings = research_themes(profile)
    except Exception as exc:  # noqa: BLE001 - same reasoning as profile_node
        # Every external call is a failure boundary. The news API may be
        # unreachable or rate limited, and the model may fail after its retries.
        # None of that should end in a traceback.
        return {"error": f"Research failed: {type(exc).__name__}: {exc}"}

    return {"research_findings": findings}


def company_node(state: InvestmentState) -> dict:
    """Run Agent 3 over the research findings.

    Runs even when the research found nothing: analyse_companies handles that
    case and returns empty findings with an explanation, which keeps the reason
    visible in state instead of leaving a silently missing key.
    """
    research = state["research_findings"]

    try:
        findings = analyse_companies(research)
    except Exception as exc:  # noqa: BLE001 - same reasoning as the other nodes
        # Two providers and a model call sit behind this. Any of them can be
        # down, rate limited or out of quota, and none of that should reach the
        # user as a traceback.
        return {"error": f"Company analysis failed: {type(exc).__name__}: {exc}"}

    return {"company_findings": findings}


def risk_node(state: InvestmentState) -> dict:
    """Run Agent 4 over the ranked candidates.

    Runs even when Agent 3 found nothing: critique_companies handles that case
    and returns empty findings with the reason recorded, which keeps it visible
    in state rather than leaving a silently missing key for Agent 5 to
    misinterpret as "not run yet".
    """
    findings = state["company_findings"]

    try:
        critique = critique_companies(findings)
    except Exception as exc:  # noqa: BLE001 - same reasoning as the other nodes
        # A news provider and a model call per candidate sit behind this. Any of
        # them can be down, rate limited or out of quota, and none of that
        # should reach the user as a traceback.
        return {"error": f"Risk critique failed: {type(exc).__name__}: {exc}"}

    return {"risk_findings": critique}


def decide_node(state: InvestmentState) -> dict:
    """Run Agent 5 over the candidates and the criticism of them.

    The only node needing three pieces of state at once: the candidates, the
    criticism, and the PROFILE. The profile matters because the restrictions the
    investor stated are re-checked here, at the last gate before a person reads
    anything, and because a brief is supposed to say plainly when a company is a
    poor fit for their risk tolerance or their horizon.

    Runs even when nothing survived: the decision records WHY there is no
    recommendation, which is a more useful output than an absent key.
    """
    try:
        final = decide(
            state["company_findings"],
            state["risk_findings"],
            state["investor_profile"],
        )
    except Exception as exc:  # noqa: BLE001 - same reasoning as the other nodes
        # Up to three model calls sit behind this. None of them failing should
        # reach the user as a traceback.
        return {"error": f"Decision failed: {type(exc).__name__}: {exc}"}

    return {"decision": final}


def route_risk(state: InvestmentState) -> str:
    """Continue to the decision unless the critic failed outright.

    ``found_nothing`` is deliberately NOT a failure, for the same reason as
    everywhere upstream: every candidate withstanding criticism is a legitimate
    result, and the decision stage is what turns that into an answer.
    """
    if state.get("error"):
        return "failed"
    return "ok"


def route_research(state: InvestmentState) -> str:
    """Continue to company analysis unless research failed outright.

    ``found_nothing`` is deliberately NOT a failure. It means no theme cleared
    the evidence bar, which is a legitimate result the pipeline is designed to
    produce, and the company stage reports it rather than the graph hiding it.
    """
    if state.get("error"):
        return "failed"
    return "ok"


def route_companies(state: InvestmentState) -> str:
    """Continue to the risk critic unless company analysis failed outright.

    ``found_nothing`` is deliberately NOT a failure, for the same reason as in
    ``route_research``: the themes may be real while no company mentioned
    alongside them is both investable and genuinely exposed. The critic records
    that there was nothing to criticise rather than the graph hiding it.
    """
    if state.get("error"):
        return "failed"
    return "ok"


builder = StateGraph(InvestmentState)

builder.add_node("profile_agent", profile_node)
builder.add_node("clarification", clarification_node)
builder.add_node("clarification_exhausted", clarification_exhausted_node)
builder.add_node("research", research_node)
builder.add_node("companies", company_node)
builder.add_node("risk_critic", risk_node)
builder.add_node("decide", decide_node)

builder.add_edge(START, "profile_agent")

builder.add_conditional_edges(
    "profile_agent",
    route_profile,
    {
        "valid": "research",
        "clarification": "clarification",
        "exhausted": "clarification_exhausted",
        "failed": END,
    },
)

builder.add_edge("clarification", "profile_agent")
builder.add_edge("clarification_exhausted", END)

# Research feeds company analysis, unless the research node itself failed.
builder.add_conditional_edges(
    "research",
    route_research,
    {"ok": "companies", "failed": END},
)

# Company analysis feeds the risk critic, unless the company node itself failed.
builder.add_conditional_edges(
    "companies",
    route_companies,
    {"ok": "risk_critic", "failed": END},
)

# The critic feeds the decision, unless the critic node itself failed.
builder.add_conditional_edges(
    "risk_critic",
    route_risk,
    {"ok": "decide", "failed": END},
)

# The decision is the end of the pipeline. `decision.recommended_nothing` being
# True is a real answer and not a failure - it is the outcome the whole design
# exists to make possible, and `no_recommendation_reason` says which kind of
# nothing it is.
builder.add_edge("decide", END)


# The checkpointer saves state at every step so an interrupted graph can resume.
# InMemorySaver keeps it in RAM: fine for development, but everything is lost
# when the process exits. Swap for SqliteSaver before this is used for real.
serializer = JsonPlusSerializer(
    allowed_msgpack_modules=[
        UserInput,
        InvestorProfile,
        # Agent 2's output, including the nested types, or resuming an
        # interrupted graph would fail to reconstruct them.
        ResearchFindings,
        Theme,
        Evidence,
        Article,
        # Agent 3's output and its nested types, or resuming an interrupted
        # graph could not reconstruct them.
        CompanyFindings,
        CompanyCandidate,
        DroppedCompany,
        Fundamentals,
        ComparableMetrics,
        CurrencyAmounts,
    ]
)

memory = InMemorySaver(serde=serializer)

investment_graph = builder.compile(checkpointer=memory)
