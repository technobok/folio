"""Hash-addressed blob storage service."""

import hashlib
from pathlib import Path

from flask import current_app
from werkzeug.datastructures import FileStorage

from folio.models.attachment import Attachment, FileBlob


def get_blob_path(sha256_hash: str) -> Path:
    """Get the storage path for a blob based on its hash."""
    blobs_dir = Path(current_app.config["BLOBS_DIRECTORY"])
    return blobs_dir / sha256_hash[:2] / sha256_hash


def save_uploaded_file(
    file: FileStorage,
    document_id: int,
    uploaded_by: str,
) -> Attachment:
    """Save an uploaded file with deduplication. Returns the created Attachment."""
    content = file.read()
    sha256_hash = hashlib.sha256(content).hexdigest()
    file_size = len(content)
    mime_type = file.content_type or "application/octet-stream"

    blob, created = FileBlob.get_or_create(sha256_hash, file_size, mime_type)

    if created:
        blob_path = get_blob_path(sha256_hash)
        blob_path.parent.mkdir(parents=True, exist_ok=True)
        blob_path.write_bytes(content)

    filename = file.filename or "unnamed"
    attachment = Attachment.create(
        document_id=document_id,
        blob_id=blob.id,
        filename=filename,
        uploaded_by=uploaded_by,
    )

    return attachment


def get_blob_content(blob: FileBlob) -> bytes | None:
    """Get the content of a blob from disk."""
    blob_path = get_blob_path(blob.sha256_hash)
    if blob_path.exists():
        return blob_path.read_bytes()
    return None


def delete_attachment(attachment: Attachment) -> None:
    """Delete an attachment. Only deletes the blob file if no other attachments reference it."""
    blob = attachment.get_blob()
    attachment.delete()

    if blob:
        from folio.db import get_db

        db = get_db()
        row = db.execute("SELECT COUNT(*) FROM attachment WHERE blob_id = ?", (blob.id,)).fetchone()
        count = int(row[0]) if row else 0

        if count == 0:
            blob_path = get_blob_path(blob.sha256_hash)
            if blob_path.exists():
                blob_path.unlink()
            db.execute("DELETE FROM file_blob WHERE id = ?", (blob.id,))


def format_file_size(size_bytes: int) -> str:
    """Format file size for display."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
