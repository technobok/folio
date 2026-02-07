"""Folio - A self-hosted document management system."""

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import apsw
import mistune
from flask import Flask, render_template, request
from markupsafe import Markup

from folio.config import KEY_MAP, REGISTRY, parse_value


def get_user_timezone() -> ZoneInfo:
    """Get user's timezone from request header or cookie."""
    tz_name = request.headers.get("X-Timezone") or request.cookies.get("tz") or "UTC"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("UTC")


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    """Application factory for Folio."""
    # Resolve database path
    db_path = os.environ.get("FOLIO_DB")
    if not db_path:
        if "FOLIO_ROOT" in os.environ:
            project_root = Path(os.environ["FOLIO_ROOT"])
        else:
            source_root = Path(__file__).parent.parent.parent
            if (source_root / "src" / "folio" / "__init__.py").exists():
                project_root = source_root
            else:
                project_root = Path.cwd()
        db_path = str(project_root / "instance" / "folio.sqlite3")
        instance_path = project_root / "instance"
    else:
        instance_path = Path(db_path).parent

    instance_path.mkdir(parents=True, exist_ok=True)

    app = Flask(
        __name__,
        instance_path=str(instance_path),
        instance_relative_config=True,
    )

    app.config.from_mapping(
        SECRET_KEY="dev",
        DATABASE_PATH=db_path,
    )

    if test_config is not None:
        app.config.from_mapping(test_config)
    else:
        _load_config_from_db(app)

    max_mb = app.config.get("MAX_UPLOAD_SIZE_MB", 50)
    app.config["MAX_UPLOAD_SIZE"] = max_mb * 1024 * 1024

    # Ensure directories exist
    blobs_dir = app.config.get("BLOBS_DIRECTORY", str(instance_path / "blobs"))
    Path(blobs_dir).mkdir(parents=True, exist_ok=True)
    # Store resolved absolute path
    if not os.path.isabs(blobs_dir):
        blobs_dir = str(instance_path / blobs_dir)
    app.config["BLOBS_DIRECTORY"] = blobs_dir

    from folio.db import close_db

    app.teardown_appcontext(close_db)

    # Jinja filters
    @app.template_filter("localdate")
    def localdate_filter(iso_string: str | None) -> str:
        if not iso_string:
            return ""
        try:
            dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            user_tz = get_user_timezone()
            local_dt = dt.astimezone(user_tz)
            return local_dt.strftime("%b %d, %Y")
        except Exception:
            return iso_string[:10] if iso_string else ""

    @app.template_filter("localdatetime")
    def localdatetime_filter(iso_string: str | None) -> str:
        if not iso_string:
            return ""
        try:
            dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            user_tz = get_user_timezone()
            local_dt = dt.astimezone(user_tz)
            tz_abbr = local_dt.strftime("%Z")
            return local_dt.strftime(f"%b %d, %Y %H:%M {tz_abbr}")
        except Exception:
            return iso_string[:16].replace("T", " ") if iso_string else ""

    # Markdown renderer for document display (GFM plugins)
    md = mistune.create_markdown(
        escape=True,
        plugins=["strikethrough", "table", "task_lists", "url"],
    )

    @app.template_filter("markdown")
    def markdown_filter(text: str | None) -> Markup:
        if not text:
            return Markup("")
        html = str(md(text)).strip()
        if html.startswith("<p>") and html.endswith("</p>") and html.count("<p>") == 1:
            html = html[3:-4]
        return Markup(html)

    @app.template_filter("markdown_block")
    def markdown_block_filter(text: str | None) -> Markup:
        if not text:
            return Markup("")
        return Markup(str(md(text)))

    # Register blueprints
    from folio.blueprints import auth, documents

    app.register_blueprint(auth.bp)
    app.register_blueprint(documents.bp)

    # Initialize Gatekeeper client if configured
    gk_db_path = app.config.get("GATEKEEPER_DB_PATH", "")
    if gk_db_path:
        from gatekeeper_client import GatekeeperClient

        gk = GatekeeperClient(db_path=gk_db_path)
        cookie_name = app.config.get("GATEKEEPER_COOKIE_NAME", "folio_session")
        gk.init_app(app, cookie_name=cookie_name)
        app.config["GATEKEEPER_CLIENT"] = gk

    @app.route("/")
    def index():
        return render_template("index.html")

    return app


def _load_config_from_db(app: Flask) -> None:
    """Load configuration from the database into Flask app.config."""
    db_path = app.config["DATABASE_PATH"]

    try:
        conn = apsw.Connection(db_path, flags=apsw.SQLITE_OPEN_READONLY)
    except apsw.CantOpenError:
        return

    try:
        rows = conn.execute("SELECT key, value FROM app_setting").fetchall()
    except apsw.SQLError:
        conn.close()
        return

    db_values = {str(r[0]): str(r[1]) for r in rows}
    conn.close()

    if "secret_key" in db_values:
        app.config["SECRET_KEY"] = db_values["secret_key"]

    for entry in REGISTRY:
        flask_key = KEY_MAP.get(entry.key)
        if not flask_key:
            continue

        raw = db_values.get(entry.key)
        if raw is not None:
            value = parse_value(entry, raw)
        else:
            value = entry.default

        app.config[flask_key] = value

    # Apply ProxyFix if any proxy values are non-zero
    x_for = app.config.get("PROXY_X_FORWARDED_FOR", 0)
    x_proto = app.config.get("PROXY_X_FORWARDED_PROTO", 0)
    x_host = app.config.get("PROXY_X_FORWARDED_HOST", 0)
    x_prefix = app.config.get("PROXY_X_FORWARDED_PREFIX", 0)
    if any((x_for, x_proto, x_host, x_prefix)):
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(  # type: ignore[assignment]
            app.wsgi_app, x_for=x_for, x_proto=x_proto, x_host=x_host, x_prefix=x_prefix
        )
