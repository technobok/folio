"""Document watcher model."""

from dataclasses import dataclass
from datetime import UTC, datetime

from folio.db import get_db, transaction


@dataclass
class DocumentWatcher:
    document_id: int
    username: str
    created_at: str

    @staticmethod
    def watch(document_id: int, username: str) -> None:
        now = datetime.now(UTC).isoformat()
        with transaction() as cursor:
            cursor.execute(
                "INSERT OR IGNORE INTO document_watcher (document_id, username, created_at) "
                "VALUES (?, ?, ?)",
                (document_id, username, now),
            )

    @staticmethod
    def unwatch(document_id: int, username: str) -> None:
        with transaction() as cursor:
            cursor.execute(
                "DELETE FROM document_watcher WHERE document_id = ? AND username = ?",
                (document_id, username),
            )

    @staticmethod
    def is_watching(document_id: int, username: str) -> bool:
        db = get_db()
        row = db.execute(
            "SELECT 1 FROM document_watcher WHERE document_id = ? AND username = ?",
            (document_id, username),
        ).fetchone()
        return row is not None

    @staticmethod
    def get_watchers(document_id: int) -> list[str]:
        db = get_db()
        rows = db.execute(
            "SELECT username FROM document_watcher WHERE document_id = ? ORDER BY created_at",
            (document_id,),
        ).fetchall()
        return [str(row[0]) for row in rows]
