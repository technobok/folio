# Folio

A self-hosted document management system for storing, editing, versioning, and searching documents. Built for small teams and personal use, Folio prioritises simplicity and operational ease over feature sprawl.

## What It Does

- **Write and version markdown documents** with a WYSIWYG editor, full version history, and side-by-side diffs
- **Organise documents hierarchically** using wiki-style slugs (`projects/alpha/meeting-notes`)
- **Search everything** via SQLite FTS5 full-text search
- **Upload and store binary files** (PDFs, images, attachments) with SHA256-deduplicated blob storage
- **Tag documents** with colour-coded labels
- **Authenticate via Gatekeeper** (shared auth infrastructure) with magic-link login

## Quickstart

### Prerequisites

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) package manager
- A [Gatekeeper](../gatekeeper/) instance (for authentication)

### Setup

```bash
cd /path/to/folio

# Install dependencies
make sync

# Initialise the database
make init-db

# Point Folio at your Gatekeeper database
make config-set KEY=gatekeeper.db_path VAL=/path/to/gatekeeper/instance/gatekeeper.sqlite3

# Start the development server
make rundev
```

Open http://127.0.0.1:5001 and log in with any user registered in Gatekeeper.

### Database location

By default the database is created at `instance/folio.sqlite3` relative to the project root. Set the `FOLIO_DB` environment variable to override:

```bash
export FOLIO_DB=/data/folio.sqlite3
```

The resolution order is:

1. `FOLIO_DB` environment variable (if set)
2. Flask `DATABASE_PATH` config (when running inside the web server)
3. `instance/folio.sqlite3` relative to the source tree (fallback)

All CLI commands (`folio-admin`, `make config-*`, `make init-db`) and the web server use the same resolution logic — set `FOLIO_DB` once and everything finds the database.

### Production

```bash
make run
```

This runs gunicorn on 0.0.0.0:5001. Put nginx or Caddy in front for TLS.

## Makefile reference

| Target | Description |
|---|---|
| `make sync` | Install/sync dependencies with uv |
| `make init-db` | Create a blank database |
| `make run` | Start production server (gunicorn, 0.0.0.0:5001) |
| `make rundev` | Start development server (Flask debug mode) |
| `make config-list` | Show all configuration settings |
| `make config-set KEY=... VAL=...` | Set a configuration value |
| `make config-export FILE=...` | Export all settings as a shell script |
| `make check` | Run ruff (format + lint) and ty (type check) |
| `make clean` | Remove bytecode and the database file |

## CLI commands

The `folio-admin` CLI provides the same operations outside of Make:

```
folio-admin init-db              # Initialize the database schema
folio-admin config list          # Show settings
folio-admin config get KEY       # Get a single setting
folio-admin config set KEY VAL   # Set a setting
folio-admin config export FILE   # Export all settings as a shell script
```

## Configuration reference

All settings are stored in the SQLite database (`app_setting` table) and managed via `make config-set` or `folio-admin config set`. Use `make config-list` to see current values.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `server.host` | string | `0.0.0.0` | Bind address for production server |
| `server.port` | int | `5001` | Port for production server |
| `server.dev_host` | string | `127.0.0.1` | Bind address for dev server |
| `server.dev_port` | int | `5001` | Port for dev server |
| `server.debug` | bool | `false` | Enable Flask debug mode |
| `gatekeeper.db_path` | string | | Path to Gatekeeper SQLite database (required for login) |
| `gatekeeper.cookie_name` | string | `folio_session` | Auth cookie name |
| `uploads.max_size_mb` | int | `50` | Maximum upload size in MB |
| `blobs.directory` | string | `instance/blobs` | Blob storage directory |
| `proxy.x_forwarded_for` | int | `0` | Trust X-Forwarded-For (hop count) |
| `proxy.x_forwarded_proto` | int | `0` | Trust X-Forwarded-Proto (hop count) |
| `proxy.x_forwarded_host` | int | `0` | Trust X-Forwarded-Host (hop count) |
| `proxy.x_forwarded_prefix` | int | `0` | Trust X-Forwarded-Prefix (hop count) |

## Project Structure

```
folio/
  pyproject.toml
  database/
    schema.sql                  # Full schema (11 tables + FTS5 virtual table)
  src/folio/
    __init__.py                 # App factory (Flask, mistune, Jinja filters)
    db.py                       # APSW connection management + transactions
    config.py                   # Typed configuration registry
    web.py                      # Web server entry point (dev + gunicorn)
    cli.py                      # Admin CLI (init-db, config management)
    models/
      document.py               # Document with hierarchical slugs
      document_version.py       # Version history rows
      attachment.py             # FileBlob (SHA256 dedup) + Attachment
      tag.py                    # Tags with colour support
    blueprints/
      auth.py                   # Gatekeeper magic-link authentication
      documents.py              # Document CRUD, history, diff, search, upload
    services/
      version_service.py        # Diff computation via difflib
      blob_service.py           # Hash-addressed file storage
      search_service.py         # FTS5 full-text search
    templates/                  # 12 Jinja2 templates
    static/
      css/app.css               # PicoCSS compact theme + Folio styles
      js/app.js                 # Theme toggle, flash auto-dismiss, timezone
      vendor/                   # pico.min.css, htmx.min.js
  tests/
    test_basic.py               # 7 tests covering CRUD, search, tags, slugs
```

## Architecture Decisions

### Why SQLite versioning instead of git

The original design called for an embedded git repository to track document versions. This was rejected as over-engineered:

- **Attributing commits to web app users** requires programmatic git operations that are fragile and hard to debug.
- **Concurrent edits** in a single git repo need locking or branch-per-user schemes, adding operational complexity.
- **Blame and diff** are straightforward to compute from version rows using Python's `difflib`, without any git dependency.
- **Backup is simpler**: just back up the database file + blob directory. No `.git` directory to manage.

Instead, each save creates a row in `document_version` with content, author, timestamp, and optional edit message. Diffs are computed on-demand. This gives all the requested features (history, diffs, user attribution) with a fraction of the complexity.

### Why APSW over sqlite3

APSW (Another Python SQLite Wrapper) provides direct access to SQLite's C API, giving us:

- Native FTS5 support without workarounds
- Proper WAL mode and busy timeout configuration
- Better threading behaviour
- Identical to what Cadence uses, so patterns are proven

### Why Vditor for the markdown editor

The app is HTMX/server-rendered with no JavaScript build step, so the editor must work as a vanilla `<script>` tag include. This eliminates bundler-dependent options (Milkdown, Tiptap).

Of the remaining options:

- **EasyMDE**: Simpler but abandoned (fork of dead SimpleMDE), no WYSIWYG mode.
- **Toast UI Editor**: Good but heavier; Vditor covers the same ground.
- **StackEdit.js**: Abandoned (last release 2019), iframe-based.

**Vditor** was chosen because it is actively maintained, provides three editing modes (WYSIWYG, split-pane, source), handles image uploads natively, generates table-of-contents outlines, supports GFM, and works via CDN with no build step. It is Chinese-origin but fully localisable to English via `lang: 'en_US'`.

### Why GitHub Flavoured Markdown

GFM (via mistune 3.x with `strikethrough`, `table`, `task_lists`, and `url` plugins) is what most people expect when they hear "markdown". It covers tables, task lists, strikethrough, and autolinks without needing a separate spec.

AsciiDoc was considered and rejected: the Ruby toolchain dependency is operationally painful, and GFM covers the practical use case.

### Why hierarchical slugs instead of folders

Documents are organised by hierarchical slug paths (e.g. `projects/alpha/meeting-notes`) rather than a separate folder table. This means:

- **No folder CRUD**: "folders" are virtual, derived from slug prefixes. Creating a document under `projects/alpha/` implicitly creates the folder structure.
- **Stable URLs**: `/documents/view/projects/alpha/meeting-notes` is both a permanent link and encodes the hierarchy.
- **Simple moves**: Renaming a slug moves a document between folders.
- **Breadcrumb navigation**: Derived from splitting the slug on `/`.

Slugs are auto-generated from titles via `python-slugify` with manual override. Collisions get `-2`, `-3` suffixes.

### Why Gatekeeper for auth (not built-in)

Folio delegates all user management and authentication to Gatekeeper, a shared auth service already running in the infrastructure. This avoids:

- Reimplementing user registration, password hashing, email verification
- Managing a separate user database
- Duplicating the magic-link login flow

Folio's auth blueprint sends magic-link requests to Gatekeeper and verifies the returned tokens. User identity comes from the Gatekeeper cookie. If Gatekeeper is not configured, the login page says so rather than failing silently.

### Access control: deliberately simple

All authenticated users can read and write all documents. There is no per-document ACL in Phase 1. This matches the intended use case (small trusted team / personal use) and avoids the complexity of permission systems that are rarely needed but always expensive to build.

Gatekeeper group-based access control is reserved for a future phase if needed.

### Stack choices inherited from Cadence

Folio deliberately reuses the same technology stack as [Cadence](../cadence/) (a task and issue tracker in the same infrastructure):

| Component | Choice | Shared with Cadence |
|-----------|--------|:-------------------:|
| Backend framework | Flask | Yes |
| Database | SQLite via APSW | Yes |
| Frontend | HTMX + PicoCSS (compact theme) | Yes |
| Markdown rendering | mistune 3.x (server-side) | Yes |
| Blob storage | SHA256 hash-addressed files | Yes |
| Auth | Gatekeeper client | Yes |
| Dark/light mode toggle | CSS + JS (same implementation) | Yes |
| Package manager | uv | Yes |

This means one set of patterns to learn, consistent look-and-feel across apps, and copy-paste code reuse.

### Hash-addressed blob storage

Binary files (images, PDFs, attachments) are stored on disk at `{BLOBS_DIR}/{sha256[:2]}/{sha256}`. The `file_blob` table tracks hash, size, and mime type. Multiple attachments referencing the same content share one blob file. Blobs are only deleted from disk when zero attachments reference them.

This is the same deduplication pattern Cadence uses for task attachments.

### No integration with Cadence

Folio and Cadence are independent systems. If you need to reference a Cadence task from a Folio document, use a hyperlink. This keeps both systems simple and independently deployable.

## Development

```bash
make sync          # Install with dev dependencies
make check         # Format, lint, and type check
make rundev        # Run dev server (127.0.0.1:5001, debug mode)

# Run tests
.venv/bin/pytest tests/ -v
```

## Roadmap

### Phase 1 - MVP (done)

Core document management, delivered and working.

- [x] Project scaffolding (pyproject.toml, uv, app factory, database init)
- [x] PicoCSS compact theme with dark/light mode toggle (adapted from Cadence)
- [x] Database schema (11 tables + FTS5 virtual table)
- [x] Gatekeeper authentication integration (magic-link login)
- [x] Markdown document CRUD (create, list, view rendered, edit with Vditor)
- [x] Hierarchical slug-based organisation with virtual folders and breadcrumbs
- [x] Document versioning (save creates version row, view history, view old versions)
- [x] Diff view between versions (HTML table diff via `difflib`)
- [x] Image/attachment upload with SHA256-deduplicated blob storage
- [x] Vditor editor with inline image upload support
- [x] Table of contents generation (sidebar on document view from heading extraction)
- [x] FTS5 full-text search with result snippets
- [x] Tag model and document-tag association (data layer ready, UI in Phase 3)
- [x] Admin CLI (init-db, config get/set/list)
- [x] 7 passing tests covering CRUD, search, tags, and hierarchical slugs
- [x] Clean type checking (ty) and formatting (ruff)

### Phase 2 - Search and Binary Documents

Extend search to cover binary documents and improve the search experience.

- [ ] Binary document upload (PDF, Word, Excel, email) with type detection
- [ ] Text extraction pipeline: PyMuPDF (PDF), python-docx (Word), openpyxl (Excel), email.parser (email)
- [ ] Index extracted text in FTS5 alongside markdown content
- [ ] Search UI improvements: result highlighting, faceted filtering by type/tag/date
- [ ] Search result ranking tuning

### Phase 3 - Organisation and Collaboration

Add the collaboration features that make Folio useful for teams.

- [ ] Tag management UI (create, edit, delete tags; assign to documents; filter by tag)
- [ ] Document watching (subscribe to changes on specific documents)
- [ ] Email notifications via Outbox when watched documents change
- [ ] Blame view (walk version history to attribute lines to authors via `difflib`)
- [ ] Document metadata sidebar (creation date, author, version count, tags, watchers)
- [ ] Recent changes feed / activity log

### Phase 4 - Polish and Operations

Production hardening and administrative tools.

- [ ] Admin dashboard (document statistics, storage usage, user activity)
- [ ] SQLite database backup (APSW online backup API, scheduled or on-demand)
- [ ] Blob directory backup tooling
- [ ] Access control via Gatekeeper groups (restrict documents to specific groups)
- [ ] Document templates (predefined markdown scaffolds for common document types)
- [ ] Export (download document as .md file, export all as zip)
- [ ] Print-friendly CSS for document view

### Ideas (not scheduled)

- **Mermaid diagram rendering** in markdown (via mermaid.js CDN)
- **Document linking / backlinks** (detect `[[wiki-style]]` links between documents)
- **Revision restore** (revert to a previous version with one click)
- **Collaborative editing indicators** (show who else is editing, no real-time sync)
- **Webhook notifications** on document changes
- **API** (JSON endpoints for programmatic document access)
- **Import from files** (bulk import `.md` files from a directory, preserving structure)
- **Syntax highlighting** in code blocks (via highlight.js or Prism CDN)
