"""Documents blueprint - CRUD, view, edit, history, diff, attachments."""

import hashlib
import io
import re

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
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
from folio.models.file_blob import FileBlob
from folio.models.tag import Tag
from folio.services import blob_service, search_service, version_service

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
        content = request.form.get("content", "")
        username = get_username()

        doc = Document.create(
            title=title,
            created_by=username,
            content=content,
            slug=slug,
            parent_path=parent_path,
        )

        # Create initial version
        DocumentVersion.create(
            document_id=doc.id,
            content=content,
            author=username,
            message="Initial version",
        )

        # Index for search
        search_service.index_document(doc.id, doc.title, content)

        flash("Document created.", "success")
        return redirect(url_for("documents.view", slug=doc.slug))

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
            flash("Markdown document created from file.", "success")
            return redirect(url_for("documents.view", slug=doc.slug))

        # Binary file — create document + blob
        doc = Document.create(
            title=title,
            created_by=username,
            content=None,
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

    # Attachment slugs (/.att/) redirect to raw for backward compat with
    # embedded image URLs in markdown content.
    blob = doc.get_blob()
    if blob and "/.att/" in slug:
        return redirect(url_for("documents.raw", slug=slug))

    version_count = DocumentVersion.count_for_document(doc.id)
    tags = Tag.get_for_document(doc.id)
    attachments = Document.list_attachments(doc.slug)

    # Generate TOC from headings if markdown
    toc_items: list[dict] = []
    if doc.is_markdown and doc.current_content:
        toc_items = _extract_toc(doc.current_content)

    return render_template(
        "documents/view.html",
        document=doc,
        blob=blob,
        version_count=version_count,
        tags=tags,
        attachments=attachments,
        toc_items=toc_items,
    )


def _extract_toc(markdown_text: str) -> list[dict]:
    """Extract headings from markdown for table of contents."""
    toc: list[dict] = []
    for line in markdown_text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if match:
            level = len(match.group(1))
            title = match.group(2).strip()
            anchor = re.sub(r"[^\w\s-]", "", title.lower())
            anchor = re.sub(r"[-\s]+", "-", anchor).strip("-")
            toc.append({"level": level, "title": title, "anchor": anchor})
    return toc


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

        # Capture old values before any mutations (needed for FTS update)
        old_title = doc.title
        old_content = doc.current_content or ""

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
            search_service.index_document(
                doc.id, doc.title, content, old_title=old_title, old_content=old_content
            )
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


# ---------------------------------------------------------------------------
# Delete document
# ---------------------------------------------------------------------------


@bp.route("/delete/<path:slug>", methods=["POST"])
@login_required
def delete(slug: str):
    """Delete a document and its attachment children."""
    doc = _get_doc_or_404(slug)

    # Delete attachment children first (no FK cascade from child slug to parent)
    for att_doc in Document.list_attachments(doc.slug):
        blob_service.delete_binary_document(att_doc)

    search_service.remove_from_index(doc.id, doc.title, doc.current_content or "")
    doc.delete()
    flash("Document deleted.", "success")
    return redirect(url_for("documents.index"))


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
    results: list[dict] = []
    if query:
        results = search_service.search(query)

    return render_template(
        "search/results.html",
        query=query,
        results=results,
    )
