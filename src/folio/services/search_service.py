"""Full-text search service using FTS5."""

import logging

from folio.db import get_db

log = logging.getLogger(__name__)


def index_document(
    document_id: int,
    title: str,
    content_text: str,
    tags_text: str = "",
) -> None:
    """Add or update a document in the FTS index."""
    db = get_db()
    db.execute("DELETE FROM document_fts WHERE rowid = ?", (document_id,))
    db.execute(
        "INSERT INTO document_fts (rowid, title, content_text, tags_text) VALUES (?, ?, ?, ?)",
        (document_id, title, content_text, tags_text),
    )


def remove_from_index(document_id: int) -> None:
    """Remove a document from the FTS index."""
    db = get_db()
    db.execute("DELETE FROM document_fts WHERE rowid = ?", (document_id,))


def rebuild_index() -> int:
    """Drop and rebuild the entire FTS index from the document table.

    Returns the number of documents indexed.
    Hidden-slug documents (attachments) are excluded.

    For binary documents with NULL current_content, extracts text from
    the blob and persists it to current_content before indexing.
    """
    from folio.services import blob_service, extraction_service

    db = get_db()
    db.execute("DROP TABLE IF EXISTS document_fts")
    db.execute(
        "CREATE VIRTUAL TABLE document_fts USING fts5("
        "title, content_text, tags_text, tokenize='porter unicode61')"
    )

    rows = db.execute(
        "SELECT d.id, d.title, d.current_content, d.mime_type, "
        "fb.sha256_hash "
        "FROM document d "
        "LEFT JOIN document_blob db ON db.document_id = d.id "
        "LEFT JOIN file_blob fb ON fb.id = db.blob_id "
        "WHERE d.slug NOT LIKE '%/.%'"
    ).fetchall()

    count = 0
    for row in rows:
        doc_id = int(row[0] or 0)
        title = str(row[1]) if row[1] else ""
        content = str(row[2]) if row[2] else ""
        mime_type = str(row[3]) if row[3] else ""
        blob_hash = str(row[4]) if row[4] else ""

        # Extract text from binary docs that have no current_content
        if not content and blob_hash:
            blob_path = blob_service.get_blob_path(blob_hash)
            if blob_path.exists():
                blob_bytes = blob_path.read_bytes()
                content = extraction_service.extract_text(blob_bytes, mime_type)
                if content:
                    db.execute(
                        "UPDATE document SET current_content = ? WHERE id = ?",
                        (content, doc_id),
                    )

        # Gather tags for this document
        tag_rows = db.execute(
            "SELECT t.name FROM tag t "
            "JOIN document_tag dt ON dt.tag_id = t.id "
            "WHERE dt.document_id = ?",
            (doc_id,),
        ).fetchall()
        tags_text = " ".join(str(r[0]) for r in tag_rows)

        db.execute(
            "INSERT INTO document_fts (rowid, title, content_text, tags_text) VALUES (?, ?, ?, ?)",
            (doc_id, title, content, tags_text),
        )
        count += 1

    return count


def search(
    query: str,
    limit: int = 50,
    mime_type: str | None = None,
    tag: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """Search documents with optional filters.

    Returns list of dicts with id, title, snippet, etc.
    """
    db = get_db()

    has_query = bool(query and query.strip())

    if has_query:
        # Quote each term to avoid FTS5 syntax errors from special characters
        safe_query = " ".join(f'"{term}"' for term in query.split())
        sql = (
            "SELECT d.id, d.slug, d.title, d.mime_type, d.updated_at, "
            "snippet(document_fts, 1, '<mark>', '</mark>', '...', 40) as snippet "
            "FROM document_fts fts "
            "JOIN document d ON d.id = fts.rowid "
        )
        conditions = ["document_fts MATCH ?", "d.slug NOT LIKE '%/.%'"]
        params: list[str | int] = [safe_query]
    else:
        sql = (
            "SELECT d.id, d.slug, d.title, d.mime_type, d.updated_at, "
            "'' as snippet "
            "FROM document d "
        )
        conditions = ["d.slug NOT LIKE '%/.%'"]
        params: list[str | int] = []

    if mime_type == "markdown":
        conditions.append("d.mime_type = 'text/markdown'")
    elif mime_type == "binary":
        conditions.append("d.mime_type != 'text/markdown'")

    if tag:
        sql += "JOIN document_tag dt ON dt.document_id = d.id JOIN tag t ON t.id = dt.tag_id "
        conditions.append("t.name = ?")
        params.append(tag)

    if date_from:
        conditions.append("d.updated_at >= ?")
        params.append(date_from)

    if date_to:
        conditions.append("d.updated_at <= ?")
        params.append(date_to + "T23:59:59")

    sql += "WHERE " + " AND ".join(conditions)
    sql += (" ORDER BY rank" if has_query else " ORDER BY d.updated_at DESC") + " LIMIT ?"
    params.append(limit)

    rows = db.execute(sql, params).fetchall()

    results: list[dict] = []
    for row in rows:
        doc_id, slug, title, row_mime, updated_at, snippet = row
        results.append(
            {
                "id": int(doc_id or 0),
                "slug": str(slug or ""),
                "title": str(title or ""),
                "mime_type": str(row_mime or ""),
                "updated_at": str(updated_at or ""),
                "snippet": str(snippet) if snippet else "",
            }
        )
    return results


def get_search_facets() -> dict:
    """Return available filter values for the search UI."""
    db = get_db()
    tag_rows = db.execute(
        "SELECT DISTINCT t.name FROM tag t "
        "JOIN document_tag dt ON dt.tag_id = t.id "
        "JOIN document d ON d.id = dt.document_id "
        "WHERE d.slug NOT LIKE '%/.%' "
        "ORDER BY t.name"
    ).fetchall()
    return {"tags": [str(r[0]) for r in tag_rows]}
