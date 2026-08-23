"""Agent 4 output models — the contract handed to Agent 5.

THE CENTRAL IDEA: a risk that cites nothing is not a risk.

The failure mode this agent exists to avoid is not missing a danger. It is
MANUFACTURING one. Asked to criticise a company, a model will always find
something to say: competition is intense, valuation is stretched, macro
conditions are uncertain. Every one of those sentences is true of every company
ever listed, which makes them worth nothing. They read like analysis and carry
no information.

So every ``Risk`` must be anchored to something outside the model's opinion,
and the schema gives it exactly two places to anchor:

* ``article_ids`` — uuids of articles the news client actually retrieved. The
  model cannot write a title, a URL or a date, so it cannot invent a source.
  Same mechanism as Agent 2's themes.
* ``metric`` — the name of a fundamental Agent 3 already measured, with the
  value Python read from the provider.

A risk with neither is rejected by the validator. Not discouraged, not
down-weighted: rejected, because there is no way to check it.

WHO PRODUCES WHAT

Fundamental risks are computed by PYTHON from the numbers Agent 3 collected.
They are reproducible, inspectable and always available even when news
retrieval returns nothing. News risks come from the LLM, which is reading prose
and judging whether it undermines the thesis — the thing models are actually
good at.

Severity is the model's judgement. The per-candidate VERDICT is arithmetic over
those severities, computed in Python. This is the same division of labour as
Agent 3's screening: the model contributes judgement about language, and the
part that has to be consistent between companies is not left to it.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from models.research import Article

# --- Controlled vocabularies -------------------------------------------------
# Fixed sets rather than free text, for the same reason as everywhere else in
# this project: a bounded choice means something, and can be counted across
# runs. It also forces specificity — a model that must pick a TYPE cannot hide
# behind "there are various risks".

RiskType = Literal[
    "competitive",          # a rival, a substitute, pricing pressure
    "regulatory",           # law, licence, investigation, sanction
    "financial",            # leverage, cash burn, margin compression
    "execution",            # delay, recall, failed launch, key-person loss
    "concentration",        # one customer, one product, one geography
    "thesis_invalidation",  # the theme itself is weaker than Agent 2 thought
]
"""What KIND of thing could go wrong.

Deliberately excludes a "market" or "general" option. Broad market risk applies
to every equity, so recording it distinguishes nothing and would let the model
fill its quota with sentences that survive no scrutiny. If the only thing to be
said about a company is that shares can fall, that is a finding of NO risk.
"""

RiskSeverity = Literal["critical", "material", "minor"]
"""How much this should weigh on the decision.

    critical  - undermines the reason for holding it at all
    material  - a real cost to the thesis; changes the size of the case
    minor     - worth knowing, would not change a decision on its own

Three levels, not a 0-100 score, for the reason given throughout this project:
a model asked for a number invents a precise-looking one. Three defined buckets
give an answer that can be compared between companies and between runs.
"""

CandidateVerdict = Literal["survives", "weakened", "disqualified"]
"""The outcome of criticism for one candidate. Computed in Python, never asked
of the model — see the module docstring."""


class Risk(BaseModel):
    """One specific, grounded reason a candidate could fail."""

    ticker: str = Field(
        description="Ticker of the candidate this risk applies to, exactly as given."
    )
    risk_type: RiskType
    severity: RiskSeverity
    claim: str = Field(
        description=(
            "One sentence naming the specific mechanism of harm. Not 'faces "
            "competition' but 'Samsung's new fab adds supply in the segment "
            "that produced most of last year's margin'."
        )
    )

    article_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Uuids of retrieved articles supporting this risk, exactly as "
            "shown. Only ids that appear in the provided list are valid."
        ),
    )
    metric: str | None = Field(
        default=None,
        description=(
            "For a risk read from the fundamentals rather than the news: the "
            "metric name, e.g. 'debt_to_equity'. Set by Python, not the model."
        ),
    )
    metric_value: float | None = Field(
        default=None, description="The measured value behind ``metric``."
    )

    @field_validator("article_ids", mode="before")
    @classmethod
    def null_means_none_cited(cls, value):
        """Treat ``null`` as an empty list.

        REGRESSION: the model writes ``"article_ids": null`` when a risk is
        grounded in a metric instead of an article - which is correct, and
        exactly what the prompt asks for. Pydantic rejected the whole object
        over it, so a good risk was thrown away because of how the absence was
        spelled.

        This could NOT be recovered by ``agents/structured.py``: the failure
        arrives as a client-side parse error carrying no rejected payload, not
        as a provider 400 with ``failed_generation``. The only place to absorb
        it is here.

        Loosens the transport, never the contract - a risk still has to cite
        an article or a metric, and ``must_be_grounded`` still refuses one that
        cites neither.
        """
        return [] if value is None else value

    @model_validator(mode="after")
    def must_be_grounded(self) -> "Risk":
        """A risk anchored to nothing cannot be checked, so it is not kept.

        This is the validator the whole agent rests on. Without it the output is
        indistinguishable from fluent guessing, and a reader has no way to tell
        which sentences were derived from evidence and which were produced
        because a critic was asked for criticism and obliged.
        """
        if not self.article_ids and self.metric is None:
            raise ValueError(
                f"risk {self.claim[:60]!r} cites neither an article nor a "
                "metric; every risk must be traceable to evidence"
            )
        return self

    @property
    def is_fundamental(self) -> bool:
        """True when this came from the numbers rather than from the news."""
        return self.metric is not None


class CandidateCritique(BaseModel):
    """Everything the critic found — or failed to find — about one candidate.

    ``queries_used`` and ``articles_reviewed`` matter as much as ``risks``. An
    empty risk list means one of two very different things: the company was
    attacked and held up, or nothing was ever looked at. Without the effort
    recorded, Agent 5 cannot tell those apart, and "no risks found" would read
    as reassurance when it might be silence.
    """

    ticker: str
    name: str

    risks: list[Risk] = Field(default_factory=list)

    queries_used: list[str] = Field(default_factory=list)
    articles_reviewed: int = 0
    skipped_reason: str | None = Field(
        default=None,
        description=(
            "Set when this candidate was not critiqued at all, e.g. it fell "
            "outside the per-run critique cap. Never left implicit."
        ),
    )

    @property
    def was_critiqued(self) -> bool:
        """False when the candidate was skipped rather than examined."""
        return self.skipped_reason is None

    @property
    def severity_counts(self) -> dict[str, int]:
        """How many risks of each severity, most severe first."""
        counts = {"critical": 0, "material": 0, "minor": 0}
        for risk in self.risks:
            counts[risk.severity] += 1
        return counts

    @property
    def verdict(self) -> CandidateVerdict:
        """Arithmetic over severities. Deliberately not a model judgement.

        One critical risk disqualifies: 'the reason to hold this no longer
        holds' is not something two material risks add up to. Two material
        risks weaken, because a single material risk is the normal condition of
        every real company and demoting on it would demote everything.

        A candidate that was never critiqued reports ``survives``, which is
        honest only because ``was_critiqued`` sits beside it. Agent 5 must read
        both — a verdict alone would silently promote whatever the cap skipped.
        """
        counts = self.severity_counts
        if counts["critical"] >= 1:
            return "disqualified"
        if counts["material"] >= 2:
            return "weakened"
        return "survives"


class RiskFindings(BaseModel):
    """The final Agent 4 output, assembled by Python. Agent 5 consumes this."""

    critiques: list[CandidateCritique] = Field(default_factory=list)

    articles: list[Article] = Field(default_factory=list)
    """The bear-case articles that ended up CITED, deduplicated.

    Without these a risk's ``article_ids`` point at nothing reachable: Agent 5
    could not show a reader the source, and the eval could not check that the
    citation resolves at all. Agent 2 keeps its cited articles for exactly the
    same reason — a citation is only worth something if it can be followed.

    Only cited articles are kept. Retrieval pulls far more than it uses, and
    carrying the unused ones would bloat the state that flows to Agent 5 without
    making anything checkable.
    """

    articles_retrieved: int = 0
    """Bear-case articles pulled across every candidate, before deduplication.

    Kept beside ``articles`` because the gap between them is informative: 40
    retrieved and 2 cited says the searches worked and the model was selective;
    0 retrieved says the searches found nothing and no amount of prompting
    would have helped."""

    risks_discarded: int = 0
    """Risks the model produced that cited no retrievable article.

    Kept visible rather than silently dropped. A number climbing here is the
    early warning that the model is inventing sources, which is exactly the
    failure this agent is built to prevent — and it would otherwise be
    invisible, because the output would still look clean.
    """

    notes: str | None = None

    @property
    def found_nothing(self) -> bool:
        """True when no risk was found against any candidate.

        A legitimate outcome, but an unusual one, and worth Agent 5 treating
        with suspicion rather than relief: it is far more often a sign that
        retrieval returned nothing than that every candidate is sound.
        """
        return not any(c.risks for c in self.critiques)

    @property
    def disqualified(self) -> list[str]:
        """Tickers a critical risk ruled out."""
        return [c.ticker for c in self.critiques if c.verdict == "disqualified"]

    def critique_for(self, ticker: str) -> CandidateCritique | None:
        """The critique of one candidate, if it was produced."""
        return next((c for c in self.critiques if c.ticker == ticker), None)

    def article_by_id(self, article_id: str) -> Article | None:
        """Find a cited article. By assembly time, ids are real uuids."""
        return next((a for a in self.articles if a.uuid == article_id), None)


class NewsRiskAssessment(BaseModel):
    """What the LLM returns for ONE candidate: news-derived risks only.

    Separate from ``RiskFindings`` on purpose. The model is handed one company
    and the articles retrieved against it, and returns just the risks it can
    support from that prose. It never sees the fundamental risks Python
    computed, never assigns a verdict, and never writes the assembled output.

    Keeping the model's job this narrow is what makes its contribution
    checkable: everything it returns can be validated against a list of article
    ids that Python controls.
    """

    risks: list[Risk] = Field(
        default_factory=list,
        description=(
            "Risks supported by the supplied articles. Return an EMPTY list if "
            "the articles show nothing that genuinely undermines the case — "
            "that is a real finding, not a failure to try."
        ),
    )
    notes: str | None = Field(
        default=None,
        description="Optional one line on what was looked for and not found.",
    )
