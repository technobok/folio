"""Attachment and FileBlob models."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from folio.db import get_db, transaction


@dataclass
class FileBlob:
    """Deduplicated file storage. Path: {BLOBS_DIR}/{hash[:2]}/{hash}"""

    id: int
    sha256_hash: str
    file_size: int
    mime_type: str
    created_at: str

    @staticmethod
    def _from_row(row: tuple[Any, ...]) -> FileBlob:
        return FileBlob(
            id=int(row[0]),
            sha256_hash=str(row[1]),
            file_size=int(row[2]),
            mime_type=str(row[3]),
            created_at=str(row[4]),
        )

    @staticmethod
    def get_by_id(blob_id: int) -> FileBlob | None:
        db = get_db()
        row = db.execute(
            "SELECT id, sha256_hash, file_size, mime_type, created_at FROM file_blob WHERE id = ?",
            (blob_id,),
        ).fetchone()
        return FileBlob._from_row(row) if row else None

    @staticmethod
    def get_by_hash(sha256_hash: str) -> FileBlob | None:
        db = get_db()
        row = db.execute(
            "SELECT id, sha256_hash, file_size, mime_type, created_at "
            "FROM file_blob WHERE sha256_hash = ?",
            (sha256_hash,),
        ).fetchone()
        return FileBlob._from_row(row) if row else None

    @staticmethod
    def create(sha256_hash: str, file_size: int, mime_type: str) -> FileBlob:
        now = datetime.now(UTC).isoformat()
        with transaction() as cursor:
            cursor.execute(
                "INSERT INTO file_blob (sha256_hash, file_size, mime_type, created_at) "
                "VALUES (?, ?, ?, ?)",
                (sha256_hash, file_size, mime_type, now),
            )
            row = cursor.execute("SELECT last_insert_rowid()").fetchone()
            blob_id = int(row[0]) if row else 0

        return FileBlob(
            id=blob_id,
            sha256_hash=sha256_hash,
            file_size=file_size,
            mime_type=mime_type,
            created_at=now,
        )

    @staticmethod
    def get_or_create(sha256_hash: str, file_size: int, mime_type: str) -> tuple[FileBlob, bool]:
        existing = FileBlob.get_by_hash(sha256_hash)
        if existing:
            return existing, False
        return FileBlob.create(sha256_hash, file_size, mime_type), True


@dataclass
class Attachment:
    """Per-upload attachment metadata, linked to a deduplicated FileBlob."""

    id: int
    document_id: int
    blob_id: int
    filename: str
    uploaded_by: str
    created_at: str

    @staticmethod
    def _from_row(row: tuple[Any, ...]) -> Attachment:
        return Attachment(
            id=int(row[0]),
            document_id=int(row[1]),
            blob_id=int(row[2]),
            filename=str(row[3]),
            uploaded_by=str(row[4]),
            created_at=str(row[5]),
        )

    _COLUMNS = "id, document_id, blob_id, filename, uploaded_by, created_at"

    @staticmethod
    def create(
        document_id: int,
        blob_id: int,
        filename: str,
        uploaded_by: str,
    ) -> Attachment:
        now = datetime.now(UTC).isoformat()
        with transaction() as cursor:
            cursor.execute(
                "INSERT INTO attachment (document_id, blob_id, filename, uploaded_by, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (document_id, blob_id, filename, uploaded_by, now),
            )
            row = cursor.execute("SELECT last_insert_rowid()").fetchone()
            att_id = int(row[0]) if row else 0

        return Attachment(
            id=att_id,
            document_id=document_id,
            blob_id=blob_id,
            filename=filename,
            uploaded_by=uploaded_by,
            created_at=now,
        )

    @staticmethod
    def get_by_id(attachment_id: int) -> Attachment | None:
        db = get_db()
        row = db.execute(
            f"SELECT {Attachment._COLUMNS} FROM attachment WHERE id = ?",
            (attachment_id,),
        ).fetchone()
        return Attachment._from_row(row) if row else None

    @staticmethod
    def list_for_document(document_id: int) -> list[Attachment]:
        db = get_db()
        rows = db.execute(
            f"SELECT {Attachment._COLUMNS} FROM attachment "
            "WHERE document_id = ? ORDER BY created_at ASC",
            (document_id,),
        ).fetchall()
        return [Attachment._from_row(row) for row in rows]

    def get_blob(self) -> FileBlob | None:
        return FileBlob.get_by_id(self.blob_id)

    def delete(self) -> None:
        with transaction() as cursor:
            cursor.execute("DELETE FROM attachment WHERE id = ?", (self.id,))
