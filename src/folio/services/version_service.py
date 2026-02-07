"""Version management service - diffs and history."""

import difflib

from folio.models.document_version import DocumentVersion


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
    """Compute an HTML table diff between two text contents."""
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()
    differ = difflib.HtmlDiff(wrapcolumn=80)
    return differ.make_table(
        old_lines,
        new_lines,
        fromdesc="Previous",
        todesc="Current",
        context=True,
        numlines=context,
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
