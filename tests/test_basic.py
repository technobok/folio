"""Basic tests for the Folio application."""

import tempfile
from pathlib import Path

import pytest

from folio import create_app
from folio.db import init_db_at


@pytest.fixture
def app():
    db_fd = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    db_path = db_fd.name
    db_fd.close()

    init_db_at(db_path)

    app = create_app(
        test_config={
            "DATABASE_PATH": db_path,
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "BLOBS_DIRECTORY": str(Path(db_path).parent / "blobs"),
        }
    )

    yield app

    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def client(app):
    return app.test_client()


def test_index_redirects_to_login(client):
    """Unauthenticated users should see the index page."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"Folio" in response.data


def test_documents_requires_auth(client):
    """Documents page should redirect to login."""
    response = client.get("/documents/")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_login_page(client):
    """Login page should load."""
    response = client.get("/auth/login")
    assert response.status_code == 200


def test_document_crud(app):
    """Test document creation, update, and deletion."""
    with app.app_context():
        from folio.models.document import Document
        from folio.models.document_version import DocumentVersion

        doc = Document.create(
            title="Test Doc",
            created_by="tester",
            content="# Test\n\nHello.",
        )
        assert doc.id > 0
        assert doc.slug == "test-doc"

        # Version
        v = DocumentVersion.create(
            document_id=doc.id,
            content="# Test\n\nHello.",
            author="tester",
            message="Initial",
        )
        assert v.version_number == 1

        # Update
        doc.update(title="Updated Doc")
        reloaded = Document.get_by_id(doc.id)
        assert reloaded.title == "Updated Doc"

        # List
        docs = Document.list_all()
        assert len(docs) >= 1

        # Delete
        doc.delete()
        assert Document.get_by_id(doc.id) is None


def test_hierarchical_slugs(app):
    """Test hierarchical slug generation."""
    with app.app_context():
        from folio.models.document import Document

        doc = Document.create(
            title="Design Spec",
            created_by="tester",
            parent_path="projects/folio",
        )
        assert doc.slug == "projects/folio/design-spec"

        folders = Document.list_folders()
        assert "projects" in folders

        doc.delete()


def test_search(app):
    """Test FTS5 search."""
    with app.app_context():
        from folio.models.document import Document
        from folio.services import search_service

        doc = Document.create(
            title="Searchable Doc",
            created_by="tester",
            content="This document contains unique-keyword-xyz for testing.",
        )
        search_service.index_document(doc.id, doc.title, doc.current_content or "")

        results = search_service.search("unique-keyword-xyz")
        assert len(results) == 1
        assert results[0]["title"] == "Searchable Doc"

        doc.delete()


def test_folio_slugify():
    """Test custom slugify preserves dots and leading dots."""
    from folio.models.document import folio_slugify

    assert folio_slugify("photo.png") == "photo.png"
    assert folio_slugify(".hidden") == ".hidden"
    assert folio_slugify("Hello World") == "hello-world"
    assert folio_slugify("") == ""
    assert folio_slugify("!!!") == ""
    assert folio_slugify("  Spaced  Out  ") == "spaced-out"
    assert folio_slugify("café") == "cafe"
    assert folio_slugify("my--file---name") == "my-file-name"
    assert folio_slugify("file  name.tar.gz") == "file-name.tar.gz"


def test_tags(app):
    """Test tag creation and association."""
    with app.app_context():
        from folio.models.document import Document
        from folio.models.tag import Tag

        doc = Document.create(title="Tagged Doc", created_by="tester")
        tag = Tag.create("urgent", "#ef4444")

        Tag.add_to_document(doc.id, tag.id)
        tags = Tag.get_for_document(doc.id)
        assert len(tags) == 1
        assert tags[0].name == "urgent"

        Tag.remove_from_document(doc.id, tag.id)
        tags = Tag.get_for_document(doc.id)
        assert len(tags) == 0

        doc.delete()
        tag.delete()
