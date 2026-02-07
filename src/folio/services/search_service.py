"""Full-text search service using FTS5."""

from folio.db import get_db


def _delete_from_fts(
    document_id: int, old_title: str, old_content: str, old_tags: str = ""
) -> None:
    """Remove existing entry from the contentless FTS index.

    Contentless FTS5 tables do not support regular DELETE.  Instead we
    must use the 'delete' command and supply the original column values
    so the inverted index can be updated.
    """
    db = get_db()
    db.execute(
        "INSERT INTO document_fts(document_fts, rowid, title, content_text, tags_text) "
        "VALUES('delete', ?, ?, ?, ?)",
        (document_id, old_title, old_content, old_tags),
    )


def index_document(
    document_id: int,
    title: str,
    content_text: str,
    tags_text: str = "",
    old_title: str | None = None,
    old_content: str | None = None,
) -> None:
    """Add or update a document in the FTS index.

    For updates, pass old_title and old_content so the previous FTS
    entry can be removed from the contentless index.
    """
    db = get_db()
    if old_title is not None and old_content is not None:
        _delete_from_fts(document_id, old_title, old_content)
    db.execute(
        "INSERT INTO document_fts (rowid, title, content_text, tags_text) VALUES (?, ?, ?, ?)",
        (document_id, title, content_text, tags_text),
    )


def remove_from_index(document_id: int, title: str, content: str) -> None:
    """Remove a document from the FTS index."""
    _delete_from_fts(document_id, title, content)


def search(query: str, limit: int = 50) -> list[dict]:
    """Search documents. Returns list of dicts with id, title, snippet."""
    db = get_db()
    # Quote each term to avoid FTS5 syntax errors from special characters
    safe_query = " ".join(f'"{term}"' for term in query.split())
    rows = db.execute(
        "SELECT d.id, d.slug, d.title, d.mime_type, d.updated_at, "
        "snippet(document_fts, 1, '<mark>', '</mark>', '...', 40) as snippet "
        "FROM document_fts fts "
        "JOIN document d ON d.id = fts.rowid "
        "WHERE document_fts MATCH ? "
        "ORDER BY rank LIMIT ?",
        (safe_query, limit),
    ).fetchall()

    results: list[dict] = []
    for row in rows:
        doc_id, slug, title, mime_type, updated_at, snippet = row
        results.append(
            {
                "id": int(doc_id or 0),
                "slug": str(slug or ""),
                "title": str(title or ""),
                "mime_type": str(mime_type or ""),
                "updated_at": str(updated_at or ""),
                "snippet": str(snippet) if snippet else "",
            }
        )
    return results
