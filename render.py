"""One description of a finished run, for every front end that shows it.

WHY THIS FILE EXISTS

The CLI used to walk the models and print in the same breath, which was fine
while printing was the only thing anyone did with a run. It is not any more:
there is now an HTTP layer, and a second walk of the same objects would be a
second set of decisions about what a reader is told - which of two article
stores to look in, whether a metric-only condition counts as grounded, whether
an exclusion's stored detail is fit to show.

Two copies of those decisions drift. This project has recorded that failure
under its own name often enough to treat it as a certainty rather than a risk:
a promise made in prose the code stopped keeping, four times in one review
(entry 49), the rendered log stale within four minutes of being committed
(entry 63), a handoff four sessions out of date and believed (entry 92), a
front page describing a system that no longer existed (entry 94).

So the split is between CONTENT and LAYOUT, and the line is drawn here:

    content   which article grounds this condition, what to call
              `debt_to_equity` in English, whether a company was excluded for
              a reason worth explaining, what "nothing is being recommended"
              says. Same for every reader. Lives in this file.

    layout    line width, banners, bullets, indentation, HTML. Different for
              every reader. Stays in the front end.

The test of the line: if changing it would tell a reader something different,
it is content. If it only changes where the words sit, it is layout.

WHAT `describe_run` RETURNS

Plain JSON-safe values - no Pydantic objects, no datetimes, no enums. That is
not tidiness. A model dumped straight to JSON silently loses every computed
PROPERTY it has, and this pipeline keeps fifteen of them: `recommended_nothing`,
`verdict`, `found_nothing`, `drop_summary`, `in_major_units`. Those are exactly
the judgments a reader needs, so a front end handed a raw dump would have to
re-derive "is this a recommendation of nothing?" from the length of a list -
putting a rule that lives in the model into a second home that nothing tests.
Everything computed is therefore stated explicitly below.
"""

from datetime import date, datetime, timedelta
from typing import get_args

import re

from models.user_input import UserInput

# --- The words a machine name is shown as ------------------------------------

METRIC_WORDS = {
    "revenue_growth": "revenue growth",
    "operating_margin": "operating margin",
    "gross_margin": "gross margin",
    "debt_to_equity": "debt-to-equity",
    "net_income_is_negative": "net income",
    "free_cash_flow_is_negative": "free cash flow",
}
"""The four metrics and two flags, said in English.

The model writes the raw field name into a condition because that is what it
was given and what Python validates against. The reader gets words.
"""

VERDICT_WORDS = {
    "survives": "We argued against this one and it held up.",
    "weakened": "We argued against this one and it mostly held up.",
    "disqualified": "We argued against this one and it did not hold up.",
}

EXCLUSION_WORDS = {
    "outside_top_three": "Ranked just outside the top three.",
    "not_critiqued": "Only a few companies are examined closely each run, and "
                     "this one fell outside that.",
    "restriction_violation": "It runs into something you said you wanted to avoid.",
    "disqualified_by_risk": "A serious problem we found ruled it out.",
}

DETAIL_WORTH_SHOWING = {"disqualified_by_risk", "restriction_violation"}
"""Exclusions whose stored detail describes the COMPANY rather than the run's
bookkeeping.

For the ranking reasons the detail reads "ranked 4 of 5 eligible (weakened,
score 0.997)" - internal, and carrying the score that `agents/screening.py`
records as unreadable as a grade.
"""

REVIEW_AFTER_DAYS = 91
"""How far ahead to point the reader.

Deliberately NOT derived from the stated holding period. That field is free text
- "3-5 years", "a while", "until I need it" - so parsing it is guesswork, and
even parsed it is the wrong number: someone holding for five years should not
first check in five years, because the conditions above are things that could
happen next quarter. Three months is roughly one earnings cycle.
"""

DISCLAIMER = (
    "This is research, not advice. It does not tell you what to buy, or how much."
)

NOTHING_RECOMMENDED = (
    "This is a real answer, not a failure. Everything ran, and nothing it found "
    "was good enough to put in front of you."
)

CLARIFICATION_INTRO = "Two of your answers appear to contradict each other:"

BLANK_CLARIFICATION = "Please say which of the two you would rather keep."
"""Why an empty answer is refused rather than passed on.

The clarification loop is bounded at a small number of attempts and gives up
with a stated outcome. A blank answer would spend one of them and tell the agent
nothing, so both front ends refuse it - and refusing it needs a sentence saying
what would help, which is the same sentence wherever a person reads it.
"""

RATE_LIMIT_HINT = (
    "If this mentions a rate limit or a quota, the daily ceiling has been "
    "reached; try again later. Run python -m scripts.check_setup to tell a "
    "configuration problem from an outage."
)


def plain(text: str) -> str:
    """Make model-written text fit for a reader.

    Two substitutions, both of internal plumbing the model was legitimately
    given and had no way to know was not for publication.

    Field names, because a condition is validated against `debt_to_equity` and
    so that is what the model writes back.

    Citation labels, because articles are numbered [A1], [A2] in the prompt so
    the model can refer to one reliably - a 36-character uuid it cannot copy.
    Python maps the label back to the real article and the source is shown
    separately. By the time a person reads it, "[A1]" names nothing on screen.
    """
    for machine, human in METRIC_WORDS.items():
        text = text.replace(machine, human)

    text = re.sub(r"\s*\[A\d+\]", "", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def as_datetime(value):
    """Accept either a datetime or an ISO string, or give up quietly.

    LangGraph stores a checkpoint's timestamp as an ISO STRING while the demo
    recording and MarketPrice both carry real datetimes. Every caller treats
    this as a courtesy, so an unparseable value returns None and the caller
    stays silent rather than failing a whole run over a date it could not read.
    """
    if value is None or hasattr(value, "strftime"):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def next_review(today: date | None = None) -> date:
    return (today or date.today()) + timedelta(days=REVIEW_AFTER_DAYS)


# --- Grounding ---------------------------------------------------------------


def find_article(article_id: str, state: dict):
    """Look an article id up in both stores that could hold it.

    Exit conditions cite bear-case articles from Agent 4 OR theme articles from
    Agent 2, and neither store knows about the other.
    """
    for findings in (state.get("risk_findings"), state.get("research_findings")):
        if findings is not None:
            article = findings.article_by_id(article_id)
            if article is not None:
                return article
    return None


def grounds_for(condition, state: dict) -> list[dict]:
    """What a reader could go and check to see whether a condition has hit.

    A list rather than a formatted block, because a terminal wants three lines
    lined up under a "Check:" label and a browser wants a link. Each entry says
    what KIND of thing it is, so neither front end has to guess from the shape:

        metric   a number the company reports, named in English
        article  a headline, publisher, date and URL
        missing  an id that resolves in neither store
        none     nothing checkable at all

    ``missing`` is reported rather than printed as a bare uuid: "the source was
    not kept" is information and a hex string on its own is not. ``none`` exists
    for the same reason - silence there looks identical to a citation that
    worked.
    """
    if condition.metric:
        metric = METRIC_WORDS.get(condition.metric, condition.metric)
        return [{"kind": "metric", "text": f"the company's reported {metric}"}]

    out: list[dict] = []
    for article_id in condition.article_ids:
        article = find_article(article_id, state)
        if article is None:
            out.append(
                {
                    "kind": "missing",
                    "article_id": article_id,
                    "text": f"the source for this was not kept ({article_id[:8]})",
                }
            )
            continue
        out.append(
            {
                "kind": "article",
                "title": article.title,
                "source": article.source,
                "published_at": article.published_at.isoformat(),
                "published_on": f"{article.published_at:%d %b %Y}",
                "url": article.url,
            }
        )

    if not out:
        # Unreachable through a validated ExitCondition: the schema refuses to
        # construct one citing neither an article nor a metric, which is the
        # trust boundary doing its job. Kept because this function takes any
        # condition-shaped object, and silence here would look identical to a
        # citation that worked.
        out.append({"kind": "none", "text": "nothing you could go and look up"})
    return out


# --- The investor ------------------------------------------------------------


def profile_parts(user) -> dict:
    """The person this was researched for, as three pieces.

    Read back to them as confirmation of what the system believes they said -
    "will not hold: no restrictions" versus a blank is a statement about their
    answer, not a layout choice, so the WORDS live here.

    Three pieces rather than one string, because joining them with newlines and
    two spaces of indent is a terminal's decision. Returning the joined block
    would put 78-column formatting into what a browser receives, which is the
    boundary this module exists to hold.
    """
    return {
        "headline": (
            f"age {user.age}, {user.investment_experience}, "
            f"{user.risk_tolerance} risk, {user.investment_amount:,.0f} "
            f"held for {user.holding_period}"
        ),
        "sectors": ", ".join(user.sectors_of_interest) or "no sectors given",
        "restrictions": ", ".join(user.restrictions) or "no restrictions",
    }


def affordable_sentence(rec, user) -> str | None:
    """"Your money would buy about N shares", when that can be said honestly.

    The arithmetic is NOT done here. It is computed in Agent 5 alongside the
    price it derives from and stored on the recommendation, so no display layer
    ever touches the network - the demo and a resumed run both render without
    one.

    Absent when there was no price, no stated currency, or no exchange rate,
    which is the same outcome as before conversion existed.
    """
    shares = getattr(rec, "shares_affordable", None)
    currency = getattr(user, "investment_currency", None)
    if shares is None or not currency:
        return None

    # ZERO is a computed answer, not a missing one, and saying so is more use
    # than silence: one share costing more than the whole amount is exactly the
    # thing a beginner has no way to work out from a price in another currency.
    if shares == 0:
        return (
            f"One share costs more than your {currency} "
            f"{user.investment_amount:,.0f}."
        )

    return (
        f"Your {currency} {user.investment_amount:,.0f} would buy about "
        f"{shares:,} share{'' if shares == 1 else 's'}."
    )


def _converted(own, currency: str | None, code: str) -> bool:
    """Whether a price in the reader's own money can honestly be shown.

    All three conditions matter. ``currency`` being unset means they never said
    what their money is in, so there is nothing to convert TO - and a guess
    lands under the one figure in the brief a beginner might act on directly.
    """
    return own is not None and bool(currency) and currency != code


def _price(rec, user) -> dict | None:
    """The share price, in its own currency and in the reader's.

    Both are carried because "CNY 373.00" tells a reader almost nothing on its
    own, and the conversion is Agent 5's - computed next to the price it derives
    from so the two cannot drift apart.
    """
    price = getattr(rec, "price", None)
    if price is None:
        return None

    amount, code = price.in_major_units
    currency = getattr(user, "investment_currency", None) if user else None
    own = getattr(rec, "price_in_investor_currency", None)

    return {
        "amount": amount,
        "currency": code,
        "as_of": price.as_of.isoformat(),
        "as_of_on": f"{price.as_of:%d %b %Y}",
        # Only when the share trades in something other than the reader's money.
        # Same currency twice is noise, not information.
        "in_investor_currency": own if _converted(own, currency, code) else None,
        "investor_currency": currency if _converted(own, currency, code) else None,
    }


# --- A finished run ----------------------------------------------------------


def describe_run(state: dict, today: date | None = None) -> dict:
    """Everything a reader is told about one run, as plain data.

    ``status`` is the first thing a front end branches on, and the three values
    are deliberately different outcomes rather than degrees of failure:

        failed        a stage caught its own exception and recorded it. The
                      run stopped. There is a reason and it must be shown.
        no_decision   unreachable in principle - every path sets a decision or
                      an error - and reported rather than rendered as a blank
                      page if it ever happens.
        ok            there is a brief. It may recommend nothing, which is an
                      answer and not a failure, and `recommended_nothing`
                      says so explicitly rather than leaving it to be inferred
                      from an empty list.
    """
    user = state.get("user_input")
    common = {
        "profile": (
            {**user.model_dump(mode="json"), **profile_parts(user)}
            if user is not None
            else None
        ),
        "disclaimer": DISCLAIMER,
    }

    if state.get("error"):
        return {
            **common,
            "status": "failed",
            "error": state["error"],
            "error_hint": RATE_LIMIT_HINT,
            "decision": None,
        }

    decision = state.get("decision")
    if decision is None:
        return {
            **common,
            "status": "no_decision",
            "error": None,
            "state_reached": sorted(state),
            "decision": None,
        }

    return {
        **common,
        "status": "ok",
        "error": None,
        "decision": describe_decision(decision, state, user, today),
    }


def describe_decision(decision, state: dict, user, today: date | None = None) -> dict:
    count = len(decision.recommendations)
    return {
        # A property, so it does not survive model_dump and has to be stated.
        "recommended_nothing": decision.recommended_nothing,
        "nothing_headline": "Nothing is being recommended",
        "nothing_explanation": NOTHING_RECOMMENDED,
        "no_recommendation_reason": (
            plain(decision.no_recommendation_reason or "no reason recorded")
            if decision.recommended_nothing
            else None
        ),
        "headline": f"{count} {'company' if count == 1 else 'companies'} worth a look",
        "recommendations": [
            _describe_recommendation(index, rec, state, user)
            for index, rec in enumerate(decision.recommendations, start=1)
        ],
        "excluded": [_describe_exclusion(item) for item in decision.excluded],
        "next_review": next_review(today).isoformat(),
        "next_review_on": f"{next_review(today):%d %b %Y}",
        "conditions_discarded": decision.conditions_discarded,
        # Observability, kept small and last. A count that climbs means the
        # model is writing conditions grounded in nothing, and the briefs above
        # would still read perfectly well.
        "footnotes": _footnotes(decision),
    }


def _describe_recommendation(index: int, rec, state: dict, user) -> dict:
    """One company, as a reader is told about it.

    The screen score is deliberately absent. It is a ranking number, and
    `agents/screening.py` records why its absolute value cannot be read as a
    grade: it saturates at the top and caps financial companies at 0.50. A
    reader shown "0.64" will take it for 64% of something. The position in the
    list is the part of that number that means anything, and the list already
    shows it.
    """
    return {
        "index": index,
        "ticker": rec.ticker,
        "name": rec.name,
        "themes": list(rec.themes),
        "verdict": rec.verdict,
        "verdict_text": VERDICT_WORDS.get(rec.verdict),
        "thesis": plain(rec.thesis),
        "exit_conditions": [
            {
                "condition": plain(condition.condition),
                "grounds": grounds_for(condition, state),
            }
            for condition in rec.exit_conditions
        ],
        "known_risks": [plain(risk) for risk in rec.known_risks],
        "price": _price(rec, user),
        "affordable": affordable_sentence(rec, user) if user else None,
    }


def _describe_exclusion(item) -> dict:
    """Every candidate considered and not chosen, with why.

    A company that simply vanished between the ranking and the output would be
    the one failure a reader could never detect.
    """
    return {
        "ticker": item.ticker,
        "name": item.name,
        "reason": item.reason,
        "reason_text": EXCLUSION_WORDS.get(item.reason, item.reason),
        "detail": (
            plain(item.detail)
            if item.detail and item.reason in DETAIL_WORTH_SHOWING
            else None
        ),
    }


def _footnotes(decision) -> list[str]:
    notes = []
    if decision.conditions_discarded:
        notes.append(
            f"{decision.conditions_discarded} thing(s) to watch for were left "
            "out, because nothing was given that you could go and check."
        )
    if decision.notes:
        notes.append(decision.notes)
    return notes


def describe_question(payload: dict) -> dict:
    """The clarification Agent 1 stopped to ask, as a reader receives it.

    The reason is the agent's own words and travels unchanged. Everything around
    it - that these are two answers in conflict, which attempt this is, what an
    empty reply would cost - is what makes the question answerable, and it must
    read the same in a terminal and in a browser.

    ``attempt`` and ``max_attempts`` are shown rather than hidden because the
    loop is bounded and gives up with a stated outcome. Somebody on their third
    of three is entitled to know that.
    """
    return {
        "intro": CLARIFICATION_INTRO,
        "reason": payload["reason"],
        "prompt": payload.get("question", "Please clarify your preference."),
        "attempt": payload["attempt"],
        "max_attempts": payload["max_attempts"],
        "blank_answer_hint": BLANK_CLARIFICATION,
    }


# --- A run in progress -------------------------------------------------------


STAGE_LABELS: dict[str, tuple[int, str]] = {
    "profile_agent": (1, "Checking your profile makes sense"),
    "clarification": (1, "Waiting for your clarification"),
    "clarification_exhausted": (1, "Giving up on the profile"),
    "research": (2, "Researching current themes in your sectors"),
    "companies": (3, "Finding companies genuinely exposed to those themes"),
    "risk_critic": (4, "Stress-testing each candidate against bad news"),
    "decide": (5, "Writing the brief"),
}
"""What each graph node is called on screen, and which of the five stages it is.

Needed in three places that must agree: the CLI's progress display, the CLI's
resume path working out where a saved run stopped, and the HTTP layer's stage
events. Three copies would drift the moment a node is added.
"""

STAGES = 5


def stage_detail(node: str, update: dict) -> dict:
    """What one completed node produced, as counts.

    These are the same numbers the evals score - `articles_retrieved`,
    `companies_examined`, `drop_summary` - because a run that examines eleven
    companies and produces zero candidates looks identical to a broken one until
    the drop reasons are visible. Anything this cannot describe returns an empty
    dict rather than a guess.

    Computed properties are read HERE, where the objects still exist. Every one
    of `found_nothing`, `drop_summary`, `was_critiqued` and `verdict` is a
    property, so a front end handed the raw update would not have them.
    """
    if node == "profile_agent":
        profile = update.get("investor_profile")
        if profile is None:
            return {}
        return {
            "needs_clarification": profile.needs_clarification,
            "status": profile.status,
        }

    if node == "clarification":
        return {"answer_recorded": True}

    if node == "research":
        found = update.get("research_findings")
        if found is None:
            return {}
        return {
            "themes": [
                {"name": t.name, "confidence": t.confidence} for t in found.themes
            ],
            "articles_cited": len(found.articles),
            "articles_retrieved": found.articles_retrieved,
            "found_nothing": found.found_nothing,
        }

    if node == "companies":
        found = update.get("company_findings")
        if found is None:
            return {}
        return {
            "candidates": [c.ticker for c in found.candidates],
            "companies_examined": found.companies_examined,
            "drop_summary": dict(found.drop_summary or {}),
            "found_nothing": found.found_nothing,
        }

    if node == "risk_critic":
        found = update.get("risk_findings")
        if found is None:
            return {}
        return {
            "critiques": [
                {
                    "ticker": c.ticker,
                    "was_critiqued": c.was_critiqued,
                    "verdict": c.verdict if c.was_critiqued else None,
                    "skipped_reason": None if c.was_critiqued else c.skipped_reason,
                    "risks": len(c.risks),
                    "articles_reviewed": c.articles_reviewed,
                    # A filter that removes evidence without saying so is its
                    # own kind of unreliable narrator. Both counts travel.
                    "press_releases_withheld": c.press_releases_withheld,
                    # The NAMES are deduplicated and the COUNT is not, on
                    # purpose: four articles withheld from one publisher is the
                    # shape of a filter that is too aggressive, and four from
                    # four is the shape of a thin week. Collapsing the count
                    # into the name list would erase that difference.
                    "sources_withheld": sorted(set(c.sources_withheld or [])),
                    "sources_withheld_count": len(c.sources_withheld or []),
                }
                for c in found.critiques
            ]
        }

    if node == "decide":
        decision = update.get("decision")
        if decision is None:
            return {}
        return {
            "recommendations": [r.ticker for r in decision.recommendations],
            "recommended_nothing": decision.recommended_nothing,
            "conditions_discarded": decision.conditions_discarded,
        }

    return {}


# --- The questions a person is asked ------------------------------------------


SECTORS: tuple[tuple[str, str], ...] = (
    ("Technology", "semiconductors, cloud software"),
    ("Healthcare", "biotechnology, medical devices"),
    ("Financial Services", "regional banks, payments"),
    ("Energy", "oil services, refining"),
    ("Utilities", "solar, grid storage"),
    ("Industrials", "aerospace, electrical equipment"),
    ("Consumer Cyclical", "carmakers, online retail"),
    ("Consumer Defensive", "food producers, household goods"),
    ("Communication Services", "streaming, telecoms"),
    ("Basic Materials", "lithium mining, chemicals"),
    ("Real Estate", "data-centre REITs, logistics"),
)
"""The eleven sectors the market is conventionally divided into.

In the wording the company data provider itself reports - "Consumer Cyclical"
and "Financial Services" are Yahoo's names, not GICS's. Taking the provider's
vocabulary means a sector picked here is the same string Agent 3 later reads off
a resolved company, rather than something that has to be translated.

EACH ONE CARRIES A NARROWER EXAMPLE, and that is the point of the list rather
than decoration. This answer is the highest-signal input in the whole run -
Agent 2 turns it straight into search queries - and narrower researches better:
"semiconductors" produced this project's best brief, "renewable energy" produced
an empty one. A bare menu of eleven broad sectors would push every beginner to
the broad end, which is the opposite of what helps them. The examples teach the
narrowing at the moment the choice is made.
"""

SECTOR_GUIDANCE = "Narrower researches better - 'grid storage' beats 'utilities'."


def _bound(field, kind: str):
    """Read a numeric bound off the model rather than restating it.

    ``gt=0, le=120`` lives in UserInput. Typing it into a form as well would
    give the bound two homes and one of them no test - the argument entry 29
    settled for the CLI, applied to the front end that has a min= attribute
    sitting there inviting exactly that mistake.
    """
    for constraint in field.metadata:
        value = getattr(constraint, kind, None)
        if value is not None:
            return value
    return None


def form_fields() -> list[dict]:
    """Every question, once, for whatever is asking it.

    The wording is here rather than in a terminal or a template because entry 96
    is about exactly this: the CLI asked "when do you need the money back" while
    the agent's prompt read the same field as when the person planned to BUY,
    and a guard written against the intended meaning stopped guarding anything
    once the wording drifted. Two front ends asking the same field two ways is
    that failure with a second copy.

    Options come from the model's own Literal types, and bounds from its own
    constraints, so adding a risk level or a currency cannot leave a form
    offering the old three.
    """
    fields = UserInput.model_fields

    return [
        {
            "name": "age",
            "label": "Your age",
            "kind": "number",
            "min": _bound(fields["age"], "gt"),
            "max": _bound(fields["age"], "le"),
        },
        {
            "name": "investment_experience",
            "label": "Investment experience",
            "kind": "choice",
            "options": list(get_args(fields["investment_experience"].annotation)),
        },
        {
            "name": "risk_tolerance",
            "label": "Risk tolerance",
            "kind": "choice",
            "options": list(get_args(fields["risk_tolerance"].annotation)),
        },
        {
            "name": "investment_amount",
            "label": "Amount you want to invest",
            "kind": "number",
            "min": _bound(fields["investment_amount"], "gt"),
            "max": None,
        },
        {
            "name": "investment_currency",
            "label": "Currency of that amount",
            "kind": "choice",
            # The annotation is `Literal[...] | None`, so the codes sit one
            # level in. USD leads because most companies this finds trade in it,
            # and the share count only appears when the currencies match.
            "options": list(get_args(get_args(fields["investment_currency"].annotation)[0])),
            "help": "Most companies this finds trade in USD.",
        },
        {
            # ONE time question, not two. This used to ask "when do you need the
            # money back" and then "how long do you expect to hold", which for a
            # retail investor are the same question - and the first contradicted
            # what the profile agent believed the field held.
            "name": "holding_period",
            "label": "How long do you plan to keep this money invested",
            "kind": "text",
            "help": "Free text: '18 months', '3-5 years', 'until my daughter starts university'.",
        },
        {
            "name": "sectors_of_interest",
            "label": "Which parts of the market interest you?",
            "kind": "sectors",
            "options": [{"name": name, "example": example} for name, example in SECTORS],
            "help": SECTOR_GUIDANCE,
        },
        {
            "name": "restrictions",
            "label": "Anything you will not invest in?",
            "kind": "list",
            "help": "For example: no fossil fuels, no tobacco. Leave blank if none.",
        },
    ]
