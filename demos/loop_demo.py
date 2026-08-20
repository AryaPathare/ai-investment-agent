from typing import TypedDict
from langgraph.graph import StateGraph, START, END


class UserState(TypedDict):
    name: str
    age: int
    status: str


def validate_user(state: UserState):
    if state["age"] >= 18:
        return {"status": "valid"}
    else:
        return {"status": "invalid"}


def choose_path(state: UserState):
    if state["status"] == "valid":
        return "approved"
    else:
        return "clarify"


def clarify(state: UserState):
    print(f"{state['name']}, your age must be at least 18.")

    new_age = int(input("Please enter your age again: "))

    return {
        "age": new_age,
        "status": "pending"
    }


def approved(state: UserState):
    print(f"{state['name']} passed validation.")
    return {}


builder = StateGraph(UserState)

builder.add_node("validate_user", validate_user)
builder.add_node("clarify", clarify)
builder.add_node("approved", approved)

builder.add_edge(START, "validate_user")

builder.add_conditional_edges(
    "validate_user",
    choose_path,
    {
        "approved": "approved",
        "clarify": "clarify"
    }
)

builder.add_edge("clarify", "validate_user")

builder.add_edge("approved", END)

graph = builder.compile()

result = graph.invoke({
    "name": "Arya",
    "age": 15,
    "status": "pending"
})

print(result)