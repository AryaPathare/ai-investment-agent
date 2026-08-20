from models.user_input import UserInput
from agents.profile_agent import create_investor_profile


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

profile = create_investor_profile(user)

print(profile)