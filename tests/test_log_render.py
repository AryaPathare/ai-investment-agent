"""The rendered log must not drift from the log.

``docs/project_log.html`` is committed so the document is available without
running anything, which means it is a copy - and a copy nobody regenerates goes
stale silently. It did, within minutes of being created: three entries were
appended and the committed HTML still described the previous state.

This is the same failure as prose drifting from behaviour, and it gets the same
instrument. Nothing here is about how the document LOOKS; it fails when the
committed file is not what the current markdown produces.

    python -m scripts.build_log_html
"""

from pathlib import Path

import pytest

from scripts.build_log_html import SOURCE, TARGET, to_html


def test_the_rendered_log_is_current():
    """Regenerate and compare. The fix when this fails is to run the builder."""
    if not TARGET.exists():  # pragma: no cover - only on a fresh clone
        pytest.fail(f"{TARGET.name} is missing. Run: python -m scripts.build_log_html")

    expected = to_html(SOURCE.read_text(encoding="utf-8"))
    committed = TARGET.read_text(encoding="utf-8")

    # Reduced to a bool BEFORE asserting. Comparing the strings directly makes
    # pytest dump both sides - a hundred kilobytes of HTML - and the one useful
    # line, which is the command to run, scrolls away.
    is_current = expected in committed
    assert is_current, (
        "docs/project_log.html is out of date with docs/PROJECT_LOG.md.\n"
        "Fix: python -m scripts.build_log_html"
    )


def test_every_entry_in_the_log_reaches_the_document():
    """A converter that quietly drops a section would still pass the check above
    on the day it was run. This counts what actually arrived."""
    markdown = SOURCE.read_text(encoding="utf-8")
    rendered = to_html(markdown)

    entries = [
        line for line in markdown.split("\n")
        if line.startswith("### ") and line[4:5].isdigit()
    ]
    assert len(entries) >= 62, "entries went missing from the source"
    assert rendered.count("<h3") >= len(entries)


def test_no_markdown_survives_into_the_document():
    """Bold markers and fences leaking through mean a converter gap, and the
    reader sees raw syntax. Both happened on the first build."""
    rendered = to_html(SOURCE.read_text(encoding="utf-8"))
    assert "**" not in rendered

    # A pipe inside a table cell must survive the column split - the provider
    # facts table documents TheNewsAPI's own "|" operator.
    assert "<td><strong><code>|</code>" in rendered.replace("</strong>", "</strong>")


def test_the_builder_is_idempotent():
    """Two runs over the same source produce the same bytes, or the check above
    would fail at random."""
    markdown = SOURCE.read_text(encoding="utf-8")
    assert to_html(markdown) == to_html(markdown)


def test_the_source_is_where_the_builder_thinks():
    assert SOURCE.exists()
    assert SOURCE.name == "PROJECT_LOG.md"
    assert Path(TARGET).suffix == ".html"
