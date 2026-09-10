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

import hashlib
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

    This used to anchor on `<nav class="tabs">`, which stopped meaning anything
    the moment F6 moved the nav into a banner ABOVE the disclaimer - the test
    failed while the disclaimer had not moved at all. It now anchors on the
    thing that actually does the hiding: the tab panels. The disclaimer must
    appear before the first one opens, and exist exactly once, so there is no
    second copy inside a panel and no way for a tab switch to take it off
    screen.
    """
    first_panel = HTML.index('<div class="tab" id="tab-run">')
    assert 'id="disclaimer"' in HTML[:first_panel]
    assert HTML.count('id="disclaimer"') == 1


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
    """`minmax(21rem, 1fr)` keeps a 21rem column even when the screen is
    narrower than 21rem, which overflows. min() lets the track shrink to the
    container instead.

    The track width itself is a layout choice and has moved once (15rem -> 21rem
    when F6 widened the panel and a 15rem track started fitting four columns).
    The `min()` wrapper is the part this test exists for: without it the grid
    overflows every phone, whatever the number is."""
    assert "minmax(min(21rem, 100%), 1fr)" in HTML


def test_the_sector_name_cannot_be_the_thing_that_gives():
    """"Consumer Defensive" wrapped and no other sector did.

    It looked like a width problem and was not. `.sectors label` is a flex row
    of three children - checkbox, name, example - and the NAME had no flex rule
    of its own, so it was the child that gave when the row ran short. Consumer
    Defensive is both the longest name and carries the longest example ("food
    producers, household goods"), which made that one cell the tightest in the
    grid and the only one to break.

    Two halves, in different parts of the file, and the CSS is inert without
    the class - so both are asserted here. Widening the page would have hidden
    this without fixing it, and it would have returned at the next viewport.
    """
    assert ".sectors .nm { flex: none; white-space: nowrap; }" in HTML
    assert 'el("span", option.name, "nm")' in HTML


def test_the_tabs_live_in_the_banner():
    """F6 moved the navigation into the banner. If a tidy-up ever leaves a
    second `.tabs` nav behind in the page body, there are two navigation
    models and only one of them gets `aria-current`."""
    assert HTML.count('<nav class="tabs">') == 1
    banner = HTML[HTML.index('<header class="banner">') : HTML.index("</header>")]
    assert '<nav class="tabs">' in banner


def test_the_gutter_decoration_is_hidden_from_assistive_tech():
    """The spines repeat what the page says properly elsewhere. Decoration
    that reads aloud is noise, and this decoration is the kind a redesign
    forgets to mark."""
    for spine in ('class="spine spine-l"', 'class="spine spine-r"'):
        block = HTML[HTML.index(spine) :]
        assert 'aria-hidden="true"' in block[: block.index(">") + 1]


def test_the_tabs_wrap_rather_than_clip():
    """Three bold tabs are close to the full width of a small phone, and a
    third one falling off the edge is a navigation model with a hidden
    destination."""
    tabs = HTML[HTML.index("  .tabs {") :]
    assert "flex-wrap: wrap" in tabs[: tabs.index("}")]


def test_a_choice_menu_starts_blank():
    """A <select> shows its first option, so before F8 the form arrived already
    claiming the visitor was a beginner at low risk holding USD - three answers
    nobody had given. The blank option must be added BEFORE the real ones, and
    `required` must come from the server's field rather than a list kept here."""
    assert 'select.append(new Option(field.required ? "Choose one" : "Not specified", ""))' in HTML
    assert "if (field.required) select.required = true;" in HTML


def test_an_unanswered_optional_menu_is_null_not_empty_string():
    """`investment_currency` is `Literal[...] | None`. An empty string is
    neither, and would come back as a 422 on a field the model says may be
    skipped."""
    assert 'profile[field.name] = $(field.name).value || null;' in HTML


# --- The About tab's right column --------------------------------------------

PAPER = PROJECT_ROOT / "frontend" / "static" / "paper.pdf"
PREVIEW = PROJECT_ROOT / "frontend" / "static" / "paper-p1.png"
STAMP = PROJECT_ROOT / "frontend" / "static" / "paper-p1.source"


def _about_tab() -> str:
    """Just the About panel, so a check about it cannot pass on another tab."""
    start = HTML.index('id="tab-about"')
    return HTML[start : HTML.index("</main>", start)]


def test_the_pipeline_band_appears_once():
    """It used to be rendered twice, verbatim - on the run tab and on About.

    Two identical copies of the same explanation is the redundancy this was
    asked to remove, and duplicated markup is also how the two copies would
    eventually come to disagree. The run tab keeps it, because that is where
    somebody is deciding whether to start one.
    """
    assert HTML.count("<h2>How a run works</h2>") == 1
    assert "How a run works" not in _about_tab()


def test_the_about_tab_offers_the_paper():
    """The card that fills the column the prose does not use.

    It links to a file this app serves itself rather than to GitHub: the point
    of the About tab is to explain the project to somebody who has not decided
    to look at the code yet.
    """
    about = _about_tab()

    assert 'href="/paper.pdf"' in about, "the card is gone from About"
    assert 'class="about"' in about, "the About tab is no longer two columns"


def test_the_preview_opens_the_thing_it_is_a_picture_of():
    """A picture of a document that does nothing when clicked is a dead control.

    The image and the card must point at the same file - it would be easy to
    rename the PDF, fix the card's href, and leave the preview pointing at a
    404 nobody clicks often enough to notice.
    """
    about = _about_tab()
    start = about.index('class="preview"')
    anchor = about[start : about.index("</a>", start)]

    assert 'href="/paper.pdf"' in anchor, "the preview does not open the PDF"
    assert 'src="/paper-p1.png"' in anchor, "the preview has no image"
    assert "alt=" in anchor and 'aria-label' in anchor


def test_the_preview_declares_its_size():
    """Without width and height the About tab reflows when the image lands.

    The preview is 44KB below the fold of a lazily-loaded tab, so it arrives
    late by design; a box reserved for it is what stops the prose beside it
    jumping once it does.
    """
    about = _about_tab()

    assert re.search(r'<img src="/paper-p1\.png" width="\d+" height="\d+"', about), (
        "the preview image declares no intrinsic size"
    )


def test_the_preview_was_rendered_from_the_pdf_that_is_committed():
    """The image is a COPY, which is the failure this project keeps meeting.

    `docs/project_log.html` went stale within minutes of being created and
    entry 132 turned down a stat tile for the same reason. So the build script
    stamps the source hash next to the image and this compares it against the
    PDF actually committed: replace the paper, forget the preview, and the
    suite says so rather than the site showing last month's title page.

    Pure hashlib on purpose - the renderer is a build-time dependency that CI
    does not install, so the guard must not need it.
    """
    if not (PAPER.exists() and STAMP.exists()):
        pytest.skip("no paper committed yet")

    actual = hashlib.sha256(PAPER.read_bytes()).hexdigest()

    assert actual == STAMP.read_text(encoding="utf-8").strip(), (
        "paper.pdf has changed since paper-p1.png was rendered - "
        "run: python -m frontend.scripts.build_paper_preview"
    )


def _pdf_pages(data: bytes) -> int:
    """Page count, read from the file rather than from anything that claims one.

    Counting `/Type /Page` markers, minus the `/Type /Pages` tree nodes that
    also match. This is a heuristic and it has a known blind spot - a producer
    that puts its page objects in compressed object streams hides them from a
    byte scan - so a zero here means UNKNOWN, not empty, and the caller skips
    rather than asserting something it did not actually measure.
    """
    return data.count(b"/Type /Page") - data.count(b"/Type /Pages")


def test_the_card_states_the_page_count_the_pdf_actually_has():
    """The one number on the card, checked against the file it describes.

    Entry 132 turned down a tile reading "11 recorded runs" because a figure
    copied by hand goes stale silently. This one is copied by hand too - so it
    gets the guard that makes the staleness loud. Swapping in a longer paper
    and not updating the card fails here, and the fix is one number.
    """
    if not PAPER.exists():
        pytest.skip("no paper committed yet")

    pages = _pdf_pages(PAPER.read_bytes())
    if pages <= 0:
        pytest.skip("this PDF's page objects are not visible to a byte scan")

    stated = re.search(r'id="paper-pages">(\d+)<', HTML)

    assert stated, "the card states no page count"
    assert int(stated.group(1)) == pages, (
        f"the card says {stated.group(1)} pages; the PDF has {pages}"
    )
