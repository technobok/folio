"""FileBlob model — deduplicated file storage."""

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
