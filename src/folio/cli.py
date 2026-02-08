"""CLI entry point for folio-admin."""

import os
import stat
import sys
from datetime import UTC, datetime

import click

from folio.config import REGISTRY, parse_value, resolve_entry, serialize_value
from folio.db import (
    close_standalone_db,
    get_db_path,
    get_standalone_db,
    init_db_at,
    standalone_transaction,
)


def _make_app():
    """Create a Flask app for commands that need app context."""
    from folio import create_app

    return create_app()


def _db_get(key: str) -> str | None:
    db = get_standalone_db()
    row = db.execute("SELECT value FROM app_setting WHERE key = ?", (key,)).fetchone()
    return str(row[0]) if row else None


def _db_get_all() -> dict[str, str]:
    db = get_standalone_db()
    rows = db.execute("SELECT key, value FROM app_setting ORDER BY key").fetchall()
    return {str(r[0]): str(r[1]) for r in rows}


def _db_set(key: str, value: str) -> None:
    with standalone_transaction() as cursor:
        cursor.execute(
            "INSERT INTO app_setting (key, value, description) VALUES (?, ?, '') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


@click.group()
def main():
    """Folio administration tool."""


# ---- config group --------------------------------------------------------


@main.group()
def config():
    """View and manage configuration settings."""


@config.command("list")
def config_list():
    """Show all settings with their effective values."""
    db_values = _db_get_all()

    current_group = ""
    for entry in REGISTRY:
        group = entry.key.split(".")[0]
        if group != current_group:
            if current_group:
                click.echo()
            click.echo(click.style(f"[{group}]", bold=True))
            current_group = group

        raw = db_values.get(entry.key)
        if raw is not None:
            value = raw
            source = "db"
        else:
            value = serialize_value(entry, entry.default)
            source = "default"

        if entry.secret and raw is not None:
            display = "********"
        else:
            display = value if value else "(empty)"

        source_tag = click.style(f"[{source}]", fg="cyan" if source == "db" else "yellow")
        click.echo(f"  {entry.key} = {display}  {source_tag}")
        click.echo(click.style(f"    {entry.description}", dim=True))

    close_standalone_db()


@config.command("get")
@click.argument("key")
def config_get(key: str):
    """Get the effective value of a setting."""
    entry = resolve_entry(key)
    if not entry:
        click.echo(f"Unknown setting: {key}", err=True)
        sys.exit(1)
    assert entry is not None

    raw = _db_get(key)
    if raw is not None:
        value = parse_value(entry, raw)
    else:
        value = entry.default

    if entry.secret and raw is not None:
        click.echo("********")
    elif isinstance(value, bool):
        click.echo("true" if value else "false")
    else:
        click.echo(value if value else "(empty)")

    close_standalone_db()


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str):
    """Set a configuration value in the database."""
    entry = resolve_entry(key)
    if not entry:
        click.echo(f"Unknown setting: {key}", err=True)
        sys.exit(1)
    assert entry is not None

    try:
        parse_value(entry, value)
    except (ValueError, TypeError) as exc:
        click.echo(f"Invalid value for {key} ({entry.type.value}): {exc}", err=True)
        sys.exit(1)

    _db_set(key, value)
    click.echo(f"{key} = {value}")
    close_standalone_db()


@config.command("export")
@click.argument("output_file", type=click.Path())
def config_export(output_file: str):
    """Export all settings as a shell script of make config-set calls."""
    db_values = _db_get_all()
    lines = [
        "#!/bin/bash",
        "# Configuration export for Folio",
        f"# Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
    ]

    for entry in REGISTRY:
        raw = db_values.get(entry.key)
        if raw is not None:
            value = raw
            lines.append(f"make config-set KEY={entry.key} VAL='{value}'")
        else:
            value = serialize_value(entry, entry.default)
            lines.append(f"# default: {entry.key}")
            lines.append(f"# make config-set KEY={entry.key} VAL='{value}'")

    with open(output_file, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(output_file, os.stat(output_file).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    click.echo(f"Exported {len(REGISTRY)} settings to {output_file}")
    close_standalone_db()


# ---- admin commands ------------------------------------------------------


@main.command("init-db")
def init_db_command():
    """Initialize the database schema."""
    db_path = get_db_path()
    init_db_at(db_path)
    click.echo(f"Database initialized at {db_path}")


@main.command("rebuild-index")
def rebuild_index_command():
    """Drop and rebuild the full-text search index."""
    app = _make_app()
    with app.app_context():
        from folio.services import search_service

        count = search_service.rebuild_index()
        click.echo(f"Rebuilt FTS index: {count} documents indexed.")


@main.command("migrate-schema")
def migrate_schema_command():
    """Migrate database schema to latest version (currently v3).

    Recreates the FTS index as a regular (non-contentless) table.
    After migrating, run `folio-admin rebuild-index` to populate it.
    """
    app = _make_app()
    with app.app_context():
        from folio.db import get_db

        db = get_db()
        row = db.execute(
            "SELECT value FROM db_metadata WHERE key = 'schema_version'"
        ).fetchone()
        version = str(row[0]) if row else "1"

        if int(version) >= 3:
            click.echo(f"Schema already at version {version}, nothing to do.")
            return

        click.echo(f"Migrating schema from version {version} to 3...")

        # v2 → v3: switch FTS from contentless to regular
        db.execute("DROP TABLE IF EXISTS document_fts")
        db.execute(
            "CREATE VIRTUAL TABLE document_fts USING fts5("
            "title, content_text, tags_text, tokenize='porter unicode61')"
        )
        db.execute(
            "INSERT OR REPLACE INTO db_metadata (key, value) VALUES ('schema_version', '3')"
        )

        click.echo("Schema migrated to version 3.")
        click.echo("Run `folio-admin rebuild-index` to populate the search index.")


@main.command("migrate-attachments")
def migrate_attachments_command():
    """Migrate attachment rows to document-based attachments (one-time)."""
    app = _make_app()
    with app.app_context():
        from folio.services import migration_service

        count = migration_service.migrate_attachments()
        if count:
            click.echo(f"Migrated {count} attachments to documents.")
        else:
            click.echo("No attachments to migrate.")
