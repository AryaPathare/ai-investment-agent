"""Agent 5 output models — the only thing in this project a person reads.

THE CENTRAL IDEA: recommending nothing must be as expressible as recommending
something, and both must say why.

Every earlier agent could hide a weakness behind a plausible-looking field. A
theme with one citation still looks like a theme; a candidate scoring 0.31 still
looks like a candidate. This is the stage where that stops being survivable,
because the output is prose a human will act on, and prose is exactly where an
unsupported claim is hardest to see.

So two things are structural rather than encouraged:

* A ``Decision`` with no recommendations MUST carry the reason there are none.
  "All three were disqualified by a critical risk" and "none of them were ever
  examined" are completely different messages, and an empty list says neither.
* An ``ExitCondition`` must cite a risk's article or a measured metric. The same
  rule as Agent 4's risks, for the same reason: "if fundamentals deteriorate" is
  a sentence, not a condition. Nobody can ever tell whether it has happened.

WHAT THIS DELIBERATELY DOES NOT CONTAIN

No position sizes, no allocation, no split of the investor's money. The profile
carries ``investment_amount`` and dividing it three ways would be two lines of
code. That is the point where research becomes advice, and this project is not
licensed to give any. The boundary is easier to hold in a schema that has
nowhere to put a number than in a prompt asking the model not to.

No new score. Agent 3's ``screen_score`` is arithmetic over provider data and
Agent 4's ``verdict`` is arithmetic over severities. Selection here orders by
those two and invents nothing, so a reader asking "why is this one first" gets
an answer that can be recomputed rather than a number a model preferred.
"""

from typing import Literal

from models.companies import MarketPrice
from pydantic import BaseModel, Field, field_validator, model_validator

from models.risk import CandidateVerdict

# The most companies this system will ever put in front of someone. Three is a
# judgement, not a finding: enough to show that alternatives were weighed, few
# enough that each one had to earn its place. Returning fewer is normal and
# returning none is a legitimate answer.
MAX_RECOMMENDATIONS = 3


ExclusionReason = Literal[
    "disqualified_by_risk",   # a critical risk broke the thesis
    "not_critiqued",          # never attacked, so "survives" was not earned
    "restriction_violation",  # breaches something the investor ruled out
    "outside_top_three",      # sound, but ranked below the cap
]
"""Why a candidate that reached Agent 5 is not being recommended.

Every candidate ends as a recommendation or one of these. A company that simply
vanished between the ranking and the output would be the one failure a reader
could never detect, because nothing in the output would refer to it.

There is deliberately no "weakened_by_risk". A weakened candidate is still
selectable - it just ranks below one that survived - so when it does not make
the cut the honest reason is that something outranked it, which is
``outside_top_three``. A second reason meaning almost the same thing would only
make the summary harder to read.
"""


class ExitCondition(BaseModel):
    """Something that, if it happened, would mean the thesis has broken.

    The most useful part of the output and the easiest to fill with mush. "If
    the company underperforms" is unfalsifiable; "if the FTC probe results in a
    fine" and "if debt-to-equity rises above 3.0" are things a person can check
    in six months and get a yes or a no.
    """

    condition: str = Field(
        description=(
            "One sentence naming an OBSERVABLE event or threshold. It must be "
            "possible to answer 'has this happened yet?' with yes or no."
        )
    )

    article_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Uuids of articles behind the risk this condition tracks, exactly "
            "as shown. Only ids that appear in the provided list are valid."
        ),
    )
    metric: str | None = Field(
        default=None,
        description=(
            "For a condition on the fundamentals: the metric name, e.g. "
            "'debt_to_equity'."
        ),
    )

    @field_validator("article_ids", mode="before")
    @classmethod
    def null_means_none_cited(cls, value):
        """Treat ``null`` as an empty list.

        REGRESSION: the model writes ``"article_ids": null`` when a condition is
        grounded in a metric instead of an article - which is correct, and
        exactly what the prompt asks for. Pydantic rejected the whole object
        over it, so a good condition was thrown away because of how the absence was
        spelled.

        This could NOT be recovered by ``agents/structured.py``: the failure
        arrives as a client-side parse error carrying no rejected payload, not
        as a provider 400 with ``failed_generation``. The only place to absorb
        it is here.

        Loosens the transport, never the contract - a condition still has to cite
        an article or a metric, and ``must_be_grounded`` still refuses one that
        cites neither.
        """
        return [] if value is None else value

    @model_validator(mode="after")
    def must_be_grounded(self) -> "ExitCondition":
        """A condition anchored to nothing cannot be monitored.

        Same guarantee as Agent 4's risks. Without it the model writes advice
        that sounds prudent and can never be acted on, which is worse than
        writing none: it looks like the question was handled.
        """
        if not self.article_ids and self.metric is None:
            raise ValueError(
                f"exit condition {self.condition[:60]!r} cites neither an "
                "article nor a metric; there would be no way to monitor it"
            )
        return self


class Recommendation(BaseModel):
    """One company being put forward, with the case and the way out."""

    ticker: str
    name: str

    thesis: str = Field(
        description=(
            "Why this company, in two or three sentences. It must connect the "
            "theme to what the company actually sells, not restate the theme."
        )
    )
    exit_conditions: list[ExitCondition] = Field(default_factory=list)

    # Carried through from the earlier agents rather than recomputed, so a
    # reader can trace any of it back and Agent 5 cannot quietly disagree with
    # the stages that produced it.
    screen_score: float
    # Display only, and carried here so the CLI does not have to reach back into
    # Agent 3's output to print it. Optional because a provider may report none,
    # and a brief with no price is better than a brief with a guessed one.
    price: MarketPrice | None = None
    # Worked out in Python at decision time, not in the CLI, for two reasons.
    # The rate is fetched from a provider and the display layer must never do
    # I/O - the demo and a resumed run both print without a network. And a share
    # count computed later would drift from the price it was derived from, which
    # is exactly the pairing a reader is being asked to trust.
    shares_affordable: int | None = None
    price_in_investor_currency: float | None = None
    verdict: CandidateVerdict
    exposure: str
    themes: list[str] = Field(default_factory=list)
    evidence_article_ids: list[str] = Field(default_factory=list)
    known_risks: list[str] = Field(
        default_factory=list,
        description="Claims from Agent 4 that this company still carries.",
    )

    @model_validator(mode="after")
    def must_carry_a_way_out(self) -> "Recommendation":
        """A recommendation with no exit condition is a position with no plan.

        Deliberately structural. Every other part of a brief can be written
        after the fact; this is the part that has to be decided BEFORE, and a
        schema that permits omitting it guarantees it is sometimes omitted.
        """
        if not self.exit_conditions:
            raise ValueError(
                f"{self.ticker!r} has no exit condition; a recommendation must "
                "state what would mean it has stopped being a good idea"
            )
        return self


class ExcludedCompany(BaseModel):
    """A candidate that reached Agent 5 and is not being recommended."""

    ticker: str
    name: str
    reason: ExclusionReason
    detail: str | None = None


class Decision(BaseModel):
    """The final output. Assembled by Python from the stages before it."""

    recommendations: list[Recommendation] = Field(default_factory=list)
    excluded: list[ExcludedCompany] = Field(default_factory=list)

    no_recommendation_reason: str | None = Field(
        default=None,
        description=(
            "Why nothing is being recommended. Required when there are no "
            "recommendations, and forbidden when there are."
        ),
    )

    conditions_discarded: int = 0
    """Exit conditions the model wrote that cited nothing checkable.

    Kept visible rather than silently dropped, for the same reason Agent 4
    counts discarded risks: the output still reads perfectly well when the model
    is inventing, so the only way to notice is to count. A number climbing here
    means the briefs are being written from memory rather than from the evidence
    supplied.
    """

    notes: str | None = None

    @model_validator(mode="after")
    def nothing_must_explain_itself(self) -> "Decision":
        """An empty result has to say which kind of empty it is.

        "Every candidate was disqualified", "none of them were examined" and
        "the research found no companies at all" are three different findings
        that an empty list renders identical. Recommending nothing is a
        first-class outcome here, and a first-class outcome carries a reason.
        """
        if not self.recommendations and not self.no_recommendation_reason:
            raise ValueError(
                "a decision with no recommendations must say why there are none"
            )
        if self.recommendations and self.no_recommendation_reason:
            raise ValueError(
                "no_recommendation_reason is set on a decision that does "
                "recommend something"
            )
        return self

    @model_validator(mode="after")
    def the_cap_is_a_cap(self) -> "Decision":
        if len(self.recommendations) > MAX_RECOMMENDATIONS:
            raise ValueError(
                f"{len(self.recommendations)} recommendations exceeds the "
                f"maximum of {MAX_RECOMMENDATIONS}"
            )
        return self

    @property
    def recommended_nothing(self) -> bool:
        """True when the honest answer was that nothing cleared the bar."""
        return not self.recommendations

    @property
    def exclusion_summary(self) -> dict[str, int]:
        """How many candidates fell out for each reason, most common first.

        The equivalent of Agent 3's drop_summary. If everything reads
        ``not_critiqued``, the critique cap is too tight rather than the
        candidates being poor - a distinction invisible from the output alone.
        """
        counts: dict[str, int] = {}
        for item in self.excluded:
            counts[item.reason] = counts.get(item.reason, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


class CompanyBrief(BaseModel):
    """What the LLM returns for ONE company: the prose, and nothing else.

    Kept as narrow as Agent 4's assessment. The model does not choose which
    companies are recommended, does not order them, does not score them and does
    not see the others. It is handed one company that Python has already
    selected and asked to write the case for it and the ways it could break.

    That is the whole of its job here, and it is a job models are good at:
    turning structured facts into readable prose without inventing any.
    """

    thesis: str = Field(
        description=(
            "Two or three sentences on why this company, connecting the theme "
            "to what it actually sells."
        )
    )
    exit_conditions: list[ExitCondition] = Field(
        default_factory=list,
        description=(
            "Two or three observable things that would mean the case has "
            "broken. Each must cite a supplied article or a named metric."
        ),
    )
