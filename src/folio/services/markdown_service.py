"""Markdown → HTML for documents and other text people write.

Rendered with mistune 3 (the Markdown library the other projects use) with
``escape=True``: raw HTML in a document is shown as text, and a link or image to a
``javascript:``/``vbscript:``/``file:``/non-image ``data:`` URL is neutralised
(mistune's ``safe_url``). A document can therefore never run script in a reader's
browser. Until 2026-11-24 folio used Python-Markdown, which passes raw HTML and
``javascript:`` links straight through.

Headings get the ids Python-Markdown's ``toc`` extension gave them (``Getting
Started`` → ``getting-started``; a repeat → ``getting-started_1``), so links to a
document's sections keep working and tocbot builds the contents sidebar from them.
Tables, fenced code and strikethrough are on.
"""

import re
import unicodedata
from typing import Any

import mistune
from markupsafe import Markup
from mistune.toc import add_toc_hook

_PLUGINS = ["table", "strikethrough"]
_INLINE = mistune.create_markdown(escape=True, plugins=_PLUGINS)
_IDCOUNT = re.compile(r"^(.*)_([0-9]+)$")


def _slugify(text: str) -> str:
    """Python-Markdown's ``toc.slugify`` (ASCII): ``Getting Started!`` → ``getting-started``."""
    value = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[-\s]+", "-", value)


def _unique(heading_id: str, seen: set[str]) -> str:
    """Python-Markdown's ``toc.unique``: ``x``, then ``x_1``, ``x_2`` …"""
    while heading_id in seen or not heading_id:
        m = _IDCOUNT.match(heading_id)
        heading_id = f"{m.group(1)}_{int(m.group(2)) + 1}" if m else f"{heading_id}_1"
    seen.add(heading_id)
    return heading_id


def render_block(text: str | None) -> Markup:
    """A document: block Markdown with heading ids."""
    if not text:
        return Markup("")
    seen: set[str] = set()

    def heading_id(token: dict[str, Any], _index: int) -> str:
        return _unique(_slugify(str(token.get("text", ""))), seen)

    md = mistune.create_markdown(escape=True, plugins=_PLUGINS)
    add_toc_hook(md, min_level=1, max_level=6, heading_id=heading_id)
    return Markup(str(md(text)))


def render_inline(text: str | None) -> Markup:
    """A short text: one paragraph loses its <p> so it sits inline."""
    if not text:
        return Markup("")
    html = str(_INLINE(text)).strip()
    if html.startswith("<p>") and html.endswith("</p>") and html.count("<p>") == 1:
        html = html[3:-4]
    return Markup(html)
