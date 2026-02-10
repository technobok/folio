"""Web server entry point for folio-web."""

from __future__ import annotations

import click
from flask import Flask


@click.command()
@click.option("--host", default=None, help="Bind address (overrides config)")
@click.option("--port", default=None, type=int, help="Port (overrides config)")
@click.option("--workers", default=2, help="Number of gunicorn workers")
@click.option("--dev", is_flag=True, help="Run Flask development server with debug mode")
def main(host: str | None, port: int | None, workers: int, dev: bool) -> None:
    """Start the Folio web server."""
    from folio import create_app

    app = create_app()

    if dev:
        run_host = host or app.config.get("DEV_HOST", "127.0.0.1")
        run_port = port or app.config.get("DEV_PORT", 5001)
        app.run(debug=True, host=run_host, port=run_port)
    else:
        run_host = host or app.config.get("HOST", "0.0.0.0")
        run_port = port or app.config.get("PORT", 5001)

        import gunicorn.app.base

        class FolioApp(gunicorn.app.base.BaseApplication):
            def load_config(self) -> None:
                self.cfg.set("bind", f"{run_host}:{run_port}")  # type: ignore[union-attr]
                self.cfg.set("workers", str(workers))  # type: ignore[union-attr]
                self.cfg.set("preload_app", True)  # type: ignore[union-attr]

            def load(self) -> Flask:
                return app

        FolioApp().run()
