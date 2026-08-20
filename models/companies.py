"""Agent 3 output models — the contract handed to Agent 4 (risk critic).

THREE IDEAS SHAPE THIS FILE, ALL OF THEM LEARNED BY PROBING THE LIVE APIS.

1. The model never writes a ticker.
   It extracts a company NAME as the article wrote it. Resolving that name to a
   ticker is done by a provider search and verified in Python. A hallucinated
   ticker is uniquely dangerous because it does not look wrong: NVDA, NVDA.NE
   and NVD.DE are all real symbols for "Nvidia", and analysing the wrong one
   produces confident, plausible, incorrect financials.

2. Comparable ratios and currency amounts are SEPARATE objects.
   Fundamentals arrive in local currency - USD, HKD, INR and GBp were all seen
   in one sample, and GBp is pence, a sub-unit. Ranking on raw amounts across
   exchanges is meaningless. Rather than write a comment asking future code not
   to do that, the two kinds of number live in different types: ranking touches
   ``ComparableMetrics``, and ``CurrencyAmounts`` is for display only.

3. Rejections are recorded, not discarded.
   Most mentioned companies will not become candidates - private, no listing, a
   subsidiary, an incidental mention, or screened out. Keeping the reasons is
   what tells you whether "3 candidates from 30 mentions" is good filtering or a
   broken resolver. Without it, both look identical.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# --- Controlled vocabularies -------------------------------------------------

ExposureLevel = Literal["direct", "partial", "incidental"]
"""How much a company actually stands to be affected by a theme.

Coarse on purpose. A model asked to score exposure 0-100 returns 70 or 80 with
no calibration behind it; asked to choose one of three clearly defined levels it
gives an answer that means something.
"""

DataSource = Literal["fmp", "yfinance"]
"""Which provider supplied the numbers.

Recorded per company because the two disagree on units and periods, so knowing
the origin is necessary to interpret or debug a figure.
"""

DropReason = Literal[
    "no_ticker_found",
    "not_publicly_traded",
    "not_an_operating_company",
    "no_fundamentals",
    "incidental_mention",
    "failed_screen",
    "duplicate",
]


class CompanyMention(BaseModel):
    """A company the model spotted in an article. Names only, never tickers."""

    name: str = Field(
        description=(
            "The company name exactly as the article writes it. Do NOT supply a "
            "ticker symbol; ticker resolution is done from a provider database."
        )
    )
    article_id: str = Field(
        description="Label of the article this mention came from, e.g. 'A3'."
    )
    context: str = Field(
        description=(
            "One short sentence on what the article says this company is doing."
        )
    )


class MentionExtraction(BaseModel):
    """What the LLM returns in stage 1 of Agent 3.

    Note the absence of a ticker field anywhere in this object. The model has no
    way to express one, so it cannot invent one.
    """

    mentions: list[CompanyMention] = Field(
        default_factory=list,
        description=(
            "Companies named in the articles. Include a company only if the "
            "article actually names it. Return an empty list if none are named."
        ),
    )


class ComparableMetrics(BaseModel):
    """Unitless ratios. SAFE to compare and rank across exchanges.

    Every value here is dimensionless, so a Hong Kong company and a US one can
    be ranked against each other without any currency conversion.

    ``debt_to_equity`` is stored as a RATIO. The two providers disagree: for AMD,
    FMP reports 0.0636 while yfinance reports 6.3610 for the same quantity -
    exactly 100x apart, because yfinance expresses it as a percentage. The client
    normalises to a ratio at the boundary so nothing downstream has to know or
    care which provider a company came from.
    """

    revenue_growth: float | None = Field(
        default=None, description="Year-over-year revenue growth, e.g. 0.34 = 34%."
    )
    gross_margin: float | None = Field(
        default=None, description="Gross profit / revenue, e.g. 0.53 = 53%."
    )
    operating_margin: float | None = Field(
        default=None, description="Operating income / revenue."
    )
    debt_to_equity: float | None = Field(
        default=None,
        description="Total debt / shareholder equity as a RATIO, e.g. 0.06.",
    )

    @property
    def completeness(self) -> float:
        """Fraction of metrics actually available.

        A company with two of four metrics should not be ranked as confidently
        as one with all four, and screening rules need to know when a value is
        missing rather than treating None as zero.
        """
        values = [
            self.revenue_growth,
            self.gross_margin,
            self.operating_margin,
            self.debt_to_equity,
        ]
        return sum(v is not None for v in values) / len(values)


class CurrencyAmounts(BaseModel):
    """Absolute figures in ``currency``. NEVER compare these across companies.

    Kept in their own type precisely so that ranking code cannot reach them by
    accident. A comment saying "do not compare these" would be ignored eventually;
    a separate object makes the mistake visible.
    """

    currency: str = Field(
        description="ISO-ish code as the provider reports it, e.g. USD, HKD, GBp."
    )
    net_income: float | None = None
    free_cash_flow: float | None = None


class Fundamentals(BaseModel):
    """Financial health for one company, from one provider."""

    comparable: ComparableMetrics
    amounts: CurrencyAmounts
    source: DataSource
    as_of: date | None = Field(
        default=None, description="Period end date of the reported figures."
    )


class ExposureVerdict(BaseModel):
    """The LLM's judgment on whether a company is genuinely tied to a theme.

    ``company_id`` is a short label ('C2') that Python assigned, for the same
    reason Agent 2's citations use '[A3]': a model copies a two-character label
    reliably and a long identifier unreliably.
    """

    company_id: str = Field(description="Label of a listed company, e.g. 'C2'.")
    exposure: ExposureLevel = Field(
        description=(
            "'direct' - the theme materially drives this company's business. "
            "'partial' - real but secondary exposure. "
            "'incidental' - merely named in the article, or barely affected."
        )
    )
    rationale: str = Field(
        description="One short sentence, under 20 words, justifying the level."
    )


class ExposureAssessment(BaseModel):
    """What the LLM returns in stage 2 of Agent 3."""

    verdicts: list[ExposureVerdict] = Field(default_factory=list)


class CompanyCandidate(BaseModel):
    """An investable company that survived screening. Assembled by Python."""

    ticker: str
    name: str
    exchange: str
    currency: str

    fundamentals: Fundamentals

    exposure: ExposureLevel
    exposure_rationale: str

    themes: list[str] = Field(
        default_factory=list, description="Theme names this company relates to."
    )
    evidence_article_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Real article uuids from Agent 2 that mentioned this company, so "
            "every candidate traces back to retrieved evidence."
        ),
    )

    screen_score: float = Field(
        default=0.0,
        description=(
            "Ranking score computed in PYTHON from ComparableMetrics and the "
            "exposure level. Deliberately not a number the model invented - see "
            "the note in the module docstring of the ranking code."
        ),
    )

    @model_validator(mode="after")
    def must_trace_to_evidence(self) -> "CompanyCandidate":
        """A candidate with no supporting article did not come from the research.

        Agent 3 exists to analyse companies that Agent 2's articles surfaced. One
        that traces to nothing arrived some other way, which means the pipeline
        leaked.
        """
        if not self.evidence_article_ids:
            raise ValueError(
                f"candidate {self.ticker!r} cites no article; every candidate "
                "must trace back to evidence retrieved by Agent 2"
            )
        return self


class DroppedCompany(BaseModel):
    """A mentioned company that did not become a candidate, and why."""

    name: str
    reason: DropReason
    detail: str | None = None


class CompanyFindings(BaseModel):
    """The final Agent 3 output. Agent 4 consumes this."""

    candidates: list[CompanyCandidate] = Field(default_factory=list)
    dropped: list[DroppedCompany] = Field(default_factory=list)

    mentions_extracted: int = 0
    notes: str | None = None

    @property
    def found_nothing(self) -> bool:
        """True when no company survived. A legitimate outcome, not a failure."""
        return not self.candidates

    @property
    def drop_summary(self) -> dict[str, int]:
        """How many companies fell out at each stage.

        The single most useful debugging view in this agent. If almost everything
        is 'no_ticker_found', the resolver is broken. If almost everything is
        'incidental_mention', the extraction step is too eager.
        """
        counts: dict[str, int] = {}
        for drop in self.dropped:
            counts[drop.reason] = counts.get(drop.reason, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
