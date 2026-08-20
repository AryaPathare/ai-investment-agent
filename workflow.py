from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from models.state import InvestmentState
from models.user_input import UserInput
from models.profile import InvestorProfile
from agents.profile_agent import create_investor_profile


def profile_node(state: InvestmentState):
    user_input = state["user_input"]

    clarification = state.get("clarification_response")

    profile = create_investor_profile(
        user_input,
        clarification
    )

    return {
        "investor_profile": profile
    }


def route_profile(state: InvestmentState):
    profile = state["investor_profile"]

    if profile.needs_clarification:
        return "clarification"

    return "valid"


def clarification_node(state: InvestmentState):
    profile = state["investor_profile"]

    response = interrupt({
        "reason": profile.clarification_reason,
        "question": "Please clarify your preference."
    })

    return {
        "clarification_response": response
    }


builder = StateGraph(InvestmentState)

builder.add_node("profile_agent", profile_node)
builder.add_node("clarification", clarification_node)

builder.add_edge(START, "profile_agent")

builder.add_conditional_edges(
    "profile_agent",
    route_profile,
    {
        "valid": END,
        "clarification": "clarification"
    }
)

builder.add_edge(
    "clarification",
    "profile_agent"
)


serializer = JsonPlusSerializer(
    allowed_msgpack_modules=[
        UserInput,
        InvestorProfile
    ]
)

memory = InMemorySaver(
    serde=serializer
)

investment_graph = builder.compile(
    checkpointer=memory
)