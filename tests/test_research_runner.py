"""Tests for Agent 2's eval runner - the instrument, not the agent.

An eval runner is a measuring device, and a measuring device nobody has tested
reports whatever it happens to report. This project has already been bitten
twice by that: an eval whose restriction check reused the implementation's own
naive matcher could only ever agree with it, and a mutation test that could not
fail was mistaken for evidence for two sessions.

What is under test here is the query-shape signal added after entry 68, where
five queries that each named a company returned one article between them and
the runner had no way to say so.
"""

from evals.research_cases import ResearchCase
from evals.research_runner import _proper_nouns, score, summarise
from models.profile import InvestorProfile
from models.research import ResearchFindings


def profile() -> InvestorProfile:
    return InvestorProfile(
        age=30, investment_experience="intermediate", risk_tolerance="moderate",
        investment_amount=5000.0,
        holding_period="3-5 years", sectors_of_interest=["renewable energy"],
        restrictions=[], status="valid",
    )


def case() -> ResearchCase:
    return ResearchCase(name="c", probes="p", profile=profile())


def run(*queries) -> dict:
    findings = ResearchFindings(queries_used=list(queries), articles_retrieved=0)
    return score(case(), findings, None)


# --- the heuristic ------------------------------------------------------------


def test_a_capitalised_word_is_read_as_a_company_name():
    """The five queries from entry 68, which returned one article between them."""
    assert _proper_nouns("SunPower solar panel manufacturing expansion") == ["SunPower"]
    assert _proper_nouns("NextEra Energy renewable portfolio expansion") == [
        "NextEra", "Energy",
    ]


def test_an_ordinary_query_names_nobody():
    assert _proper_nouns("grid scale battery storage contracts") == []
    assert _proper_nouns("solar panel manufacturing expansion") == []


def test_an_acronym_is_not_a_company_name():
    """"GLP-1 drug manufacturing capacity" is one of the prompt's own good
    examples. Flagging it would train whoever reads this report to ignore it."""
    assert _proper_nouns("GLP-1 drug manufacturing capacity") == []
    assert _proper_nouns("US semiconductor export controls") == []


# --- the signals --------------------------------------------------------------


def test_the_runner_reports_queries_that_name_a_company():
    row = run("SunPower solar panel manufacturing expansion",
              "grid scale battery storage contracts")

    assert list(row["queries_naming_companies"]) == [
        "SunPower solar panel manufacturing expansion"
    ]


def test_the_runner_counts_queries_longer_than_five_words():
    """Six words against an AND-only provider is where results stop coming."""
    row = run("NextEra Energy renewable portfolio expansion contracts",  # 6
              "grid scale battery storage contracts")                    # 5

    assert row["long_queries"] == [
        "NextEra Energy renewable portfolio expansion contracts"
    ]
    assert row["avg_query_words"] == 5.5


def test_a_clean_run_reports_nothing_to_look_at():
    row = run("solar panel manufacturing expansion",
              "grid scale battery storage contracts")

    assert row["long_queries"] == []
    assert row["queries_naming_companies"] == {}


def test_the_summary_totals_query_shape_across_cases():
    rows = [
        run("SunPower solar panel manufacturing expansion"),
        run("grid scale battery storage contracts"),
    ]

    summary = summarise(rows)

    assert summary["queries_total"] == 2
    assert summary["queries_naming_companies"] == 1
    assert summary["long_queries"] == 0


def test_no_queries_does_not_divide_by_zero():
    """``found_nothing`` runs reach the scorer too, and a crash in the reporter
    would lose the whole run's measurements over an empty list."""
    row = run()

    assert row["avg_query_words"] == 0.0
    assert summarise([row])["avg_query_words"] == 0.0
