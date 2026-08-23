"""Tests for the press-release filter.

A press release is the company describing itself. Handing one to the agent
whose whole job is the bear case is worse than handing it nothing: it is the
most confirmatory input available, dressed as news, and the model cannot tell
the difference from the text alone.

**The error to be afraid of here is the false positive, not the false
negative.** Letting a press release through costs a mediocre input. Removing
"Regulator announces probe" blinds the critic to exactly what it exists to
find. Most of this file is therefore about what must NOT be filtered, and the
real headlines below were taken from the cached corpus rather than invented -
they are the ones a looser draft of this rule actually caught.
"""

import pytest

from clients.news import drop_press_releases, is_press_release
from tests.conftest import make_article


def _article(title, description="", snippet=""):
    return make_article("u1", title, description=description, snippet=snippet)


# --- What must be filtered ---------------------------------------------------


@pytest.mark.parametrize("title", [
    "Chemomab Therapeutics Announces Second Quarter 2026 Financial Results",
    "CervoMed Reports Second Quarter 2026 Financial Results and Provides Corporate Update",
    "Flow Capital Announces Q2 2026 Financial Results",
    "T1 Energy Reports Second Quarter 2026 Results",
    "USA Rare Earth Reports Second Quarter 2026 Financial Results",
    "Acme Corp Declares Quarterly Dividend",
    "Acme Corp Announces Pricing of Public Offering of Common Stock",
    "Acme Corp to Present at the Jefferies Healthcare Conference",
])
def test_issuer_documents_are_filtered(title):
    """Every one of these is a document only a company publishes about itself.
    The first five are real headlines from the cached corpus."""
    assert is_press_release(_article(title)) is True


@pytest.mark.parametrize("marker", [
    "GLOBE NEWSWIRE", "PRNewswire", "PR Newswire",
    "BUSINESS WIRE", "ACCESSWIRE", "EINPresswire",
])
def test_a_wire_dateline_marks_a_press_release(marker):
    """The strongest signal and close to definitional: an article carrying a
    paid-wire dateline was published BY the company."""
    article = _article(
        "Purple Appoints Jimmy Serrano as Growth Director",
        description=f"NEW YORK, Aug. 18, 2026 ({marker}) -- Purple today announced...",
    )
    assert is_press_release(article) is True


def test_the_wire_marker_catches_what_a_title_rule_cannot():
    """Real examples from the corpus. No title pattern would reach these, and
    all three are issuer announcements."""
    for title in (
        "Pontiac Bancorp, Inc. has agreed to acquire Ottawa Bancorp",
        "nCino Releases Mortgage MCP, Letting Lenders Connect AI Agents",
        "Ventripoint Expands Subscription Access for FDA-Cleared AI Cardiac Tool",
    ):
        plain = _article(title)
        wired = _article(title, snippet="(GLOBE NEWSWIRE) -- the company said")
        assert is_press_release(plain) is False, "no signal without the dateline"
        assert is_press_release(wired) is True


# --- What must NOT be filtered -----------------------------------------------


@pytest.mark.parametrize("title", [
    # All real, all from the cached corpus, all contain "announces".
    "Apple announces changes for apps in the European Union",
    "Canadian Solar Announces Resolution of Maxeon U.S. Patent Litigation",
    "SK Hynix Announces $38.5 Billion DRAM and NAND Manufacturing Expansion",
    "PowerBank Announces 4 MW Solar Project in North Bruce Peninsula, Ontario",
    # Invented, but these are the shape of what the critic exists to find.
    "Regulator announces probe into Acme Corp accounting",
    "FTC announces investigation into Acme Corp",
    "Acme Corp sued by shareholders over disclosure failures",
    "Short seller alleges Acme Corp overstated revenue",
])
def test_real_news_containing_announcement_words_is_kept(title):
    """THE test for this file.

    A rule keyed on "announces" would take all of these. The first four are
    real headlines a looser draft actually caught; the last four are the
    bear-case material the agent exists to retrieve. Removing them would be far
    worse than letting a press release through.
    """
    assert is_press_release(_article(title)) is False


def test_an_earnings_call_transcript_is_kept():
    """Deliberately not filtered. A transcript is the company's own event, but
    it carries the analyst Q&A - which is the one part of an earnings cycle
    where hard questions get asked out loud."""
    assert is_press_release(
        _article("Albemarle (ALB) Q2 2026 Earnings Call Transcript")
    ) is False


def test_journalism_about_results_is_kept():
    """Reporting ON results is not the results release."""
    for title in (
        "Acme profit falls 40% as solar prices collapse",
        "Why Acme's second quarter worried analysts",
        "Acme shares slide after weak guidance",
    ):
        assert is_press_release(_article(title)) is False, title


# --- The split ---------------------------------------------------------------


def test_dropping_returns_the_kept_articles_and_a_count():
    articles = [
        make_article("u1", "Regulator announces probe into Acme"),
        make_article("u2", "Acme Corp Announces Q2 2026 Financial Results"),
        make_article("u3", "Acme sued by shareholders"),
    ]
    kept, withheld = drop_press_releases(articles)

    assert [a.uuid for a in kept] == ["u1", "u3"]
    assert withheld == 1


def test_nothing_to_drop_returns_everything():
    articles = [make_article("u1", "Regulator opens probe")]
    assert drop_press_releases(articles) == (articles, 0)


def test_an_empty_input_is_not_an_error():
    assert drop_press_releases([]) == ([], 0)


# --- Reaching the reader -----------------------------------------------------


def test_the_critique_records_how_many_were_withheld(monkeypatch):
    from agents import risk_agent
    from models.risk import NewsRiskAssessment
    from tests.test_source_filter import _candidate

    articles = [
        make_article("u1", "Regulator opens probe into Waaree", source="reuters.com"),
        make_article("u2", "Waaree Announces Q2 2026 Financial Results", source="ft.com"),
    ]
    monkeypatch.setattr(risk_agent, "search_many", lambda q, **k: (articles, list(q)))
    monkeypatch.setattr(
        risk_agent, "assess_news_risks",
        lambda c, a: (NewsRiskAssessment(risks=[]), {}),
    )

    critique, _, _ = risk_agent.critique_candidate(_candidate())

    assert critique.press_releases_withheld == 1
    assert critique.articles_reviewed == 1, "only the real reporting was reviewed"


def test_the_cli_prints_the_count(capsys):
    import cli
    from models.risk import CandidateCritique, RiskFindings

    cli._report(cli.Progress(), "risk_critic", {
        "risk_findings": RiskFindings(critiques=[
            CandidateCritique(
                ticker="WAAREE", name="Waaree", risks=[],
                articles_reviewed=8, press_releases_withheld=4,
            )
        ])
    })
    out = capsys.readouterr().out
    assert "withheld 4 company press release(s)" in out


def test_research_does_not_use_this_filter():
    """Applied by the risk critic and NOT by Agent 2, on purpose. A company
    announcing a 1.2GW order genuinely IS evidence a theme is real - the same
    article that is worthless to the critic is ordinary input to research."""
    from config import PROJECT_ROOT

    source = (PROJECT_ROOT / "agents" / "research_agent.py").read_text(encoding="utf-8")
    assert "drop_press_releases" not in source


# --- Journalism that reports ON an issuer document ---------------------------
#
# Found by review after the first version shipped. The rule caught these, and
# every one is reporting a risk critic needs. The corpus contained none of them
# and the tests above used invented headlines that happened to avoid the
# construction, so neither caught it: the rule was verified against the cases it
# was designed for.


@pytest.mark.parametrize("title", [
    "First Solar Reports Disappointing Second-Quarter Financial Results, Shares Plunge",
    "Third-quarter results reveal accounting irregularities at Acme",
    "Acme Q3 FY2025 results miss badly, shares tumble",
    "Board declares special dividend amid activist pressure",
    "Acme Reports Second Quarter Financial Results as revenue falls",
    "Why Acme's Q2 2026 results worried analysts",
    "Acme announces Q2 financial results; short seller alleges fraud",
    "Acme Reports Full-Year Results, warns on guidance",
])
def test_reporting_on_results_is_never_treated_as_a_press_release(title):
    """The veto. An issuer does not call its own results disappointing, does not
    mention its shares plunging, and does not report that they revealed
    accounting irregularities."""
    assert is_press_release(_article(title)) is False


def test_the_veto_beats_every_other_signal():
    """Even a genuine wire dateline loses to journalism language in the title.

    Deliberate. If the two signals disagree the article is ambiguous, and the
    asymmetry says keep it: a press release through costs a slot, a removed
    probe costs the agent its purpose.
    """
    article = _article(
        "Acme Reports Q2 Results, accounting irregularities revealed",
        description="NEW YORK, Aug. 18, 2026 (GLOBE NEWSWIRE) -- Acme today...",
    )
    assert is_press_release(article) is False


# --- The wire marker must be a dateline, not a mention -----------------------


def test_a_wire_named_mid_sentence_is_not_a_dateline():
    """Found by review. A journalist attributing a claim to a wire release is
    reporting ABOUT the company, which is the opposite of a press release."""
    article = _article(
        "Judge rules against Acme in patent suit",
        description="Acme said in a PR Newswire release last month that the claim was baseless.",
    )
    assert is_press_release(article) is False


@pytest.mark.parametrize("dateline", [
    "DUBLIN, Ireland, Aug. 12, 2026 (GLOBE NEWSWIRE) -- Fusion Fuel today",
    "WARNERTOWN, Australia, Aug. 17, 2026 /PRNewswire/ -- As Southern",
    "/PRNewswire-PRWeb/ -- Caregility today announced",
    "TORONTO, Aug.  20, 2026  (GLOBE NEWSWIRE) -- Flow Capital",
])
def test_real_datelines_from_the_corpus_still_match(dateline):
    """Every one taken verbatim from .cache/news. The shape - wire wrapped in
    parentheses or slashes, followed by a double dash - is what makes it a
    dateline rather than a mention."""
    assert is_press_release(_article("Some Company Update", description=dateline)) is True


def test_the_veto_lets_some_positive_issuer_releases_through(capsys):
    """An accepted cost, recorded so it is not mistaken for a defect.

    The veto is broad, so an issuer release written in upbeat language - "Beats
    Guidance", "Revenue Jumps 40%" - is kept. That is the trade the module
    docstring commits to: ambiguity resolves toward keeping the article.

    It costs nothing on the real corpus - all 15 press releases in .cache/news
    are still caught - and the leaks are POSITIVE news, which a bear-case agent
    has little use for either way. Narrowing the veto to reclaim them would
    risk re-introducing the false positives that made it necessary.
    """
    leaks = [
        "Acme Corp Announces Q2 2026 Financial Results Amid Strong Demand",
        "Acme Announces Q2 2026 Financial Results; Revenue Jumps 40%",
        "Acme Announces Q2 Financial Results, Beats Guidance",
    ]
    assert all(not is_press_release(_article(t)) for t in leaks), (
        "if these start being caught the veto has been narrowed - check that "
        "the journalism cases above still pass before accepting it"
    )
