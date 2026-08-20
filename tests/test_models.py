from models.user_input import UserInput
from models.profile import InvestorProfile


user = UserInput(
    age=20,
    investment_experience="beginner",
    risk_tolerance="moderate",
    investment_amount=1000,
    investment_window="within 1 month",
    holding_period="3-5 years",
    interests=["sports", "technology"],
    restrictions=[]
)

print(user)


profile = InvestorProfile(
    age=20,
    investment_experience="beginner",
    risk_tolerance="moderate",
    investment_amount=1000,
    investment_window="within 1 month",
    holding_period="3-5 years",
    interests=["sports", "technology"],
    restrictions=[],
    profile_status="valid",
    clarification_needed=False
)

print(profile)