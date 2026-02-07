"""CLI entry point for folio-admin."""

import sys

import click

from folio.config import REGISTRY, parse_value, resolve_entry, serialize_value
from folio.db import (
    close_standalone_db,
    get_db_path,
    get_standalone_db,
    init_db_at,
    standalone_transaction,
)


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


# ---- admin commands ------------------------------------------------------


@main.command("init-db")
def init_db_command():
    """Initialize the database schema."""
    db_path = get_db_path()
    init_db_at(db_path)
    click.echo(f"Database initialized at {db_path}")
