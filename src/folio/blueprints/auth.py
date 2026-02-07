"""Authentication blueprint using Gatekeeper client."""

import functools

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


def login_required(view):
    """Decorator that redirects anonymous users to the login page."""

    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.get("user") is None:
            return redirect(url_for("auth.login", next=request.url))
        return view(**kwargs)

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


@bp.route("/login", methods=["GET", "POST"])
def login():
    """Login page - redirect to Gatekeeper or show configuration needed."""
    if g.get("user"):
        return redirect(url_for("index"))

    gk = current_app.config.get("GATEKEEPER_CLIENT")
    if not gk:
        return render_template("auth/login.html", gatekeeper_configured=False)

    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        if not identifier:
            flash("Please enter your username or email.", "error")
            return render_template("auth/login.html", gatekeeper_configured=True)

        callback_url = url_for("auth.verify", _external=True)
        next_url = request.form.get("next", "/")

        if gk.send_magic_link(identifier, callback_url, redirect_url=next_url, app_name="Folio"):
            return render_template("auth/login_sent.html", identifier=identifier)
        else:
            flash("User not found or email could not be sent.", "error")

    return render_template(
        "auth/login.html",
        gatekeeper_configured=True,
        next=request.args.get("next", "/"),
    )


@bp.route("/verify")
def verify():
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
    cookie_name = current_app.config.get("GATEKEEPER_COOKIE_NAME", "folio_session")

    response = redirect(redirect_url or url_for("index"))
    response.set_cookie(
        cookie_name,
        auth_token,
        max_age=86400 * 365,
        httponly=True,
        secure=not current_app.config.get("DEBUG", False),
        samesite="Lax",
    )

    flash(f"Welcome, {user.fullname or user.username}!", "success")
    return response


@bp.route("/logout")
def logout():
    """Log out the current user."""
    cookie_name = current_app.config.get("GATEKEEPER_COOKIE_NAME", "folio_session")
    response = redirect(url_for("index"))
    response.delete_cookie(cookie_name)
    flash("You have been logged out.", "info")
    return response
