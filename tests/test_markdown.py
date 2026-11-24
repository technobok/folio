"""Documents are Markdown that people write: rendered with mistune, raw HTML is shown
as text and unsafe links are neutralised (it used to run: Python-Markdown passes it
through); headings keep the ids Python-Markdown's toc extension gave them."""

import re
from types import SimpleNamespace

import pytest
from flask import g

from folio import create_app
from folio.db import init_db_at
from folio.services.markdown_service import render_block, render_inline

ATTACK = (
    "Before\n\n"
    "<script>alert('doc')</script>\n\n"
    '<img src="x" onerror="alert(1)">\n\n'
    "[click](javascript:alert(1)) [vb](vbscript:msgbox) [ok](https://example.com)\n\n"
    "![pic](javascript:alert(1))\n"
)


def _ids(html: str) -> list[str]:
    return re.findall(r'<h\d id="([^"]*)"', html)


def test_a_document_cannot_run_script() -> None:
    html = str(render_block(ATTACK))
    assert "<script" not in html and "&lt;script&gt;" in html
    assert '<img src="x"' not in html and "onerror=" not in html.replace("onerror=&quot;", "")
    assert "javascript:" not in html and "vbscript:" not in html
    assert html.count('href="#harmful-link"') == 2
    assert '<a href="https://example.com">ok</a>' in html


def test_headings_keep_their_ids() -> None:
    doc = (
        "# Getting Started\n\n## Install & run!\n\n## Install & run!\n\n### Über *uns*\n\n"
        "## 2026 Plan — Q1\n\n## Use **this** one\n"
    )
    assert _ids(str(render_block(doc))) == [
        "getting-started",
        "install-run",
        "install-run_1",
        "uber-uns",
        "2026-plan-q1",
        "use-this-one",
    ]


def test_tables_code_and_lists_render() -> None:
    doc = (
        "| a | b |\n|---|---|\n| 1 | 2 |\n\n```python\nx = '<b>'\n```\n\n- one\n- two\n\n~~old~~\n"
    )
    html = str(render_block(doc))
    assert "<table>" in html and "<td>1</td>" in html
    assert "<pre><code class=\"language-python\">x = '&lt;b&gt;'\n</code></pre>" in html
    assert "<li>one</li>" in html and "<del>old</del>" in html


def test_inline_text_loses_its_paragraph() -> None:
    assert str(render_inline("a **b**")) == "a <strong>b</strong>"
    assert str(render_inline("<i>x</i>")) == "&lt;i&gt;x&lt;/i&gt;"
    assert render_inline("") == "" and render_block(None) == ""


@pytest.fixture
def app(tmp_path):
    db_path = str(tmp_path / "folio.sqlite3")
    init_db_at(db_path)
    application = create_app(
        test_config={
            "DATABASE_PATH": db_path,
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "BLOBS_DIRECTORY": str(tmp_path / "blobs"),
        }
    )

    def signed_in() -> None:
        g.user = SimpleNamespace(username="tester", fullname="Tester", email="t@example.com")

    application.before_request_funcs.setdefault(None, []).insert(0, signed_in)
    return application


def test_the_document_page_shows_an_attack_as_text(app) -> None:
    with app.app_context():
        from folio.models.document import Document

        doc = Document.create(
            title="Attack", created_by="tester", content=ATTACK, file_size=len(ATTACK)
        )
        slug = doc.slug
    resp = app.test_client().get(f"/documents/view/{slug}")
    assert resp.status_code == 200
    page = resp.get_data(as_text=True)
    body = page.split('<div class="markdown-content">', 1)[1].split("</div>", 1)[0]
    assert "<script" not in body and "&lt;script&gt;" in body
    assert "javascript:" not in body
