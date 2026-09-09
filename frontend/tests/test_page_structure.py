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


def _function_body(name: str) -> str:
    """The source of one top-level function in the page's script.

    Several checks are about what a specific function does NOT do, so they need
    its body rather than the whole file - `$("intro").hidden` appears legitimately
    elsewhere.
    """
    start = HTML.index(f"async function {name}(")
    return HTML[start : HTML.index("\n}", start)]


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
    # Matching the target rather than the whole call: the argument expression
    # is free to change, the destination is not.
    body = _function_body("showRecording")
    assert '"gallery-result"' in body, (
        "showRecording must render into the gallery's own area, not the run's"
    )
    assert "showBrief(" in body


def test_showing_a_recording_does_not_touch_the_run_tab():
    """A recording may not hide anything the run tab owns.

    The original defect in one line: `$("intro").hidden = true` inside
    showRecording, never undone. Nothing in that function may hide `intro`,
    `progress` or `result` again.
    """
    body = _function_body("showRecording")

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


def test_a_recording_is_opened_by_the_hash_not_by_a_click_handler():
    """One place decides what is on screen, and the address bar agrees with it.

    Clicking a card used to call showRecording directly, so the URL never
    changed: a specific brief could not be linked to and Back did not close
    one. That is the same way-in-with-no-way-back-out shape the tabs were built
    to remove, one level down. The card sets the hash now and `route` opens it.
    """
    assert 'location.hash = "#gallery/"' in HTML, (
        "clicking a card must set the hash rather than opening the brief itself"
    )
    assert 'window.addEventListener("hashchange", route)' in HTML
    assert "function currentRecording()" in HTML


def test_leaving_a_recording_goes_through_the_hash_too():
    """The back control must navigate, not just hide.

    Hiding the panel without changing the hash would leave the address bar
    pointing at a brief that is no longer on screen - and a reload would
    reopen it.
    """
    body = _function_body("showRecording")
    assert 'location.hash = "#gallery"' in body


def test_a_link_to_a_missing_recording_says_so():
    """A link can outlive the recording it points at.

    /api/gallery/<unknown> answers 404, and rendering that as a brief would
    throw and leave a blank panel. Saying it is gone is the same rule as
    recommending nothing out loud.
    """
    body = _function_body("showRecording")
    assert "response.ok" in body
    assert "could not be found" in body


def test_the_page_declares_a_viewport():
    """Without this a phone renders at ~980px and scales down, so every word is
    unreadable.

    NOT VERIFIED ON A DEVICE. No browser runs in this suite, so everything below
    asserts that a CSS property is present, never that the result looks right.
    The layout is fluid and the four known narrow-screen hazards are guarded,
    which is as far as reading can take it - actually opening the live site on a
    phone is a separate check nobody has done yet.
    """
    assert 'name="viewport"' in HTML
    assert "width=device-width" in HTML


# --- Narrow screens ----------------------------------------------------------
#
# Nobody had opened this on a phone, and most people who follow a link on one
# will not open it again on a laptop. These are the four things that would have
# broken there, each asserted because each is a single character away from being
# reverted by a tidy-up.


def test_the_headline_scales_down_on_a_narrow_screen():
    """2.9rem is 46px, which is most of the width of a small phone."""
    assert "clamp(2rem, 8vw, 2.9rem)" in HTML


def test_long_provider_strings_can_break():
    """Company names, tickers and headlines all arrive from providers, so
    nothing here controls their length. One long token without this pushes the
    page wider than the screen and puts a horizontal scrollbar under
    everything."""
    assert "overflow-wrap: break-word" in HTML


def test_the_sector_grid_can_shrink_below_its_track():
    """`minmax(15rem, 1fr)` keeps a 15rem column even when the screen is
    narrower than 15rem, which overflows. min() lets the track shrink to the
    container instead."""
    assert "minmax(min(15rem, 100%), 1fr)" in HTML


def test_the_tabs_wrap_rather_than_clip():
    """Three bold tabs are close to the full width of a small phone, and a
    third one falling off the edge is a navigation model with a hidden
    destination."""
    tabs = HTML[HTML.index("  .tabs {") :]
    assert "flex-wrap: wrap" in tabs[: tabs.index("}")]
