"""Tag model."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from folio.db import get_db, transaction

TAG_COLORS = [
    "#3b82f6",  # blue
    "#ef4444",  # red
    "#10b981",  # green
    "#f59e0b",  # amber
    "#8b5cf6",  # violet
    "#ec4899",  # pink
    "#06b6d4",  # cyan
    "#f97316",  # orange
]

LIGHT_TAG_COLORS = {"#f59e0b", "#06b6d4", "#f97316"}


def is_light_color(color: str) -> bool:
    return color in LIGHT_TAG_COLORS


@dataclass
class Tag:
    id: int
    name: str
    color: str
    created_at: str

    @staticmethod
    def _from_row(row: tuple[Any, ...]) -> Tag:
        return Tag(
            id=int(row[0]),
            name=str(row[1]),
            color=str(row[2]),
            created_at=str(row[3]),
        )

    _COLUMNS = "id, name, color, created_at"

    @staticmethod
    def get_by_id(tag_id: int) -> Tag | None:
        db = get_db()
        row = db.execute(f"SELECT {Tag._COLUMNS} FROM tag WHERE id = ?", (tag_id,)).fetchone()
        return Tag._from_row(row) if row else None

    @staticmethod
    def get_by_name(name: str) -> Tag | None:
        db = get_db()
        row = db.execute(f"SELECT {Tag._COLUMNS} FROM tag WHERE name = ?", (name,)).fetchone()
        return Tag._from_row(row) if row else None

    @staticmethod
    def create(name: str, color: str = "#3b82f6") -> Tag:
        now = datetime.now(UTC).isoformat()
        with transaction() as cursor:
            cursor.execute(
                "INSERT INTO tag (name, color, created_at) VALUES (?, ?, ?)",
                (name, color, now),
            )
            row = cursor.execute("SELECT last_insert_rowid()").fetchone()
            tag_id = int(row[0]) if row else 0
        return Tag(id=tag_id, name=name, color=color, created_at=now)

    @staticmethod
    def get_all() -> list[Tag]:
        db = get_db()
        rows = db.execute(f"SELECT {Tag._COLUMNS} FROM tag ORDER BY name").fetchall()
        return [Tag._from_row(row) for row in rows]

    @staticmethod
    def get_for_document(document_id: int) -> list[Tag]:
        db = get_db()
        rows = db.execute(
            "SELECT t.id, t.name, t.color, t.created_at "
            "FROM tag t JOIN document_tag dt ON t.id = dt.tag_id "
            "WHERE dt.document_id = ? ORDER BY t.name",
            (document_id,),
        ).fetchall()
        return [Tag._from_row(row) for row in rows]

    @staticmethod
    def add_to_document(document_id: int, tag_id: int) -> None:
        now = datetime.now(UTC).isoformat()
        with transaction() as cursor:
            cursor.execute(
                "INSERT OR IGNORE INTO document_tag (document_id, tag_id, created_at) "
                "VALUES (?, ?, ?)",
                (document_id, tag_id, now),
            )

    @staticmethod
    def remove_from_document(document_id: int, tag_id: int) -> None:
        with transaction() as cursor:
            cursor.execute(
                "DELETE FROM document_tag WHERE document_id = ? AND tag_id = ?",
                (document_id, tag_id),
            )

    def delete(self) -> None:
        with transaction() as cursor:
            cursor.execute("DELETE FROM tag WHERE id = ?", (self.id,))
