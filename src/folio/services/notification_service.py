"""Notification service - email watchers via Outbox."""

import json
import logging
import uuid
from datetime import UTC, datetime

from flask import current_app, url_for

log = logging.getLogger(__name__)


def notify_watchers(
    document_id: int,
    changed_by: str,
    document_title: str,
    document_slug: str,
    subject_prefix: str = "",
) -> None:
    """Notify watchers of a document change (excluding the person who made the change)."""
    from folio.models.document_watcher import DocumentWatcher

    db_path = current_app.config.get("OUTBOX_DB_PATH", "")
    mail_sender = current_app.config.get("OUTBOX_MAIL_SENDER", "")

    if not db_path or not mail_sender:
        return

    watchers = DocumentWatcher.get_watchers(document_id)
    other_watchers = [w for w in watchers if w != changed_by]
    if not other_watchers:
        return

    # Look up emails via Gatekeeper
    gk = current_app.config.get("GATEKEEPER_CLIENT")
    if not gk:
        log.warning("Cannot send notifications: Gatekeeper client not configured")
        return

    subject = f"{subject_prefix}Folio: {document_title} was updated"
    doc_url = url_for("documents.view", slug=document_slug, _external=True)

    for username in other_watchers:
        try:
            user = gk.get_user(username)
            if not user or not user.email:
                log.debug("No email for watcher %s", username)
                continue

            body_text = (
                f"{document_title} was updated by {changed_by}.\n\n"
                f"View the document: {doc_url}\n\n"
                f"You are receiving this because you are watching this document."
            )

            _queue_email(db_path, mail_sender, user.email, subject, body_text)

        except Exception:
            log.exception("Failed to notify watcher %s", username)


def _queue_email(
    db_path: str,
    mail_sender: str,
    to_email: str,
    subject: str,
    body_text: str,
) -> None:
    """Insert an email into the Outbox SQLite database."""
    import apsw

    now = datetime.now(UTC).isoformat()
    msg_uuid = str(uuid.uuid4())

    try:
        conn = apsw.Connection(db_path)
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(
            "INSERT INTO message "
            "(uuid, status, delivery_type, from_address, to_recipients, "
            "subject, body, body_type, source_app, created_at, updated_at) "
            "VALUES (?, 'queued', 'email', ?, ?, ?, ?, 'plain', 'folio', ?, ?)",
            (msg_uuid, mail_sender, json.dumps([to_email]), subject, body_text, now, now),
        )
        conn.close()
        log.info("Email queued in outbox DB to %s: %s", to_email, subject)
    except Exception:
        log.exception("Failed to queue email in outbox DB to %s", to_email)
