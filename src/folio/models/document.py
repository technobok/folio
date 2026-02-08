"""Document model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from folio.models.file_blob import FileBlob

from slugify import slugify

from folio.db import get_db, transaction


def is_hidden_slug(slug: str) -> bool:
    """Return True if any path component starts with '.'."""
    return any(part.startswith(".") for part in slug.split("/"))


def attachment_slug(parent_slug: str, filename: str) -> str:
    """Build an attachment slug: {parent_slug}/.att/{filename}."""
    return f"{parent_slug}/.att/{filename}"


@dataclass
class Document:
    id: int
    slug: str
    title: str
    mime_type: str
    current_content: str | None
    created_by: str
    updated_at: str
    created_at: str

    @staticmethod
    def _from_row(row: tuple[Any, ...]) -> Document:
        return Document(
            id=int(row[0]),
            slug=str(row[1]),
            title=str(row[2]),
            mime_type=str(row[3]),
            current_content=row[4] if row[4] is not None else None,
            created_by=str(row[5]),
            updated_at=str(row[6]),
            created_at=str(row[7]),
        )

    _COLUMNS = "id, slug, title, mime_type, current_content, created_by, updated_at, created_at"

    @staticmethod
    def get_by_id(doc_id: int) -> Document | None:
        db = get_db()
        row = db.execute(
            f"SELECT {Document._COLUMNS} FROM document WHERE id = ?", (doc_id,)
        ).fetchone()
        return Document._from_row(row) if row else None

    @staticmethod
    def get_by_slug(slug: str) -> Document | None:
        db = get_db()
        row = db.execute(
            f"SELECT {Document._COLUMNS} FROM document WHERE slug = ?", (slug,)
        ).fetchone()
        return Document._from_row(row) if row else None

    @staticmethod
    def generate_slug(title: str, parent_path: str = "") -> str:
        """Generate a unique slug from title, optionally under a parent path."""
        base = slugify(title)
        if parent_path:
            parent_path = parent_path.strip("/")
            base = f"{parent_path}/{base}"

        db = get_db()
        slug = base
        counter = 2
        while True:
            row = db.execute("SELECT 1 FROM document WHERE slug = ?", (slug,)).fetchone()
            if not row:
                return slug
            slug = f"{base}-{counter}"
            counter += 1

    @staticmethod
    def create(
        title: str,
        created_by: str,
        content: str | None = None,
        mime_type: str = "text/markdown",
        slug: str | None = None,
        parent_path: str = "",
    ) -> Document:
        now = datetime.now(UTC).isoformat()
        if not slug:
            slug = Document.generate_slug(title, parent_path)

        with transaction() as cursor:
            cursor.execute(
                "INSERT INTO document (slug, title, mime_type, current_content, "
                "created_by, updated_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (slug, title, mime_type, content, created_by, now, now),
            )
            row = cursor.execute("SELECT last_insert_rowid()").fetchone()
            doc_id = int(row[0]) if row else 0

        return Document(
            id=doc_id,
            slug=slug,
            title=title,
            mime_type=mime_type,
            current_content=content,
            created_by=created_by,
            updated_at=now,
            created_at=now,
        )

    def update(self, **kwargs: Any) -> None:
        now = datetime.now(UTC).isoformat()
        updates = []
        params: list[Any] = []

        for field in ("title", "slug", "current_content", "mime_type"):
            if field in kwargs:
                updates.append(f"{field} = ?")
                params.append(kwargs[field])
                setattr(self, field, kwargs[field])

        if updates:
            updates.append("updated_at = ?")
            params.append(now)
            params.append(self.id)
            with transaction() as cursor:
                cursor.execute(f"UPDATE document SET {', '.join(updates)} WHERE id = ?", params)
            self.updated_at = now

    def delete(self) -> None:
        with transaction() as cursor:
            cursor.execute("DELETE FROM document WHERE id = ?", (self.id,))

    @staticmethod
    def list_all(
        prefix: str = "",
        limit: int = 100,
        offset: int = 0,
        include_hidden: bool = False,
    ) -> list[Document]:
        db = get_db()
        if prefix:
            prefix = prefix.strip("/")
            rows = db.execute(
                f"SELECT {Document._COLUMNS} FROM document "
                "WHERE slug LIKE ? || '%' ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (prefix + "/", limit, offset),
            ).fetchall()
        else:
            rows = db.execute(
                f"SELECT {Document._COLUMNS} FROM document "
                "ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        docs = [Document._from_row(row) for row in rows]
        if not include_hidden:
            docs = [d for d in docs if not is_hidden_slug(d.slug)]
        return docs

    @staticmethod
    def count(prefix: str = "", include_hidden: bool = False) -> int:
        db = get_db()
        hidden_filter = "" if include_hidden else " AND slug NOT LIKE '%/.%'"
        if prefix:
            prefix = prefix.strip("/")
            row = db.execute(
                f"SELECT COUNT(*) FROM document WHERE slug LIKE ? || '%'{hidden_filter}",
                (prefix + "/",),
            ).fetchone()
        else:
            where = "" if include_hidden else " WHERE slug NOT LIKE '%/.%'"
            row = db.execute(f"SELECT COUNT(*) FROM document{where}").fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def list_folders(prefix: str = "", include_hidden: bool = False) -> list[str]:
        """List virtual folder names under a prefix."""
        db = get_db()
        if prefix:
            prefix = prefix.strip("/") + "/"
        # Get all slugs under prefix and extract the next path component
        rows = db.execute(
            "SELECT DISTINCT slug FROM document WHERE slug LIKE ?",
            (prefix + "%",),
        ).fetchall()

        folders: set[str] = set()
        for (slug_val,) in rows:
            remainder = str(slug_val)[len(prefix) :]
            if "/" in remainder:
                folder = remainder.split("/")[0]
                if not include_hidden and folder.startswith("."):
                    continue
                folders.add(folder)
        return sorted(folders)

    @property
    def is_markdown(self) -> bool:
        return self.mime_type == "text/markdown"

    @staticmethod
    def list_attachments(parent_slug: str) -> list[Document]:
        """List attachment documents under {parent_slug}/.att/."""
        db = get_db()
        att_prefix = f"{parent_slug}/.att/"
        rows = db.execute(
            f"SELECT {Document._COLUMNS} FROM document WHERE slug LIKE ? ORDER BY created_at ASC",
            (att_prefix + "%",),
        ).fetchall()
        return [Document._from_row(row) for row in rows]

    def get_blob(self) -> FileBlob | None:
        """Return the FileBlob linked via document_blob, or None."""
        from folio.models.file_blob import FileBlob

        db = get_db()
        row = db.execute(
            "SELECT fb.id, fb.sha256_hash, fb.file_size, fb.mime_type, fb.created_at "
            "FROM document_blob db "
            "JOIN file_blob fb ON fb.id = db.blob_id "
            "WHERE db.document_id = ?",
            (self.id,),
        ).fetchone()
        return FileBlob._from_row(row) if row else None

    @property
    def breadcrumbs(self) -> list[tuple[str, str]]:
        """Return list of (label, slug_prefix) for breadcrumb navigation."""
        parts = self.slug.split("/")
        crumbs: list[tuple[str, str]] = []
        for i, part in enumerate(parts[:-1]):
            prefix = "/".join(parts[: i + 1])
            crumbs.append((part, prefix))
        crumbs.append((parts[-1], self.slug))
        return crumbs
