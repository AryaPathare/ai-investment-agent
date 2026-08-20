from langgraph.types import Command

from models.user_input import UserInput
from workflow import investment_graph


user = UserInput(
    age=20,
    investment_experience="beginner",
    risk_tolerance="moderate",
    investment_amount=1000,
    investment_window="within 1 month",
    holding_period="3-5 years",
    interests=["sports", "technology"],
    restrictions=["Do not invest in technology companies"]
)


config = {
    "configurable": {
        "thread_id": "test-user-1"
    }
}


result = investment_graph.invoke(
    {
        "user_input": user
    },
    config
)


while "__interrupt__" in result:

    interrupt_data = result["__interrupt__"][0].value

    print("\nClarification needed:")
    print(interrupt_data["reason"])

    clarification = input(
        f"{interrupt_data['question']}\n> "
    )

    result = investment_graph.invoke(
        Command(resume=clarification),
        config
    )


print("\nFinal result:")
print(result)