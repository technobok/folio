"""Hash-addressed blob storage service."""

import hashlib
from pathlib import Path

from flask import current_app
from werkzeug.datastructures import FileStorage

from folio.db import get_db, transaction
from folio.models.document import Document, attachment_slug
from folio.models.file_blob import FileBlob


def get_blob_path(sha256_hash: str) -> Path:
    """Get the storage path for a blob based on its hash."""
    blobs_dir = Path(current_app.config["BLOBS_DIRECTORY"])
    return blobs_dir / sha256_hash[:2] / sha256_hash


def _unique_attachment_slug(parent_slug: str, filename: str) -> str:
    """Build an attachment slug, appending a counter on collision.

    Preserves the file extension when adding a counter, e.g.
    ``photo.png`` → ``photo-2.png``.
    """
    base_slug = attachment_slug(parent_slug, filename)
    db = get_db()
    slug = base_slug
    counter = 2
    while db.execute("SELECT 1 FROM document WHERE slug = ?", (slug,)).fetchone():
        # Split filename to preserve extension
        dot_pos = filename.rfind(".")
        if dot_pos > 0:
            name_part = filename[:dot_pos]
            ext_part = filename[dot_pos:]
            slug = attachment_slug(parent_slug, f"{name_part}-{counter}{ext_part}")
        else:
            slug = f"{base_slug}-{counter}"
        counter += 1
    return slug


def save_uploaded_file(
    file: FileStorage,
    parent_doc: Document,
    uploaded_by: str,
) -> Document:
    """Save an uploaded file as a document with blob deduplication.

    Returns the created (or updated) attachment Document.
    """
    content = file.read()
    sha256_hash = hashlib.sha256(content).hexdigest()
    file_size = len(content)
    mime_type = file.content_type or "application/octet-stream"
    filename = file.filename or "unnamed"

    blob, created = FileBlob.get_or_create(sha256_hash, file_size, mime_type)

    if created:
        blob_path = get_blob_path(sha256_hash)
        blob_path.parent.mkdir(parents=True, exist_ok=True)
        blob_path.write_bytes(content)

    # Check if a document with this exact slug already exists (re-upload)
    exact_slug = attachment_slug(parent_doc.slug, filename)
    existing = Document.get_by_slug(exact_slug)

    if existing:
        # Update the blob link for the existing attachment document
        with transaction() as cursor:
            cursor.execute("DELETE FROM document_blob WHERE document_id = ?", (existing.id,))
            cursor.execute(
                "INSERT INTO document_blob (document_id, blob_id) VALUES (?, ?)",
                (existing.id, blob.id),
            )
        existing.update(mime_type=mime_type, file_size=file_size)
        return existing

    # Create a new attachment document
    slug = _unique_attachment_slug(parent_doc.slug, filename)
    doc = Document.create(
        title=filename,
        created_by=uploaded_by,
        content=None,
        mime_type=mime_type,
        slug=slug,
        file_size=file_size,
    )

    with transaction() as cursor:
        cursor.execute(
            "INSERT INTO document_blob (document_id, blob_id) VALUES (?, ?)",
            (doc.id, blob.id),
        )

    return doc


def get_blob_content(blob: FileBlob) -> bytes | None:
    """Get the content of a blob from disk."""
    blob_path = get_blob_path(blob.sha256_hash)
    if blob_path.exists():
        return blob_path.read_bytes()
    return None


def delete_binary_document(doc: Document) -> None:
    """Delete a binary document and clean up its blob if unreferenced."""
    blob = doc.get_blob()
    doc.delete()  # CASCADE removes document_blob row

    if blob:
        db = get_db()
        row = db.execute(
            "SELECT COUNT(*) FROM document_blob WHERE blob_id = ?", (blob.id,)
        ).fetchone()
        count = int(row[0]) if row else 0

        if count == 0:
            blob_path = get_blob_path(blob.sha256_hash)
            if blob_path.exists():
                blob_path.unlink()
            with transaction() as cursor:
                cursor.execute("DELETE FROM file_blob WHERE id = ?", (blob.id,))


def format_file_size(size_bytes: int) -> str:
    """Format file size for display."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
