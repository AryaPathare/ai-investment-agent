"""Building the searches that go looking for bad news about a candidate.

WHY THIS IS A PURE FUNCTION AND NOT A MODEL CALL

Asking the model to invent search terms would be a second place for it to
wander, and there is nothing here it is needed for. Turning "TSMC" plus the
theme it was picked for into "TSMC delay" is string handling, not judgement.
Keeping it deterministic means the same candidate always gets searched the same
way, so when the critic finds nothing twice in a row that means something.

WHAT THESE QUERIES ARE FOR

Agent 2's searches ask what is happening. These ask what is going WRONG, and
that difference is the whole reason Agent 4 retrieves at all. Agent 2's corpus
is a poor source of dissent because a theme is built out of the articles that
support it, so contradicting evidence never enters. Searching adversarially is
the only way to put it in front of the critic.

NAMES, NOT TICKERS

A ticker is a terrible news search term. "PBK", "C" and "TSM" appear in prose
constantly with no relation to the company, and the news provider has no notion
of a symbol. Company names are searched as quoted phrases so "Advanced Micro
Devices" cannot match three unrelated words in the same paragraph.

The legal suffix is stripped first. "Taiwan Semiconductor Manufacturing Company
Limited" as a quoted phrase matches almost nothing, because news copy calls it
TSMC or "Taiwan Semiconductor". Over-specifying a phrase query is the quiet way
to retrieve zero articles and conclude, wrongly, that there is no bad news.
"""

from __future__ import annotations

import re

from config import get_settings
from models.companies import CompanyCandidate

# Corporate suffixes that appear in a registry and almost never in a headline.
# Matched one WORD at a time with punctuation removed, because "N.V." and "NV"
# are the same suffix and a naive string comparison misses one of them.
_LEGAL_SUFFIXES = {
    "incorporated", "corporation", "holdings", "holding", "group",
    "limited", "company", "ltd", "inc", "corp", "plc", "llc",
    "nv", "sa", "ag", "se", "oyj", "asa", "ab", "co", "sas",
    "spa", "kgaa", "gmbh", "pte", "bhd", "psc",
}

# One angle per query, each a SINGLE term ANDed with the company name.
#
# This looks needlessly narrow and is not. Verified against the live provider:
#
#   "Pfizer" lawsuit OR investigation OR probe   ->  0 articles
#   "Pfizer" lawsuit | investigation | probe     ->  3 articles, two of which
#                                                    were about an Israeli army
#                                                    probe and an Air India
#                                                    incident - no Pfizer at all
#   "Pfizer" lawsuit                             ->  3 articles, all Pfizer
#
# The word OR is not query syntax here, so it silently matches nothing. The pipe
# IS syntax, but it ORs across the WHOLE query, which stops the company name
# being required - and an off-topic article is far worse than none, because the
# model is then asked what risk an Air India story poses to Pfizer, which is an
# invitation to invent one. Plain AND keeps the company mandatory.
#
# Deliberately not included: "downgrade", "shares", "stock", "target". Those
# retrieve price commentary, which is what the market already thinks rather than
# a fact about the business.
_ANGLES = [
    "lawsuit",
    "delay",
    "competition",
    "warning",
    "recall",
    "investigation",
]


def strip_legal_suffix(name: str) -> str:
    """Reduce a registered company name to what a journalist would write.

    Pops trailing suffix WORDS rather than matching string endings. Registry
    names stack them - "Acme Group Holdings Limited" needs three passes - and
    punctuation varies freely, so "N.V." is normalised to "nv" before the
    comparison rather than being handled as a separate spelling.

    The last remaining word is never removed. A company actually called
    "Holdings" would otherwise reduce to an empty phrase, and a quoted query of
    "" matches everything.
    """
    words = name.strip().split()

    while len(words) > 1:
        last = words[-1].lower().replace(".", "").replace(",", "")
        if last not in _LEGAL_SUFFIXES:
            break
        words.pop()

    return " ".join(words) or name.strip()


# Words that carry no search value in a theme name. They are the connective
# tissue an LLM writes to make a phrase read well, and ANDing on them is what
# turns a workable query into one that matches nothing.
_THEME_STOPWORDS = {
    "the", "and", "for", "with", "from", "into", "amid", "over",
    "shifts", "shift", "trends", "trend", "growth", "demand", "adoption",
    "expansion", "outlook", "market", "sector", "surge", "boom", "wave",
    "new", "rising", "global", "increased", "continued",
}


def _theme_keyword(theme: str) -> str:
    """The single most distinctive word in a theme name.

    ONE word, not the whole phrase. Verified live: '"Pfizer" Vaccine Demand
    Shifts' is four ANDed terms and returns zero articles, while '"Pfizer"
    vaccine' returns plenty. Theme names are written for a human to read, so
    most of their words are there for the prose rather than for a search.

    Stopwords are dropped first, then the longest remaining word is taken, on
    the assumption that the longest word is the most specific - "lithography"
    beats "EUV", "irrigation" beats "solar".
    """
    words = [w for w in re.findall(r"[A-Za-z0-9]+", theme) if len(w) > 2]
    meaningful = [w for w in words if w.lower() not in _THEME_STOPWORDS]

    candidates = meaningful or words
    return max(candidates, key=len) if candidates else ""


def bear_queries(candidate: CompanyCandidate, *, limit: int | None = None) -> list[str]:
    """Searches designed to surface what is going wrong for this candidate.

    The first queries pair the company name with a generic trouble angle, which
    is what finds company-specific problems. The last pairs the company with the
    THEME it was selected for, which is what finds the case that the theme
    itself is weaker than Agent 2 believed - a thesis_invalidation risk that no
    amount of company-specific searching would surface.

    Returns at most ``limit`` queries, defaulting to the configured budget.
    Deterministic: the same candidate always produces the same list.
    """
    if limit is None:
        limit = get_settings().bear_queries_per_candidate

    name = strip_legal_suffix(candidate.name)
    phrase = f'"{name}"'

    queries = [f"{phrase} {angle}" for angle in _ANGLES]

    # One theme-facing query, so the theme itself can be attacked and not only
    # the company. Placed second so it survives the common limit of two.
    #
    # No trouble word is appended: the company name and the theme together are
    # already narrow, and adding a third ANDed term reliably drove the result
    # count to zero. The model judges whether what comes back undermines the
    # case - that is its job, and it is better at it than a keyword is.
    keywords = [k for k in (_theme_keyword(t) for t in candidate.themes) if k]
    if keywords:
        queries.insert(1, f"{phrase} {keywords[0]}")

    return queries[:limit]
