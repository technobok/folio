"""Authentication blueprint using Gatekeeper SSO."""

import functools
from collections.abc import Callable
from typing import Any

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.wrappers import Response

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.before_app_request
def load_logged_in_user() -> None:
    """Load user from Gatekeeper cookie before each request.

    If Gatekeeper is not configured, g.user remains None and the
    login page will show a message about configuration.
    """
    # Gatekeeper integration handles this via its before_request hook,
    # but we need a fallback for when it's not configured.
    if not hasattr(g, "user"):
        g.user = None


def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that redirects anonymous users to the login page."""

    @functools.wraps(view)
    def wrapped_view(*args: Any, **kwargs: Any) -> Any:
        if g.get("user") is None:
            return redirect(url_for("auth.login", next=request.url))
        return view(*args, **kwargs)

    return wrapped_view


def get_username() -> str:
    """Get the current user's username, or 'anonymous'."""
    user = g.get("user")
    if user is None:
        return "anonymous"
    return user.username


def get_display_name() -> str:
    """Get the current user's display name."""
    user = g.get("user")
    if user is None:
        return "Anonymous"
    return user.fullname or user.username


@bp.route("/login")
def login() -> str | Response:
    """Redirect to Gatekeeper SSO login, or show fallback page."""
    if g.get("user"):
        return redirect(url_for("index"))

    gk = current_app.config.get("GATEKEEPER_CLIENT")
    if not gk:
        return render_template("auth/login.html", login_url=None)

    login_url = gk.get_login_url()
    if not login_url:
        return render_template("auth/login.html", login_url=None)

    next_url = request.args.get("next", "/")
    callback_url = url_for("auth.verify", _external=True)

    return redirect(
        f"{login_url}?app_name=Folio"
        f"&callback_url={callback_url}"
        f"&next={next_url}"
    )


@bp.route("/verify")
def verify() -> Response:
    """Verify magic link token from Gatekeeper."""
    gk = current_app.config.get("GATEKEEPER_CLIENT")
    if not gk:
        flash("Authentication is not configured.", "error")
        return redirect(url_for("index"))

    token = request.args.get("token", "")
    result = gk.verify_magic_link(token)

    if not result:
        flash("Invalid or expired login link. Please request a new one.", "error")
        return redirect(url_for("auth.login"))

    user, redirect_url = result

    # Create auth token and set cookie
    auth_token = gk.create_auth_token(user)

    response = redirect(redirect_url or url_for("index"))
    response.set_cookie(
        "gk_session",
        auth_token,
        max_age=86400 * 365,
        httponly=True,
        secure=not current_app.config.get("DEBUG", False),
        samesite="Lax",
    )

    flash(f"Welcome, {user.fullname or user.username}!", "success")
    return response


@bp.route("/logout")
def logout() -> Response:
    """Log out the current user."""
    response = redirect(url_for("index"))
    response.delete_cookie("gk_session")
    flash("You have been logged out.", "info")
    return response
