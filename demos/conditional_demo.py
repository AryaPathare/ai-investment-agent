from typing import TypedDict
from langgraph.graph import StateGraph, START, END


class UserState(TypedDict):
    name: str
    age: int
    status: str


def check_age(state: UserState):
    if state["age"] >= 18:
        return {"status": "valid"}
    else:
        return {"status": "invalid"}


def choose_path(state: UserState):
    if state["status"] == "valid":
        return "approved"
    else:
        return "rejected"


def approved(state: UserState):
    print(f"{state['name']} passed validation.")
    return {}


def rejected(state: UserState):
    print(f"{state['name']} did not pass validation.")
    return {}


builder = StateGraph(UserState)

builder.add_node("check_age", check_age)
builder.add_node("approved", approved)
builder.add_node("rejected", rejected)

builder.add_edge(START, "check_age")

builder.add_conditional_edges(
    "check_age",
    choose_path,
    {
        "approved": "approved",
        "rejected": "rejected"
    }
)

builder.add_edge("approved", END)
builder.add_edge("rejected", END)

graph = builder.compile()

result = graph.invoke({
    "name": "Arya",
    "age": 15,
    "status": "pending"
})

print(result)