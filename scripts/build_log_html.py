"""Render docs/PROJECT_LOG.md as a printable HTML document.

    python -m scripts.build_log_html

Writes ``docs/project_log.html``. Open it and print to PDF: the stylesheet has
page rules, so sessions start on a new page and code does not break across one.

Why this exists rather than a dependency
----------------------------------------
The log is the narrative of the project and the thing worth handing to a person,
but nothing in the toolchain turns markdown into a document - no pandoc, no
weasyprint, no markdown package. Installing one for a file that is built by hand
twice a year is a worse trade than seventy lines of converter, and this way the
build works on a machine that has only the project's own requirements.

The converter handles exactly the markdown the log uses - headings, fenced and
indented code, tables, lists, blockquotes, bold, inline code, links - and
nothing else. If an entry ever needs a feature that is missing, it will render
visibly wrong rather than silently, which is the right failure for a document
somebody is about to read.
"""

import html
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE = PROJECT_ROOT / "docs" / "PROJECT_LOG.md"
TARGET = PROJECT_ROOT / "docs" / "project_log.html"


def _inline(text: str) -> str:
    """Bold, inline code, links and bare URLs, applied to already-escaped text.

    Code spans are extracted FIRST and put back last, so that a ``**`` inside
    backticks is not read as emphasis. The log contains regex fragments where
    that distinction matters.
    """
    spans: list[str] = []

    def stash(match: re.Match) -> str:
        spans.append(match.group(1))
        return f"\x00{len(spans) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash, text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"&lt;(https?://[^&]+)&gt;", r'<a href="\1">\1</a>', text)

    for index, span in enumerate(spans):
        text = text.replace(f"\x00{index}\x00", f"<code>{span}</code>")
    return text


def _table(rows: list[str]) -> str:
    """One markdown table. The second row is the alignment rule and is dropped.

    Escaped pipes have to survive the split. The provider-facts table documents
    TheNewsAPI's ``|`` operator, so a cell there legitimately contains the same
    character the columns are separated by.
    """
    def cells(row: str) -> list[str]:
        parts = row.strip().strip("|").replace(r"\|", "\x01").split("|")
        return [c.strip().replace("\x01", "|") for c in parts]

    head, body = cells(rows[0]), [cells(r) for r in rows[2:]]
    out = ["<table><thead><tr>"]
    out += [f"<th>{_inline(c)}</th>" for c in head]
    out.append("</tr></thead><tbody>")
    for row in body:
        out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def to_html(markdown: str) -> str:
    """Convert the log's markdown subset to HTML."""
    lines = [html.escape(line, quote=False) for line in markdown.split("\n")]
    out: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]

        if line.startswith("```"):
            block, index = [], index + 1
            while index < len(lines) and not lines[index].startswith("```"):
                block.append(lines[index])
                index += 1
            out.append("<pre><code>" + "\n".join(block) + "</code></pre>")
            index += 1
            continue

        # An indented block. The log uses these for output samples and diagrams,
        # where the exact column alignment is the content.
        if line.startswith("    ") and line.strip():
            block = []
            while index < len(lines) and (
                lines[index].startswith("    ") or not lines[index].strip()
            ):
                block.append(lines[index][4:])
                index += 1
            while block and not block[-1].strip():
                block.pop()
            out.append("<pre><code>" + "\n".join(block) + "</code></pre>")
            continue

        if line.startswith("|") and index + 1 < len(lines) and set(
            lines[index + 1].replace("|", "").replace(" ", "")
        ) <= {"-", ":"}:
            block = []
            while index < len(lines) and lines[index].startswith("|"):
                block.append(lines[index])
                index += 1
            out.append(_table(block))
            continue

        heading = re.match(r"^(#{1,4}) (.*)$", line)
        if heading:
            level = len(heading.group(1))
            text = _inline(heading.group(2))
            anchor = re.sub(r"[^a-z0-9]+", "-", heading.group(2).lower()).strip("-")
            out.append(f'<h{level} id="{anchor}">{text}</h{level}>')
            index += 1
            continue

        if re.match(r"^\s*[-*] ", line) or re.match(r"^\s*\d+\. ", line):
            ordered = bool(re.match(r"^\s*\d+\. ", line))
            tag = "ol" if ordered else "ul"
            items: list[str] = []
            while index < len(lines) and (
                re.match(r"^\s*[-*] ", lines[index])
                or re.match(r"^\s*\d+\. ", lines[index])
                or (lines[index].startswith("  ") and lines[index].strip() and items)
            ):
                stripped = re.sub(r"^\s*([-*]|\d+\.) ", "", lines[index])
                if re.match(r"^\s*([-*]|\d+\.) ", lines[index]):
                    items.append(stripped)
                else:  # continuation of the previous item
                    items[-1] += " " + lines[index].strip()
                index += 1
            out.append(
                f"<{tag}>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + f"</{tag}>"
            )
            continue

        if line.startswith(">"):
            out.append(f"<blockquote>{_inline(line.lstrip('> '))}</blockquote>")
            index += 1
            continue

        if line.startswith("---"):
            out.append("<hr>")
            index += 1
            continue

        if not line.strip():
            index += 1
            continue

        paragraph = []
        while index < len(lines) and lines[index].strip() and not re.match(
            r"^(#{1,4} |```|\||>|---|\s*[-*] |\s*\d+\. )", lines[index]
        ) and not lines[index].startswith("    "):
            paragraph.append(lines[index].strip())
            index += 1
        out.append(f"<p>{_inline(' '.join(paragraph))}</p>")

    return "\n".join(out)


STYLE = """
:root {
  --ink: #1a1a1a; --muted: #5c5c5c; --rule: #d8d4cc;
  --bg: #ffffff; --code-bg: #f6f4f0; --accent: #7a3e1d;
}
* { box-sizing: border-box; }
body {
  background: var(--bg); color: var(--ink); margin: 0 auto; padding: 4rem 1.5rem;
  max-width: 44rem; font: 400 11.5pt/1.65 Charter, Georgia, "Times New Roman", serif;
  -webkit-text-size-adjust: 100%;
}
h1, h2, h3, h4 { line-height: 1.25; font-weight: 600; }
h1 { font-size: 2.1rem; margin: 0 0 .4rem; letter-spacing: -0.01em; }
h2 {
  font-size: 1.35rem; margin: 3.2rem 0 1rem; padding-top: .9rem;
  border-top: 2px solid var(--ink);
}
h3 { font-size: 1.08rem; margin: 2.1rem 0 .6rem; color: var(--accent); }
h4 { font-size: 1rem; margin: 1.5rem 0 .4rem; color: var(--muted); }
p { margin: 0 0 1rem; }
strong { font-weight: 600; }
a { color: var(--accent); }
code {
  font: 400 .86em/1.5 "SF Mono", Menlo, Consolas, monospace;
  background: var(--code-bg); padding: .1em .35em; border-radius: 3px;
}
pre {
  background: var(--code-bg); border-left: 3px solid var(--rule);
  padding: .85rem 1rem; overflow-x: auto; margin: 0 0 1.1rem; border-radius: 2px;
}
pre code { background: none; padding: 0; font-size: .8rem; line-height: 1.5; }
ul, ol { margin: 0 0 1rem; padding-left: 1.4rem; }
li { margin: 0 0 .35rem; }
blockquote {
  margin: 0 0 1rem; padding-left: 1rem; border-left: 3px solid var(--rule);
  color: var(--muted);
}
table {
  width: 100%; border-collapse: collapse; margin: 0 0 1.2rem; font-size: .92rem;
  display: block; overflow-x: auto;
}
th, td { text-align: left; padding: .45rem .6rem; border-bottom: 1px solid var(--rule); }
th { font-weight: 600; border-bottom: 2px solid var(--ink); }
hr { border: 0; border-top: 1px solid var(--rule); margin: 2rem 0; }
.subtitle { color: var(--muted); font-size: 1.05rem; margin: 0 0 2.5rem; }

@media print {
  @page { margin: 18mm 16mm; }
  body { padding: 0; max-width: none; font-size: 10pt; }
  h2 { page-break-before: always; page-break-after: avoid; }
  h2:first-of-type { page-break-before: avoid; }
  h3, h4 { page-break-after: avoid; }
  pre, table, blockquote { page-break-inside: avoid; }
  a { color: var(--ink); text-decoration: none; }
}
"""


def main() -> None:
    markdown = SOURCE.read_text(encoding="utf-8")
    body = to_html(markdown)
    entries = len(re.findall(r"^### \d+\. ", markdown, re.MULTILINE))
    sessions = len(re.findall(r"^## Session ", markdown, re.MULTILINE))

    TARGET.write_text(
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Project Log - AI Investment Agent</title>\n"
        f"<style>{STYLE}</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n",
        encoding="utf-8",
    )
    print(f"Wrote {TARGET.relative_to(PROJECT_ROOT)}")
    print(f"  {entries} numbered entries across {sessions} sessions")
    print(f"  {len(markdown.splitlines())} source lines -> {len(body.splitlines())} HTML")
    print("\nOpen it and print to PDF (Ctrl+P, Save as PDF).")


if __name__ == "__main__":
    main()
