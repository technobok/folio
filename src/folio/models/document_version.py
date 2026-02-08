"""Document version model."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from folio.db import get_db, transaction


@dataclass
class DocumentVersion:
    id: int
    document_id: int
    version_number: int
    content: str
    author: str
    message: str | None
    created_at: str

    @staticmethod
    def _from_row(row: tuple[Any, ...]) -> DocumentVersion:
        return DocumentVersion(
            id=int(row[0]),
            document_id=int(row[1]),
            version_number=int(row[2]),
            content=str(row[3]),
            author=str(row[4]),
            message=row[5] if row[5] is not None else None,
            created_at=str(row[6]),
        )

    _COLUMNS = "id, document_id, version_number, content, author, message, created_at"

    @staticmethod
    def get_by_id(version_id: int) -> DocumentVersion | None:
        db = get_db()
        row = db.execute(
            f"SELECT {DocumentVersion._COLUMNS} FROM document_version WHERE id = ?",
            (version_id,),
        ).fetchone()
        return DocumentVersion._from_row(row) if row else None

    @staticmethod
    def get_latest(document_id: int) -> DocumentVersion | None:
        db = get_db()
        row = db.execute(
            f"SELECT {DocumentVersion._COLUMNS} FROM document_version "
            "WHERE document_id = ? ORDER BY version_number DESC LIMIT 1",
            (document_id,),
        ).fetchone()
        return DocumentVersion._from_row(row) if row else None

    @staticmethod
    def get_by_version_number(document_id: int, version_number: int) -> DocumentVersion | None:
        db = get_db()
        row = db.execute(
            f"SELECT {DocumentVersion._COLUMNS} FROM document_version "
            "WHERE document_id = ? AND version_number = ?",
            (document_id, version_number),
        ).fetchone()
        return DocumentVersion._from_row(row) if row else None

    @staticmethod
    def create(
        document_id: int,
        content: str,
        author: str,
        message: str | None = None,
    ) -> DocumentVersion:
        now = datetime.now(UTC).isoformat()

        with transaction() as cursor:
            # Get next version number
            row = cursor.execute(
                "SELECT COALESCE(MAX(version_number), 0) FROM document_version "
                "WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            next_version = int(row[0]) + 1 if row else 1

            cursor.execute(
                "INSERT INTO document_version "
                "(document_id, version_number, content, author, message, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (document_id, next_version, content, author, message, now),
            )
            row = cursor.execute("SELECT last_insert_rowid()").fetchone()
            version_id = int(row[0]) if row else 0

        return DocumentVersion(
            id=version_id,
            document_id=document_id,
            version_number=next_version,
            content=content,
            author=author,
            message=message,
            created_at=now,
        )

    @staticmethod
    def list_for_document(document_id: int) -> list[DocumentVersion]:
        db = get_db()
        rows = db.execute(
            f"SELECT {DocumentVersion._COLUMNS} FROM document_version "
            "WHERE document_id = ? ORDER BY version_number DESC",
            (document_id,),
        ).fetchall()
        return [DocumentVersion._from_row(row) for row in rows]

    @staticmethod
    def list_recent_activity(limit: int = 50) -> list[dict]:
        """Return recent edits across all documents with document context.

        Returns lightweight dicts (no full content) to avoid loading large text blobs.
        """
        db = get_db()
        rows = db.execute(
            "SELECT dv.id, dv.document_id, dv.version_number, dv.author, dv.message, "
            "dv.created_at, d.slug, d.title "
            "FROM document_version dv "
            "JOIN document d ON d.id = dv.document_id "
            "WHERE d.slug NOT LIKE '%/.%' "
            "ORDER BY dv.created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "version_id": int(row[0]),
                "document_id": int(row[1]),
                "version_number": int(row[2]),
                "author": str(row[3]),
                "message": row[4] if row[4] is not None else None,
                "created_at": str(row[5]),
                "slug": str(row[6]),
                "title": str(row[7]),
            }
            for row in rows
        ]

    @staticmethod
    def count_for_document(document_id: int) -> int:
        db = get_db()
        row = db.execute(
            "SELECT COUNT(*) FROM document_version WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        return int(row[0]) if row else 0
