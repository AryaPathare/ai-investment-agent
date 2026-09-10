"""Render page 1 of the paper as the image the About tab shows.

    python -m frontend.scripts.build_paper_preview

Reads ``frontend/static/paper.pdf`` and writes two files beside it:

    paper-p1.png      the first page, rasterised
    paper-p1.source   the sha256 of the PDF it was rendered from

WHY AN IMAGE, AND NOT THE PDF ITSELF
------------------------------------
A browser can display a PDF inline in an ``<object>``, which would need no
build step and could never drift. It is still the wrong choice here: the inline
viewer is a full application with its own toolbar and scrollbars, it is
unreliable on phones - several mobile browsers refuse to inline a PDF at all
and offer a download instead - and it would pull 250KB before a visitor has
decided they want it. The preview is decoration on the About tab, so it has to
be cheap and it has to work everywhere, which is what a picture is.

WHY THE SIDECAR HASH
--------------------
The image is a COPY of something, which is the failure mode this project keeps
meeting: `docs/project_log.html` went stale within minutes of being created,
and entry 132 turned down a stat tile for the same reason. So the source hash
is written next to the image and a test compares it against the PDF actually
committed. Replace the paper without re-running this and the suite says so.

WHY pypdfium2 IS NOT IN requirements.txt
----------------------------------------
Nothing at runtime rasterises anything - the server sends a PNG that is already
committed. This is a build-time tool, the same standing Playwright has here, so
it is installed into the venv and deliberately left out of what Render
installs.
"""

import hashlib
from pathlib import Path

import pypdfium2 as pdfium

STATIC = Path(__file__).resolve().parent.parent / "static"
SOURCE = STATIC / "paper.pdf"
IMAGE = STATIC / "paper-p1.png"
STAMP = STATIC / "paper-p1.source"

# The card column is about 21rem wide, so the image is displayed near 330px.
# Rendering at 2x keeps it sharp on a phone, which is the screen most likely to
# see it - below 62rem the About tab stacks and the preview is full width.
SCALE = 2.0
TARGET_WIDTH = 660


def main() -> None:
    data = SOURCE.read_bytes()
    doc = pdfium.PdfDocument(SOURCE)
    page = doc[0]

    # Scale is expressed in points-per-pixel, so derive it from the page's own
    # width rather than assuming A4 - the paper is whatever it was exported as.
    scale = TARGET_WIDTH / page.get_width()
    image = page.render(scale=scale).to_pil()
    image.save(IMAGE, optimize=True)

    STAMP.write_text(hashlib.sha256(data).hexdigest() + "\n", encoding="utf-8")

    print(f"Wrote {IMAGE.name}  {image.width}x{image.height}px, {IMAGE.stat().st_size / 1024:.0f} KB")
    print(f"      {STAMP.name}  sha256 of {SOURCE.name} ({len(doc)} pages)")


if __name__ == "__main__":
    main()
