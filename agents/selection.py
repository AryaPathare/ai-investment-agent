"""Choosing which candidates are recommended. Pure Python, no model involved.

WHY THERE IS NO LLM IN THIS FILE

The same argument as the ranking code, and it matters more here because this is
the last stage. A model asked "which of these five should we recommend" produces
an ordering it cannot justify and will not reproduce, and by this point the
ordering IS the product. Every input it would reason over - a score, a verdict,
a restriction - is already a fact computed by an earlier stage, so there is
nothing left to judge.

The model's job comes after: writing the case for companies Python has already
chosen. That is prose, and prose is what models are for.

HOW THE TWO EARLIER NUMBERS COMBINE

They do not combine. Agent 4's verdict TIERS, and Agent 3's score ORDERS within
a tier:

    survives    ranked by screen_score
    weakened    ranked by screen_score
    (disqualified never reaches the ranking at all)

Multiplying a verdict by a weight would have meant inventing a constant, and a
company's position would then depend on a number nobody could defend. Tiering
states the preference plainly instead: prefer what withstood criticism, and
among equals prefer the stronger business.

WHAT "SURVIVES" IS NOT ALLOWED TO MEAN

A candidate that Agent 4 never examined also reports ``survives`` - the verdict
is arithmetic over a risk list, and an empty list is an empty list whether it
was earned or never attempted. Selecting on the verdict alone would therefore
promote exactly the candidates that fell outside the critique cap, which is the
opposite of what the cap is for.

So an uncritiqued candidate is not selectable, and is recorded as such rather
than dropped. ``was_critiqued`` is the field that distinguishes them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from models.companies import CompanyCandidate, CompanyFindings
from models.decision import MAX_RECOMMENDATIONS, ExcludedCompany
from models.profile import InvestorProfile
from models.risk import CandidateCritique, RiskFindings

# Better tiers first, so sorting is a plain ascending sort.
_VERDICT_RANK = {"survives": 0, "weakened": 1, "disqualified": 2}

# Words that carry no exclusionary meaning inside a restriction. An investor
# writes "No fossil fuel companies", and matching on "companies" would exclude
# every company ever considered.
_RESTRICTION_NOISE = {
    "no", "not", "none", "avoid", "exclude", "excluding", "without",
    "company", "companies", "business", "businesses", "stock", "stocks",
    "share", "shares", "firm", "firms", "sector", "sectors", "industry",
    "industries", "any", "all", "the", "and", "for", "with", "that",
    "related", "involved", "anything",
}


@dataclass(frozen=True)
class Selection:
    """What selection decided, including everything it decided against."""

    selected: list[tuple[CompanyCandidate, CandidateCritique]]
    excluded: list[ExcludedCompany]
    no_recommendation_reason: str | None


def restriction_terms(restrictions: list[str]) -> list[str]:
    """The words in a restriction that actually restrict something.

    "No fossil fuel companies" yields {fossil, fuel}. Naive on purpose and
    consistent with how Agent 2 checks its themes: a substring match will
    occasionally flag a company whose description says it has NO exposure to the
    thing. That direction of error is the safe one here - a wrongly excluded
    company is recorded with its reason and can be argued with, whereas a
    wrongly included one reaches a person as a recommendation.
    """
    terms: list[str] = []
    for restriction in restrictions:
        for word in re.findall(r"[A-Za-z]+", restriction.lower()):
            if len(word) > 2 and word not in _RESTRICTION_NOISE:
                terms.append(word)
    return terms


def _violates_restrictions(
    candidate: CompanyCandidate, terms: list[str]
) -> str | None:
    """The first restriction term this candidate matches, if any."""
    haystack = " ".join(
        [candidate.name, candidate.exposure_rationale, *candidate.themes]
    ).lower()
    return next((term for term in terms if term in haystack), None)


def _no_recommendation_reason(excluded: list[ExcludedCompany]) -> str:
    """Say which kind of empty this is, in the reader's terms.

    An empty result renders "every one carried a critical risk", "none of them
    were ever examined" and "there was nothing to consider" identically, and
    those call for completely different responses from the reader.
    """
    if not excluded:
        return (
            "No companies reached this stage: the research found no investable "
            "company genuinely exposed to any theme."
        )

    counts: dict[str, int] = {}
    for item in excluded:
        counts[item.reason] = counts.get(item.reason, 0) + 1

    parts = []
    if counts.get("disqualified_by_risk"):
        parts.append(
            f"{counts['disqualified_by_risk']} carried a critical risk that "
            "broke the case for holding them"
        )
    if counts.get("not_critiqued"):
        parts.append(
            f"{counts['not_critiqued']} were never examined by the risk critic, "
            "so nothing is known about what could go wrong with them"
        )
    if counts.get("restriction_violation"):
        parts.append(
            f"{counts['restriction_violation']} breached a limit the investor "
            "set"
        )

    return (
        "Nothing is being recommended. Of the companies considered, "
        + "; ".join(parts)
        + "."
    )


def select(
    companies: CompanyFindings,
    risks: RiskFindings,
    profile: InvestorProfile,
) -> Selection:
    """Decide which candidates are recommended, and record every one that is not.

    Order of the gates matters and is deliberate. A restriction the investor
    stated is checked FIRST, before any question of quality: a company they
    ruled out is not a close call to be weighed against a good score, and
    reporting it as "outside the top three" would imply it was in the running.
    """
    if companies.found_nothing:
        return Selection([], [], _no_recommendation_reason([]))

    terms = restriction_terms(profile.restrictions)

    eligible: list[tuple[CompanyCandidate, CandidateCritique]] = []
    excluded: list[ExcludedCompany] = []

    for candidate in companies.candidates:
        critique = risks.critique_for(candidate.ticker)

        breach = _violates_restrictions(candidate, terms)
        if breach:
            excluded.append(ExcludedCompany(
                ticker=candidate.ticker, name=candidate.name,
                reason="restriction_violation",
                detail=f"matched the excluded term {breach!r}",
            ))
            continue

        # No critique at all means the critic never ran for this company - a
        # different situation from being examined and cleared, and treated the
        # same way, because neither tells us anything about its risks.
        if critique is None or not critique.was_critiqued:
            excluded.append(ExcludedCompany(
                ticker=candidate.ticker, name=candidate.name,
                reason="not_critiqued",
                detail=(critique.skipped_reason if critique
                        else "the risk critic produced no critique for it"),
            ))
            continue

        if critique.verdict == "disqualified":
            critical = next(
                (r.claim for r in critique.risks if r.severity == "critical"),
                "a critical risk",
            )
            excluded.append(ExcludedCompany(
                ticker=candidate.ticker, name=candidate.name,
                reason="disqualified_by_risk", detail=critical,
            ))
            continue

        eligible.append((candidate, critique))

    eligible.sort(
        key=lambda pair: (_VERDICT_RANK[pair[1].verdict], -pair[0].screen_score)
    )

    selected = eligible[:MAX_RECOMMENDATIONS]

    for position, (candidate, critique) in enumerate(
        eligible[MAX_RECOMMENDATIONS:], start=MAX_RECOMMENDATIONS + 1
    ):
        excluded.append(ExcludedCompany(
            ticker=candidate.ticker, name=candidate.name,
            reason="outside_top_three",
            detail=(
                f"ranked {position} of {len(eligible)} eligible "
                f"({critique.verdict}, score {candidate.screen_score:.3f})"
            ),
        ))

    return Selection(
        selected=selected,
        excluded=excluded,
        no_recommendation_reason=(
            None if selected else _no_recommendation_reason(excluded)
        ),
    )
