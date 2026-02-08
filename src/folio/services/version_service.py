"""Version management service - diffs and history."""

import difflib
from dataclasses import dataclass
from html import escape

from folio.models.document_version import DocumentVersion


@dataclass
class AuthorLine:
    line_number: int
    content: str
    author: str
    version_number: int
    created_at: str


def compute_diff(old_content: str, new_content: str, context: int = 3) -> str:
    """Compute a unified diff between two text contents."""
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile="previous",
        tofile="current",
        n=context,
    )
    return "".join(diff)


def compute_html_diff(old_content: str, new_content: str, context: int = 3) -> str:
    """Compute a GitHub-style unified diff as an HTML table."""
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile="previous",
        tofile="current",
        n=context,
    )

    rows: list[str] = []
    old_num = 0
    new_num = 0

    for line in diff:
        # Skip the --- and +++ file headers
        if line.startswith("---") or line.startswith("+++"):
            continue

        text = escape(line.rstrip("\n"))

        if line.startswith("@@"):
            # Parse hunk header: @@ -old_start,old_count +new_start,new_count @@
            parts = line.split()
            old_range = parts[1]  # e.g. -1,5
            new_range = parts[2]  # e.g. +1,7
            old_num = int(old_range.split(",")[0].lstrip("-")) - 1
            new_num = int(new_range.split(",")[0].lstrip("+")) - 1
            rows.append(
                f'<tr class="diff-hunk">'
                f'<td class="diff-ln"></td><td class="diff-ln"></td>'
                f'<td class="diff-marker"></td>'
                f'<td class="diff-code">{text}</td></tr>'
            )
        elif line.startswith("-"):
            old_num += 1
            rows.append(
                f'<tr class="diff-del">'
                f'<td class="diff-ln">{old_num}</td><td class="diff-ln"></td>'
                f'<td class="diff-marker">-</td>'
                f'<td class="diff-code">{text[1:]}</td></tr>'
            )
        elif line.startswith("+"):
            new_num += 1
            rows.append(
                f'<tr class="diff-add">'
                f'<td class="diff-ln"></td><td class="diff-ln">{new_num}</td>'
                f'<td class="diff-marker">+</td>'
                f'<td class="diff-code">{text[1:]}</td></tr>'
            )
        else:
            old_num += 1
            new_num += 1
            rows.append(
                f'<tr class="diff-ctx">'
                f'<td class="diff-ln">{old_num}</td><td class="diff-ln">{new_num}</td>'
                f'<td class="diff-marker"></td>'
                f'<td class="diff-code">{text[1:] if text.startswith(" ") else text}</td></tr>'
            )

    if not rows:
        return '<p class="no-activity">No differences found.</p>'

    return (
        '<table class="diff-table"><tbody>'
        + "\n".join(rows)
        + "</tbody></table>"
    )


def get_diff_between_versions(document_id: int, from_version: int, to_version: int) -> str | None:
    """Get an HTML diff between two version numbers."""
    v_from = DocumentVersion.get_by_version_number(document_id, from_version)
    v_to = DocumentVersion.get_by_version_number(document_id, to_version)
    if not v_from or not v_to:
        return None
    return compute_html_diff(v_from.content, v_to.content)


def save_version(
    document_id: int,
    content: str,
    author: str,
    message: str | None = None,
) -> DocumentVersion:
    """Create a new version and update the document content."""
    from folio.models.document import Document

    version = DocumentVersion.create(
        document_id=document_id,
        content=content,
        author=author,
        message=message,
    )

    doc = Document.get_by_id(document_id)
    if doc:
        doc.update(current_content=content)

    return version


def compute_authors(document_id: int) -> list[AuthorLine]:
    """Compute per-line authorship by walking backward through versions.

    For each line in the current content, determines which version (and author)
    last modified it. Compares current content against each progressively older
    version — lines that differ from the older version are attributed to the
    newer version, unless already attributed.
    """
    versions = DocumentVersion.list_for_document(document_id)
    if not versions:
        return []

    # Versions come newest-first
    current = versions[0]
    current_lines = current.content.splitlines()

    if not current_lines:
        return []

    n = len(current_lines)
    attribution: list[tuple[str, int, str] | None] = [None] * n

    if len(versions) == 1:
        return [
            AuthorLine(i + 1, line, current.author, current.version_number, current.created_at)
            for i, line in enumerate(current_lines)
        ]

    # Walk from newest version backward, comparing current against each older version
    for idx in range(len(versions) - 1):
        newer = versions[idx]
        older = versions[idx + 1]
        older_lines = older.content.splitlines()

        matcher = difflib.SequenceMatcher(None, older_lines, current_lines)
        for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
            if tag in ("replace", "insert"):
                for j in range(j1, j2):
                    if attribution[j] is None:
                        attribution[j] = (newer.author, newer.version_number, newer.created_at)

        if all(a is not None for a in attribution):
            break

    # Remaining unattributed lines belong to the oldest version
    oldest = versions[-1]
    for i in range(n):
        if attribution[i] is None:
            attribution[i] = (oldest.author, oldest.version_number, oldest.created_at)

    return [
        AuthorLine(i + 1, line, attr[0], attr[1], attr[2])
        for i, (line, attr) in enumerate(zip(current_lines, attribution))
        if attr is not None
    ]
