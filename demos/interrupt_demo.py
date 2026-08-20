from typing import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.memory import InMemorySaver


class UserState(TypedDict):
    name: str
    age: int
    status: str


def validate_age(state: UserState):
    age = state["age"]

    while age < 18:
        age = interrupt(
            f"{state['name']}, your age must be at least 18. "
            "Please enter your age again."
        )

    return {
        "age": age,
        "status": "valid"
    }


def approved(state: UserState):
    print(f"{state['name']} passed validation.")
    return {}


builder = StateGraph(UserState)

builder.add_node("validate_age", validate_age)
builder.add_node("approved", approved)

builder.add_edge(START, "validate_age")
builder.add_edge("validate_age", "approved")
builder.add_edge("approved", END)

memory = InMemorySaver()

graph = builder.compile(checkpointer=memory)


config = {
    "configurable": {
        "thread_id": "user-1"
    }
}


result = graph.invoke(
    {
        "name": "Arya",
        "age": 15,
        "status": "pending"
    },
    config
)


while "__interrupt__" in result:

    message = result["__interrupt__"][0].value
    print(message)

    new_age = int(input("New age: "))

    result = graph.invoke(
        Command(resume=new_age),
        config
    )


print(result)