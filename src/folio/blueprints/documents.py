"""Documents blueprint - CRUD, view, edit, history, diff, attachments."""

import hashlib
import io

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from markupsafe import Markup

from folio.blueprints.auth import get_username, login_required
from folio.db import transaction
from folio.models.document import Document, folio_slugify
from folio.models.document_version import DocumentVersion
from folio.models.document_watcher import DocumentWatcher
from folio.models.file_blob import FileBlob
from folio.models.tag import Tag
from folio.services import blob_service, extraction_service, search_service, version_service

bp = Blueprint("documents", __name__, url_prefix="/documents")


def is_htmx_request() -> bool:
    return request.headers.get("HX-Request") == "true"


def _get_doc_or_404(slug: str) -> Document:
    """Look up a document by slug or abort with 404."""
    doc = Document.get_by_slug(slug)
    if not doc:
        abort(404)
    assert doc is not None
    return doc


# ---------------------------------------------------------------------------
# Document listing and navigation
# ---------------------------------------------------------------------------


@bp.route("/")
@bp.route("/browse/")
@bp.route("/browse/<path:prefix>")
@login_required
def index(prefix: str = ""):
    """List documents and virtual folders under a prefix."""
    show_hidden = request.args.get("show_hidden") == "1"
    documents = Document.list_all(prefix=prefix, include_hidden=show_hidden)
    folders = Document.list_folders(prefix=prefix, include_hidden=show_hidden)

    # Filter documents to only show those directly in this folder
    if prefix:
        prefix_with_slash = prefix.strip("/") + "/"
        direct_docs = [d for d in documents if "/" not in d.slug[len(prefix_with_slash) :]]
    else:
        direct_docs = [d for d in documents if "/" not in d.slug]

    # Build breadcrumbs from prefix
    breadcrumbs: list[tuple[str, str]] = []
    if prefix:
        parts = prefix.strip("/").split("/")
        for i, part in enumerate(parts):
            crumb_prefix = "/".join(parts[: i + 1])
            breadcrumbs.append((part, crumb_prefix))

    return render_template(
        "documents/index.html",
        documents=direct_docs,
        folders=folders,
        prefix=prefix,
        breadcrumbs=breadcrumbs,
        show_hidden=show_hidden,
    )


# ---------------------------------------------------------------------------
# Create document
# ---------------------------------------------------------------------------


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    """Create a new markdown document."""
    parent_path = request.args.get("parent", "")

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("Title is required.", "error")
            return render_template("documents/new.html", parent_path=parent_path)

        raw_slug = request.form.get("slug", "").strip()
        slug = folio_slugify(raw_slug) if raw_slug else None
        username = get_username()

        doc = Document.create(
            title=title,
            created_by=username,
            content="",
            slug=slug,
            parent_path=parent_path,
        )

        # Create initial version
        DocumentVersion.create(
            document_id=doc.id,
            content="",
            author=username,
            message="Initial version",
        )

        # Index for search
        search_service.index_document(doc.id, doc.title, "")

        # Auto-watch creator
        DocumentWatcher.watch(doc.id, username)

        flash("Document created. You can now edit it below.", "success")
        return redirect(url_for("documents.edit", slug=doc.slug))

    return render_template("documents/new.html", parent_path=parent_path)


@bp.route("/upload-file", methods=["GET", "POST"])
@login_required
def upload_file():
    """Upload a file as a standalone document."""
    parent_path = request.args.get("parent", "")

    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            flash("No file selected.", "error")
            return render_template("documents/upload_file.html", parent_path=parent_path)

        max_size = current_app.config.get("MAX_UPLOAD_SIZE", 50 * 1024 * 1024)
        content = file.read()
        if len(content) > max_size:
            flash("File too large.", "error")
            return render_template("documents/upload_file.html", parent_path=parent_path)

        filename = file.filename
        title = request.form.get("title", "").strip() or filename
        mime_type = file.content_type or "application/octet-stream"
        username = get_username()

        custom_slug = request.form.get("slug", "").strip()
        if custom_slug:
            slug = folio_slugify(custom_slug) or Document.generate_slug(title, parent_path)
        else:
            slug = Document.generate_slug(title, parent_path)

        # If file is markdown, create a text document with content
        is_md = mime_type == "text/markdown" or filename.lower().endswith(".md")
        if is_md:
            text = content.decode("utf-8", errors="replace")
            doc = Document.create(
                title=title,
                created_by=username,
                content=text,
                mime_type="text/markdown",
                slug=slug,
            )
            DocumentVersion.create(
                document_id=doc.id,
                content=text,
                author=username,
                message="Uploaded file",
            )
            search_service.index_document(doc.id, doc.title, text)
            DocumentWatcher.watch(doc.id, username)
            flash("Markdown document created from file.", "success")
            return redirect(url_for("documents.view", slug=doc.slug))

        # Binary file — create document + blob
        extracted_text = extraction_service.extract_text(content, mime_type)
        doc = Document.create(
            title=title,
            created_by=username,
            content=extracted_text or None,
            mime_type=mime_type,
            slug=slug,
        )

        sha256_hash = hashlib.sha256(content).hexdigest()
        blob, created = FileBlob.get_or_create(sha256_hash, len(content), mime_type)
        if created:
            blob_path = blob_service.get_blob_path(sha256_hash)
            blob_path.parent.mkdir(parents=True, exist_ok=True)
            blob_path.write_bytes(content)

        with transaction() as cursor:
            cursor.execute(
                "INSERT INTO document_blob (document_id, blob_id) VALUES (?, ?)",
                (doc.id, blob.id),
            )

        search_service.index_document(doc.id, doc.title, extracted_text)
        DocumentWatcher.watch(doc.id, username)
        flash("File uploaded.", "success")
        return redirect(url_for("documents.view", slug=doc.slug))

    return render_template("documents/upload_file.html", parent_path=parent_path)


# ---------------------------------------------------------------------------
# View document
# ---------------------------------------------------------------------------


@bp.route("/raw/<path:slug>")
@login_required
def raw(slug: str):
    """Serve raw binary content for a document."""
    doc = _get_doc_or_404(slug)
    blob = doc.get_blob()
    if not blob:
        abort(404)
    assert blob is not None
    content = blob_service.get_blob_content(blob)
    if content is None:
        abort(404)
    assert content is not None
    return send_file(
        io.BytesIO(content),
        mimetype=blob.mime_type,
        as_attachment=False,
        download_name=doc.title,
    )


@bp.route("/view/<path:slug>")
@login_required
def view(slug: str):
    """View a document — info page for all types."""
    doc = _get_doc_or_404(slug)

    blob = doc.get_blob()
    version_count = DocumentVersion.count_for_document(doc.id)
    tags = Tag.get_for_document(doc.id)
    all_tags = Tag.get_all()
    attachments = Document.list_attachments(doc.slug)
    is_watching = DocumentWatcher.is_watching(doc.id, get_username())

    return render_template(
        "documents/view.html",
        document=doc,
        blob=blob,
        version_count=version_count,
        tags=tags,
        all_tags=all_tags,
        attachments=attachments,
        is_watching=is_watching,
    )


# ---------------------------------------------------------------------------
# Edit document
# ---------------------------------------------------------------------------


@bp.route("/edit/<path:slug>", methods=["GET", "POST"])
@login_required
def edit(slug: str):
    """Edit a markdown document."""
    doc = _get_doc_or_404(slug)
    if not doc.is_markdown:
        flash("Binary documents cannot be edited.", "error")
        return redirect(url_for("documents.view", slug=slug))

    if request.method == "POST":
        content = request.form.get("content", "")
        message = request.form.get("message", "").strip() or None
        title = request.form.get("title", "").strip()
        username = get_username()

        title_changed = bool(title and title != doc.title)
        content_changed = content != doc.current_content

        if title_changed:
            doc.update(title=title)

        if content_changed:
            version_service.save_version(
                document_id=doc.id,
                content=content,
                author=username,
                message=message,
            )

        if title_changed or content_changed:
            search_service.index_document(doc.id, doc.title, content)
            from folio.services import notification_service

            notification_service.notify_watchers(doc.id, username, doc.title, doc.slug)
            flash("Document saved.", "success")
        else:
            flash("No changes detected.", "info")

        return redirect(url_for("documents.view", slug=doc.slug))

    attachments = Document.list_attachments(doc.slug)
    return render_template("documents/edit.html", document=doc, attachments=attachments)


# ---------------------------------------------------------------------------
# History and diff
# ---------------------------------------------------------------------------


@bp.route("/history/<path:slug>")
@login_required
def history(slug: str):
    """View version history of a document."""
    doc = _get_doc_or_404(slug)
    versions = DocumentVersion.list_for_document(doc.id)
    return render_template(
        "documents/history.html",
        document=doc,
        versions=versions,
    )


@bp.route("/version/<path:slug>/<int:version_number>")
@login_required
def view_version(slug: str, version_number: int):
    """View a specific version of a document."""
    doc = _get_doc_or_404(slug)
    version = DocumentVersion.get_by_version_number(doc.id, version_number)
    if not version:
        abort(404)
    assert version is not None

    return render_template(
        "documents/view_version.html",
        document=doc,
        version=version,
    )


@bp.route("/diff/<path:slug>")
@login_required
def diff(slug: str):
    """Show diff between two versions."""
    doc = _get_doc_or_404(slug)

    from_v = request.args.get("from", type=int)
    to_v = request.args.get("to", type=int)

    if not from_v or not to_v:
        flash("Please select two versions to compare.", "error")
        return redirect(url_for("documents.history", slug=slug))

    diff_html = version_service.get_diff_between_versions(doc.id, from_v, to_v)
    if diff_html is None:
        flash("One or both versions not found.", "error")
        return redirect(url_for("documents.history", slug=slug))

    return render_template(
        "documents/diff.html",
        document=doc,
        from_version=from_v,
        to_version=to_v,
        diff_html=Markup(diff_html),
    )


@bp.route("/authors/<path:slug>")
@login_required
def authors(slug: str):
    """Show per-line authorship for a markdown document."""
    doc = _get_doc_or_404(slug)
    if not doc.is_markdown:
        flash("Authors view is only available for markdown documents.", "error")
        return redirect(url_for("documents.view", slug=slug))

    author_lines = version_service.compute_authors(doc.id)
    return render_template(
        "documents/authors.html",
        document=doc,
        author_lines=author_lines,
    )


# ---------------------------------------------------------------------------
# Delete document
# ---------------------------------------------------------------------------


@bp.route("/delete/<path:slug>", methods=["POST"])
@login_required
def delete(slug: str):
    """Delete a document and its attachment children."""
    doc = _get_doc_or_404(slug)
    username = get_username()

    # Notify watchers before deletion
    from folio.services import notification_service

    notification_service.notify_watchers(
        doc.id, username, doc.title, doc.slug, subject_prefix="[Deleted] "
    )

    # Delete attachment children first (no FK cascade from child slug to parent)
    for att_doc in Document.list_attachments(doc.slug):
        blob_service.delete_binary_document(att_doc)

    search_service.remove_from_index(doc.id)
    doc.delete()
    flash("Document deleted.", "success")
    return redirect(url_for("documents.index"))


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


@bp.route("/tags/<path:slug>/search")
@login_required
def tag_search(slug: str):
    """JSON endpoint for tom-select tag search."""
    doc = _get_doc_or_404(slug)
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])

    existing_ids = {t.id for t in Tag.get_for_document(doc.id)}
    results = Tag.search(q)
    filtered = [t for t in results if t.id not in existing_ids]

    return jsonify([{"id": t.id, "name": t.name, "color": t.color} for t in filtered])


@bp.route("/tags/<path:slug>", methods=["POST"])
@login_required
def tag_add(slug: str):
    """Add a tag to a document. Accepts tag_id or tag_name for new tags."""
    doc = _get_doc_or_404(slug)

    tag_id = request.form.get("tag_id", type=int)
    tag_name = request.form.get("tag_name", "").strip()

    if tag_id:
        tag = Tag.get_by_id(tag_id)
    elif tag_name:
        tag = Tag.get_or_create(tag_name)
    else:
        if is_htmx_request():
            return "", 400
        flash("No tag specified.", "error")
        return redirect(url_for("documents.view", slug=slug))

    if tag:
        Tag.add_to_document(doc.id, tag.id)
        _reindex_tags(doc)

    if is_htmx_request():
        tags = Tag.get_for_document(doc.id)
        all_tags = Tag.get_all()
        return render_template("documents/_tags.html", document=doc, tags=tags, all_tags=all_tags)

    return redirect(url_for("documents.view", slug=slug))


@bp.route("/tags/<path:slug>/<int:tag_id>/remove", methods=["POST"])
@login_required
def tag_remove(slug: str, tag_id: int):
    """Remove a tag from a document."""
    doc = _get_doc_or_404(slug)
    Tag.remove_from_document(doc.id, tag_id)
    _reindex_tags(doc)

    if is_htmx_request():
        tags = Tag.get_for_document(doc.id)
        all_tags = Tag.get_all()
        return render_template("documents/_tags.html", document=doc, tags=tags, all_tags=all_tags)

    return redirect(url_for("documents.view", slug=slug))


def _reindex_tags(doc: Document) -> None:
    """Re-index a document's FTS entry with updated tags."""
    tags = Tag.get_for_document(doc.id)
    tags_text = " ".join(t.name for t in tags)
    content = doc.current_content or ""
    search_service.index_document(doc.id, doc.title, content, tags_text)


# ---------------------------------------------------------------------------
# Watching
# ---------------------------------------------------------------------------


@bp.route("/watch/<path:slug>", methods=["POST"])
@login_required
def watch(slug: str):
    """Watch a document."""
    doc = _get_doc_or_404(slug)
    DocumentWatcher.watch(doc.id, get_username())
    flash("You are now watching this document.", "success")
    return redirect(url_for("documents.view", slug=slug))


@bp.route("/unwatch/<path:slug>", methods=["POST"])
@login_required
def unwatch(slug: str):
    """Unwatch a document."""
    doc = _get_doc_or_404(slug)
    DocumentWatcher.unwatch(doc.id, get_username())
    flash("You are no longer watching this document.", "success")
    return redirect(url_for("documents.view", slug=slug))


# ---------------------------------------------------------------------------
# Attachments / Image upload
# ---------------------------------------------------------------------------


@bp.route("/upload/<path:slug>", methods=["POST"])
@login_required
def upload_attachment(slug: str):
    """Upload an attachment to a document."""
    doc = _get_doc_or_404(slug)

    file = request.files.get("file")
    if not file or not file.filename:
        if is_htmx_request():
            return '{"error": "No file selected"}', 400
        flash("No file selected.", "error")
        return redirect(url_for("documents.edit", slug=slug))

    max_size = current_app.config.get("MAX_UPLOAD_SIZE", 50 * 1024 * 1024)
    content = file.read()
    if len(content) > max_size:
        if is_htmx_request():
            return '{"error": "File too large"}', 413
        flash("File too large.", "error")
        return redirect(url_for("documents.edit", slug=slug))
    file.seek(0)

    username = get_username()
    att_doc = blob_service.save_uploaded_file(file, doc, username)

    # Return JSON for Vditor image upload callback (XHR from editor)
    is_xhr = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if is_htmx_request() or is_xhr:
        image_url = url_for("documents.raw", slug=att_doc.slug)
        return {
            "msg": "",
            "code": 0,
            "data": {
                "errFiles": [],
                "succMap": {
                    att_doc.title: image_url,
                },
            },
        }

    flash("File uploaded.", "success")
    return redirect(url_for("documents.edit", slug=slug))


@bp.route("/attachment/<int:attachment_id>")
@login_required
def serve_attachment(attachment_id: int):
    """Backward-compat redirect for old attachment URLs."""
    from folio.db import get_db

    db = get_db()
    # Look up the old attachment row to find its parent doc and filename,
    # then redirect to the new document-based URL.
    row = db.execute(
        "SELECT a.filename, d.slug FROM attachment a "
        "JOIN document d ON d.id = a.document_id "
        "WHERE a.id = ?",
        (attachment_id,),
    ).fetchone()
    if row:
        filename, parent_slug = str(row[0]), str(row[1])
        new_slug = f"{parent_slug}/.att/{filename}"
        new_doc = Document.get_by_slug(new_slug)
        if new_doc:
            return redirect(url_for("documents.raw", slug=new_doc.slug), code=301)
    abort(404)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@bp.route("/search")
@login_required
def search():
    """Search documents."""
    query = request.args.get("q", "").strip()
    mime_type = request.args.get("type", "").strip() or None
    tag = request.args.get("tag", "").strip() or None
    date_from = request.args.get("date_from", "").strip() or None
    date_to = request.args.get("date_to", "").strip() or None

    results: list[dict] = []
    if query:
        results = search_service.search(
            query, mime_type=mime_type, tag=tag, date_from=date_from, date_to=date_to
        )

    facets = search_service.get_search_facets()

    return render_template(
        "search/results.html",
        query=query,
        results=results,
        facets=facets,
        active_type=mime_type or "",
        active_tag=tag or "",
        active_date_from=date_from or "",
        active_date_to=date_to or "",
    )
