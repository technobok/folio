"""Migration service — one-time conversion of attachments to documents."""

import logging

from folio.db import get_db, transaction

log = logging.getLogger(__name__)


def migrate_attachments() -> int:
    """Migrate all attachment rows into document + document_blob rows.

    For each attachment:
    1. Create a document with slug ``{parent_slug}/.att/{filename}``
    2. Insert a ``document_blob`` row linking to the same ``file_blob``
    3. Rewrite URLs in the parent document's ``current_content`` and all
       ``document_version`` rows
    4. Drop the ``attachment`` table
    5. Bump ``schema_version`` to ``'2'``

    Returns the number of attachments migrated.
    """
    db = get_db()

    # Check if the attachment table still exists
    table_exists = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='attachment'"
    ).fetchone()
    if not table_exists:
        log.info("attachment table does not exist — nothing to migrate")
        return 0

    rows = db.execute(
        "SELECT a.id, a.document_id, a.blob_id, a.filename, a.uploaded_by, a.created_at, "
        "       d.slug AS parent_slug, "
        "       fb.mime_type "
        "FROM attachment a "
        "JOIN document d ON d.id = a.document_id "
        "JOIN file_blob fb ON fb.id = a.blob_id "
        "ORDER BY a.id"
    ).fetchall()

    if not rows:
        log.info("no attachments to migrate")
        return 0

    # Track slug collisions within this migration
    used_slugs: set[str] = set()
    # Map old attachment_id -> new slug (for URL rewriting)
    url_map: dict[int, str] = {}

    with transaction() as cursor:
        for row in rows:
            att_id = int(row[0] or 0)
            blob_id = int(row[2] or 0)
            filename = str(row[3])
            uploaded_by = str(row[4])
            created_at = str(row[5])
            parent_slug = str(row[6])
            mime_type = str(row[7])

            base_slug = f"{parent_slug}/.att/{filename}"
            slug = base_slug

            # Handle duplicate filenames — append att_id as suffix
            if (
                slug in used_slugs
                or cursor.execute("SELECT 1 FROM document WHERE slug = ?", (slug,)).fetchone()
            ):
                dot_pos = filename.rfind(".")
                if dot_pos > 0:
                    name_part = filename[:dot_pos]
                    ext_part = filename[dot_pos:]
                    slug = f"{parent_slug}/.att/{name_part}-{att_id}{ext_part}"
                else:
                    slug = f"{base_slug}-{att_id}"

            used_slugs.add(slug)

            # Create the document
            cursor.execute(
                "INSERT INTO document (slug, title, mime_type, current_content, "
                "created_by, updated_at, created_at) VALUES (?, ?, ?, NULL, ?, ?, ?)",
                (slug, filename, mime_type, uploaded_by, created_at, created_at),
            )
            last_row = cursor.execute("SELECT last_insert_rowid()").fetchone()
            new_doc_id = int(last_row[0]) if last_row else 0

            # Link to blob
            cursor.execute(
                "INSERT INTO document_blob (document_id, blob_id) VALUES (?, ?)",
                (new_doc_id, blob_id),
            )

            url_map[att_id] = slug
            log.debug("migrated attachment %d → %s", att_id, slug)

        # Rewrite URLs in parent documents' current_content and versions
        _rewrite_urls(cursor, url_map)

        # Drop the attachment table
        cursor.execute("DROP TABLE IF EXISTS attachment")

        # Bump schema version
        cursor.execute(
            "INSERT INTO db_metadata (key, value) VALUES ('schema_version', '2') "
            "ON CONFLICT(key) DO UPDATE SET value = '2'"
        )

    log.info("migrated %d attachments to documents", len(rows))
    return len(rows)


def migrate_add_file_size() -> None:
    """Add file_size column to document table and backfill values.

    Bumps schema_version from 3 to 4.
    """
    db = get_db()

    with transaction() as cursor:
        cursor.execute(
            "ALTER TABLE document ADD COLUMN file_size INTEGER NOT NULL DEFAULT 0"
        )

        # Backfill markdown documents from current_content length
        cursor.execute(
            "UPDATE document SET file_size = LENGTH(current_content) "
            "WHERE mime_type = 'text/markdown' AND current_content IS NOT NULL"
        )

        # Backfill binary documents from file_blob.file_size
        cursor.execute(
            "UPDATE document SET file_size = ("
            "  SELECT fb.file_size FROM document_blob db "
            "  JOIN file_blob fb ON fb.id = db.blob_id "
            "  WHERE db.document_id = document.id"
            ") WHERE id IN (SELECT document_id FROM document_blob)"
        )

        cursor.execute(
            "INSERT OR REPLACE INTO db_metadata (key, value) VALUES ('schema_version', '4')"
        )

    log.info("migrated schema to v4: added file_size column to document")


def _rewrite_urls(cursor, url_map: dict[int, str]) -> None:
    """Rewrite /documents/attachment/{id} URLs in document content and versions."""
    for att_id, new_slug in url_map.items():
        old_pattern = f"/documents/attachment/{att_id}"
        new_url = f"/documents/view/{new_slug}"

        # Update current_content in parent documents
        cursor.execute(
            "UPDATE document SET current_content = REPLACE(current_content, ?, ?) "
            "WHERE current_content LIKE ?",
            (old_pattern, new_url, f"%{old_pattern}%"),
        )

        # Update all document_version rows
        cursor.execute(
            "UPDATE document_version SET content = REPLACE(content, ?, ?) WHERE content LIKE ?",
            (old_pattern, new_url, f"%{old_pattern}%"),
        )
