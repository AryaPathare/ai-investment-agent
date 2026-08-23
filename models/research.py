"""Agent 2 output models — the contract handed to Agent 3.

THE CENTRAL IDEA: articles and themes are SEPARATE lists.

``Article`` objects are created by Python from what the news API actually
returned. ``Theme`` objects are created by the LLM, and a theme can only refer
to an article by its ``uuid`` — it has no field in which to write a title, a
URL, or a date.

That separation is what makes fabricated sources impossible rather than merely
discouraged. Inventing a source is the single most common failure of systems
like this: a plausible headline, a real-looking URL, a confident summary, all
of it made up. If the model could nest article objects inside themes, it could
invent them. It cannot, because it has nowhere to put them.

This is the same principle as Agent 1's ProfileAssessment: the model returns
judgment, Python owns the data.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# --- Controlled vocabularies -------------------------------------------------
# Fixed sets rather than free text. A model asked for "confidence 0-100" returns
# 75 or 80 with no calibration behind it; asked to choose one of three levels it
# gives an answer that actually means something. Buckets are also directly
# comparable against the investor's own timeframe, which free text is not.

ThemeConfidence = Literal["high", "medium", "low"]

ThemeTimeframe = Literal[
    "already_underway",
    "within_6_months",
    "6_to_18_months",
    "beyond_18_months",
    "unclear",
]

EvidenceStance = Literal["supports", "weakens", "complicates"]


class Article(BaseModel):
    """One news article, exactly as the provider returned it.

    Built by Python from the API response. The LLM never constructs one of
    these and cannot modify one.
    """

    uuid: str = Field(description="Provider's stable identifier for the article.")
    title: str
    description: str = Field(default="", description="Meta description, ~150 chars.")
    snippet: str = Field(default="", description="Opening of the article body.")
    url: str
    source: str = Field(description="Publisher domain, e.g. reuters.com.")
    published_at: datetime
    categories: list[str] = Field(default_factory=list)

    @property
    def text(self) -> str:
        """Everything we know about the article, for prompting."""
        return f"{self.title}\n{self.description}\n{self.snippet}".strip()


class Evidence(BaseModel):
    """A link from a theme to one retrieved article, and what it shows.

    ``article_id`` holds a SHORT LABEL while the model is proposing themes — the
    "[A3]" style reference it was shown. Python rewrites it to the article's real
    uuid during assembly. Short labels exist because a uuid is 36 hex characters
    and asking a model to transcribe several of those exactly, per response, is
    an invitation to silent corruption. A two-character label it can copy
    reliably; the mapping back is deterministic code.

    ``stance`` exists to fight confirmation bias. An agent that only ever
    collects supporting evidence will find a case for anything. Recording that
    an article weakens or complicates a theme keeps the contradicting evidence
    visible to Agent 4 (the risk critic) instead of quietly discarding it.
    """

    article_id: str = Field(
        description=(
            "Label of a retrieved article exactly as shown, e.g. 'A3'. Only "
            "labels that appear in the provided list are valid."
        )
    )
    stance: EvidenceStance = Field(
        description=(
            "'supports' if the article is evidence FOR the theme. "
            "'weakens' if it is evidence AGAINST it. "
            "'complicates' if it is relevant but cuts both ways."
        )
    )
    relevance: str = Field(
        description="One short sentence on what this article contributes."
    )


class Theme(BaseModel):
    """A trend worth investigating, grounded in retrieved articles."""

    name: str = Field(description="Short name for the theme, a few words.")
    why_it_matters: str = Field(
        description=(
            "Two or three sentences on why this is relevant to THIS investor, "
            "given their chosen sectors, timeframe and risk tolerance."
        )
    )
    industries: list[str] = Field(
        description="Industries or sectors this theme touches.",
    )
    timeframe: ThemeTimeframe
    confidence: ThemeConfidence = Field(
        description=(
            "How strongly the retrieved evidence supports this theme. "
            "'high' only when multiple independent sources agree."
        )
    )
    evidence: list[Evidence] = Field(
        description="Articles backing this theme, cited by uuid."
    )

    @model_validator(mode="after")
    def must_cite_something(self) -> "Theme":
        """A theme with no evidence is, by definition, invented.

        Grounding is the whole point of retrieving articles first. If the model
        proposes a theme it cannot tie to anything it was shown, that theme came
        from its training data or from nowhere, and either way it is not
        current-events research.
        """
        if not self.evidence:
            raise ValueError(
                f"theme {self.name!r} cites no evidence; every theme must be "
                "grounded in at least one retrieved article"
            )
        return self


class ThemeProposal(BaseModel):
    """What the LLM returns: themes only, no article data.

    Note what is absent. There is no place to write an article title, URL or
    date — only uuids to point at articles Python already retrieved. Whether
    those uuids are real is verified in Python afterwards, because a model can
    still cite an id that does not exist.
    """

    themes: list[Theme] = Field(
        default_factory=list,
        description=(
            "Up to 5 themes, strongest first. Return FEWER, or none at all, if "
            "the retrieved articles do not support that many. Never pad the "
            "list to reach a number."
        ),
    )
    notes: str | None = Field(
        default=None,
        description=(
            "Optional: why few or no themes were returned, if that is the case."
        ),
    )


class ResearchFindings(BaseModel):
    """The final Agent 2 output, assembled by Python. Agent 3 consumes this.

    ``articles`` contains only the articles that ended up cited, deduplicated,
    so Agent 3 has exactly the evidence it needs and nothing else. The counts
    are kept for observability: knowing that 40 articles were retrieved and 6
    were cited tells you something that the themes alone do not.
    """

    themes: list[Theme] = Field(default_factory=list)
    articles: list[Article] = Field(default_factory=list)

    queries_used: list[str] = Field(default_factory=list)
    articles_retrieved: int = 0
    notes: str | None = None

    @property
    def found_nothing(self) -> bool:
        """True when no theme cleared the bar.

        A legitimate outcome, not a failure. The system is allowed to conclude
        there is nothing worth investigating right now, and downstream stages
        must handle that rather than assume themes always exist.
        """
        return not self.themes

    def article_by_id(self, article_id: str) -> Article | None:
        """Find a cited article. By assembly time, ids are real uuids."""
        return next((a for a in self.articles if a.uuid == article_id), None)


class SearchQueries(BaseModel):
    """What the LLM returns in step 1 of Agent 2: search terms only.

    A deliberately small job. The model is not deciding what matters yet — it is
    only translating an investor's chosen sectors into terms worth typing into a news
    search. If a query is poor the cost is irrelevant articles, not a wrong
    conclusion, which makes this a low-risk place to use a model.
    """

    queries: list[str] = Field(
        description=(
            "Four to six specific news search queries. Each should target a "
            "concrete development, policy, technology or event — not a broad "
            "sector name."
        )
    )
    reasoning: str | None = Field(
        default=None,
        description="Optional one-line note on the angles chosen.",
    )

    @model_validator(mode="after")
    def clean_queries(self) -> "SearchQueries":
        """Normalise the list: trim, drop blanks, remove case-insensitive repeats.

        Duplicate queries would spend the free tier's daily request budget to
        retrieve articles we already have, and every request counts when the cap
        is 100 a day and each returns only 3 articles.
        """
        seen: set[str] = set()
        cleaned: list[str] = []
        for query in self.queries:
            text = " ".join(query.split())
            if not text or text.lower() in seen:
                continue
            seen.add(text.lower())
            cleaned.append(text)

        if not cleaned:
            raise ValueError("no usable search queries were produced")

        self.queries = cleaned
        return self
