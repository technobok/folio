# Folio - Implementation Roadmap

## Overview
Self-hosted document management system with versioning and search. Built with Python, Flask, HTMX, and SQLite (via APSW).

---

## Implementation Phases

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
- [x] Table of contents generation (tocbot sidebar with scroll-following and active section highlighting)
- [x] FTS5 full-text search with result snippets
- [x] Tag model and document-tag association (data layer ready, UI in Phase 3)
- [x] Admin CLI (init-db, config get/set/list)
- [x] 8 passing tests covering CRUD, search, tags, and hierarchical slugs
- [x] Clean type checking (ty) and formatting (ruff)

### Phase 2 - Search and Binary Documents

Extend search to cover binary documents and improve the search experience.

- [x] Binary document upload with type detection and inline preview (image, PDF, video, audio)
- [x] Text extraction pipeline: PyMuPDF (PDF), python-docx (Word), openpyxl (Excel), email.parser (email)
- [x] Index extracted text in FTS5 alongside markdown content
- [x] Search result snippets with keyword highlighting (content-backed FTS table)
- [x] Faceted search filtering by type/tag/date
- [x] Search result ranking via FTS5 relevance ordering

### Phase 3 - Organisation and Collaboration

Add the collaboration features that make Folio useful for teams.

- [x] Tag management UI (create, edit, delete tags; assign to documents; filter by tag)
- [x] Document watching (subscribe to changes on specific documents)
- [x] Email notifications via Outbox when watched documents change
- [x] Blame view (walk version history to attribute lines to authors via `difflib`)
- [x] Document metadata display (creation date, author, version count, tags in document header)
- [x] Recent changes feed / activity log

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
