"""Admin blueprint for ad hoc SQL query execution."""

import tempfile

import apsw
from flask import (
    Blueprint,
    render_template,
    request,
    send_file,
)
from openpyxl import Workbook

from folio.blueprints.auth import login_required
from folio.db import get_db

bp = Blueprint("admin_sql", __name__, url_prefix="/admin/sql")


def _get_schema() -> list[dict[str, object]]:
    """Get database schema: table names with their column names."""
    db = get_db()
    tables: list[dict[str, object]] = []
    for (name,) in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall():
        cols = [row[1] for row in db.execute(f"PRAGMA table_info({name})").fetchall()]
        tables.append({"name": name, "columns": cols})
    return tables


@bp.route("/", methods=["GET"])
@login_required
def index():
    """Show the SQL query page."""
    schema = _get_schema()
    return render_template("admin/sql.html", schema=schema, query="", columns=[], rows=[])


@bp.route("/", methods=["POST"])
@login_required
def execute():
    """Execute a SQL query and display results."""
    sql = request.form.get("sql", "").strip()
    schema = _get_schema()
    columns: list[str] = []
    rows: list[tuple] = []
    error: str | None = None

    if not sql:
        error = "No SQL query provided."
    else:
        try:
            cursor = get_db().cursor()
            cursor.execute(sql)
            try:
                desc = cursor.getdescription()
                columns = [d[0] for d in desc]
                rows = cursor.fetchall()
            except apsw.ExecutionCompleteError:
                pass
        except Exception as exc:
            error = str(exc)

    return render_template(
        "admin/sql.html",
        schema=schema,
        query=sql,
        columns=columns,
        rows=rows,
        error=error,
        row_count=len(rows),
    )


@bp.route("/export", methods=["POST"])
@login_required
def export():
    """Export SQL query results as XLSX."""
    sql = request.form.get("sql", "").strip()
    if not sql:
        return render_template(
            "admin/sql.html",
            schema=_get_schema(),
            query=sql,
            columns=[],
            rows=[],
            error="No SQL query provided.",
            row_count=0,
        )

    try:
        cursor = get_db().cursor()
        cursor.execute(sql)
        desc = cursor.getdescription()
        headers = [d[0] for d in desc]
        rows = cursor.fetchall()
    except Exception as exc:
        return render_template(
            "admin/sql.html",
            schema=_get_schema(),
            query=sql,
            columns=[],
            rows=[],
            error=str(exc),
            row_count=0,
        )

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "query"
    ws.append(headers)
    for row in rows:
        ws.append(list(row))
    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    tmp.close()
    wb.save(tmp.name)

    return send_file(tmp.name, as_attachment=True, download_name="query.xlsx")
