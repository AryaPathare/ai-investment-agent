from typing import TypedDict
from langgraph.graph import StateGraph, START, END


class DemoState(TypedDict):
    message: str
    status: str


def clean_message(state: DemoState):
    cleaned = state["message"].strip()
    return {"message": cleaned}


def mark_complete(state: DemoState):
    return {"status": "complete"}


builder = StateGraph(DemoState)

builder.add_node("clean_message", clean_message)
builder.add_node("mark_complete", mark_complete)

builder.add_edge(START, "clean_message")
builder.add_edge("clean_message", "mark_complete")
builder.add_edge("mark_complete", END)

graph = builder.compile()

result = graph.invoke({
    "message": "   Hello from LangGraph!   ",
    "status": "pending"
})

print(result)