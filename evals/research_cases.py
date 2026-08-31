"""Evaluation profiles for Agent 2.

WHY THESE ARE SCORED DIFFERENTLY FROM AGENT 1'S
------------------------------------------------
Agent 1's cases had a single correct answer: a profile either contains a
contradiction or it does not, so accuracy is meaningful.

Agent 2 has no correct answer. Two competent analysts reading the same fifteen
articles would produce different themes, and neither would be wrong. Scoring
"did it pick the right themes" would mean scoring against one arbitrary opinion.

So we measure PROCESS QUALITY instead — properties that must hold regardless of
which themes were chosen, and most of which are mechanically checkable:

    Does every citation point at an article that was actually retrieved?
    Do the cited URLs actually exist?
    Did it avoid areas the investor explicitly ruled out?
    Did it pad the list to the maximum with thin, single-source themes?
    Does it ever report evidence that WEAKENS a theme, or only supporting ones?

None of that requires waiting to see whether a stock went up, which is what
makes it usable today. It is also the honest framing: this is a research
assistant, and a research assistant is judged on whether its sourcing is sound.

Each profile below probes something specific.
"""

from dataclasses import dataclass, field

from models.profile import InvestorProfile


@dataclass(frozen=True)
class ResearchCase:
    name: str
    probes: str
    profile: InvestorProfile
    # Words that must not appear in a theme if the restriction is respected.
    forbidden_terms: tuple[str, ...] = field(default_factory=tuple)
    # Words we would expect a relevant theme to touch on. Advisory only.
    expected_terms: tuple[str, ...] = field(default_factory=tuple)


def _profile(**overrides) -> InvestorProfile:
    base = dict(
        age=30,
        investment_experience="intermediate",
        risk_tolerance="moderate",
        investment_amount=5000.0,
        holding_period="3-5 years",
        sectors_of_interest=["technology"],
        restrictions=[],
        status="valid",
    )
    return InvestorProfile(**{**base, **overrides})


CASES: list[ResearchCase] = [
    ResearchCase(
        name="renewables_excluding_fossil_fuels",
        probes=(
            "Do restrictions flow all the way through to the themes? The "
            "adjacent, obvious topic is exactly the one that is forbidden."
        ),
        profile=_profile(
            sectors_of_interest=["renewable energy"],
            restrictions=["No fossil fuel companies", "No coal, oil or gas"],
        ),
        forbidden_terms=("fossil fuel", "coal", "crude oil", "natural gas", "petroleum"),
        expected_terms=("solar", "wind", "battery", "hydrogen", "grid", "renewable"),
    ),
    ResearchCase(
        name="healthcare_low_risk_near_retirement",
        probes=(
            "The run that previously returned exactly five themes, three of them "
            "single-source and low confidence. Does it pad to the cap?"
        ),
        profile=_profile(
            age=66,
            risk_tolerance="low",
            sectors_of_interest=["healthcare"],
            holding_period="1-2 years",
        ),
        expected_terms=("health", "drug", "pharma", "fda", "medical", "biotech", "care"),
    ),
    ResearchCase(
        name="sports_and_technology_beginner",
        probes=(
            "Previously retrieved only two articles and correctly returned zero "
            "themes. Does it keep declining rather than inventing?"
        ),
        profile=_profile(
            age=20,
            investment_experience="beginner",
            sectors_of_interest=["sports", "technology"],
            holding_period="10+ years",
        ),
        expected_terms=("sport", "tech", "media", "streaming", "device", "ai"),
    ),
    ResearchCase(
        name="semiconductors_high_risk",
        probes=(
            "A well-covered sector where plenty of evidence exists. Confidence "
            "should be higher here than in thin sectors, if it is calibrated."
        ),
        profile=_profile(
            risk_tolerance="high",
            sectors_of_interest=["semiconductors", "artificial intelligence"],
            investment_amount=25000.0,
        ),
        expected_terms=("chip", "semiconductor", "ai", "data cent", "foundry", "gpu"),
    ),
    ResearchCase(
        name="banking_excluding_crypto",
        probes="A second restriction case, in a sector where the ruled-out topic is nearby.",
        profile=_profile(
            sectors_of_interest=["banking", "financial services"],
            restrictions=["No cryptocurrency or digital asset companies"],
        ),
        forbidden_terms=("crypto", "bitcoin", "digital asset", "stablecoin", "token"),
        expected_terms=("bank", "lending", "payment", "regulat", "interest rate"),
    ),
]
