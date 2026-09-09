"""The page's navigation model, asserted where it can be.

WHY THIS EXISTS

The page was one screen whose sections were toggled by `hidden`, with no
navigation model at all. Opening a recorded run set `intro.hidden = true` and
nothing ever set it back, so the live-run form vanished and only a page reload
brought it back. A visitor found it on the deployed site.

The fix was structural rather than a patch: three tabs addressed by the location
hash, and - the part that actually closes the defect - a SEPARATE result area
for the gallery, so rendering a recording cannot touch anything the run tab
owns.

WHAT THIS CAN AND CANNOT CHECK

These are assertions about the served markup, not about behaviour: no browser
runs here. They catch the structural regression - a shared result container, a
missing tab, a run section escaping the run tab - which is exactly what went
wrong. They cannot prove a click works. That was checked separately by driving
the tab functions against a DOM stub.
"""

import re

import pytest

from backend.config import PROJECT_ROOT

PAGE = PROJECT_ROOT / "frontend" / "static" / "index.html"
HTML = PAGE.read_text(encoding="utf-8")

TABS = ("run", "gallery", "about")


@pytest.mark.parametrize("name", TABS)
def test_every_tab_has_a_link_and_a_panel(name):
    """A link with no panel is a dead end; a panel with no link is unreachable."""
    assert f'href="#{name}"' in HTML, f"no nav link for the {name} tab"
    assert f'id="tab-{name}"' in HTML, f"no panel for the {name} tab"


def test_the_gallery_renders_into_its_own_result_area():
    """The whole point of the rebuild.

    One shared `#result` is what let a recorded run blank the live-run form.
    If these two ever collapse back into one container, opening a recording can
    clobber a run in progress again.
    """
    assert 'id="result"' in HTML
    assert 'id="gallery-result"' in HTML
    assert 'showBrief(body.brief, "gallery-result")' in HTML, (
        "showRecording must render into the gallery's own area, not the run's"
    )


def test_showing_a_recording_does_not_touch_the_run_tab():
    """A recording may not hide anything the run tab owns.

    The original defect in one line: `$("intro").hidden = true` inside
    showRecording, never undone. Nothing in that function may hide `intro`,
    `progress` or `result` again.
    """
    body = HTML[HTML.index("async function showRecording("):]
    body = body[: body.index("\n}")]

    for owned in ("intro", "progress", "result"):
        assert f'$("{owned}").hidden' not in body, (
            f"showRecording touches the run tab's {owned!r}, which is the defect "
            "this rebuild removed"
        )


def test_the_run_sections_live_inside_the_run_tab():
    """Progress and the form must be inside the tab that hides and shows them.

    Left outside, they would stay on screen under the gallery and the about
    page - visible with no way to reach the thing they belong to.
    """
    start = HTML.index('<div class="tab" id="tab-run">')
    end = HTML.index('<div class="tab" id="tab-gallery"')
    run_tab = HTML[start:end]

    for section in ('id="intro"', 'id="progress"', 'id="clarify"', 'id="result"'):
        assert section in run_tab, f"{section} is not inside the run tab"


def test_the_disclaimer_sits_outside_the_tabs():
    """It must not become something a reader can navigate away from.

    An About tab is exactly the kind of change that quietly relocates a
    disclaimer into a page nobody opens.
    """
    before_tabs = HTML[: HTML.index('<nav class="tabs">')]
    assert 'id="disclaimer"' in before_tabs


def test_the_in_run_guidance_does_not_warn_people_off_the_tabs():
    """The stream is a fetch ReadableStream loop living in JavaScript, so
    switching tabs does not interrupt it. Telling visitors otherwise would be
    both untrue and a reason not to look at the gallery - which is what they
    should be looking at once the day's runs are gone."""
    assert "Switching tabs is fine" in HTML
    assert re.search(r"two to four minutes", HTML)
