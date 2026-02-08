-- Folio Database Schema
-- All datetimes stored as ISO 8601 UTC strings

PRAGMA foreign_keys = ON;

-- Database metadata for versioning
CREATE TABLE IF NOT EXISTS db_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO db_metadata (key, value) VALUES ('schema_version', '2');

-- Application settings
CREATE TABLE IF NOT EXISTS app_setting (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT
);

-- Documents
CREATE TABLE IF NOT EXISTS document (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    mime_type TEXT NOT NULL DEFAULT 'text/markdown',
    current_content TEXT,
    created_by TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_document_slug ON document(slug);
CREATE INDEX IF NOT EXISTS idx_document_updated ON document(updated_at);
CREATE INDEX IF NOT EXISTS idx_document_created_by ON document(created_by);

-- Version history
CREATE TABLE IF NOT EXISTS document_version (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    version_number INTEGER NOT NULL,
    content TEXT NOT NULL,
    author TEXT NOT NULL,
    message TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES document(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_version_document ON document_version(document_id);
CREATE INDEX IF NOT EXISTS idx_version_number ON document_version(document_id, version_number);

-- File blobs (deduplicated storage)
-- Path derived from hash: {BLOB_DIRECTORY}/{hash[:2]}/{hash}
CREATE TABLE IF NOT EXISTS file_blob (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256_hash TEXT UNIQUE NOT NULL,
    file_size INTEGER NOT NULL,
    mime_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_file_blob_hash ON file_blob(sha256_hash);

-- Binary documents link to their blob
CREATE TABLE IF NOT EXISTS document_blob (
    document_id INTEGER NOT NULL,
    blob_id INTEGER NOT NULL,
    PRIMARY KEY (document_id, blob_id),
    FOREIGN KEY (document_id) REFERENCES document(id) ON DELETE CASCADE,
    FOREIGN KEY (blob_id) REFERENCES file_blob(id) ON DELETE RESTRICT
);

-- Tags
CREATE TABLE IF NOT EXISTS tag (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    color TEXT NOT NULL DEFAULT '#3b82f6',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tag_name ON tag(name);

-- Document-Tag junction table
CREATE TABLE IF NOT EXISTS document_tag (
    document_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (document_id, tag_id),
    FOREIGN KEY (document_id) REFERENCES document(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tag(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_document_tag_document ON document_tag(document_id);
CREATE INDEX IF NOT EXISTS idx_document_tag_tag ON document_tag(tag_id);

-- Watching / notifications
CREATE TABLE IF NOT EXISTS document_watcher (
    document_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (document_id, username),
    FOREIGN KEY (document_id) REFERENCES document(id) ON DELETE CASCADE
);

-- Full-text search index
CREATE VIRTUAL TABLE IF NOT EXISTS document_fts USING fts5(
    title,
    content_text,
    tags_text,
    content='',
    tokenize='porter unicode61'
);

-- Default app settings
INSERT OR IGNORE INTO app_setting (key, value, description) VALUES
    ('gatekeeper.db_path', '', 'Path to Gatekeeper SQLite database'),
    ('gatekeeper.cookie_name', 'folio_session', 'Cookie name for Gatekeeper auth');
