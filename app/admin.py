"""Moderation queue — the one authenticated corner of the site.

Deliberately not a general admin framework. Flask-Admin and friends generate a
CRUD screen over a table, which is both more than is wanted here and less: the
job is not "edit rows" but "read an objection and decide what happens to it",
and those are four buttons, not a form builder. Rolling it costs about two
hundred lines and no new dependency, against SQLAlchemy plus WTForms added to
a serverless bundle whose requirements file already warns about its size.

There is one operator, so there is no user table, no registration, no password
reset and no session store. A single password hash lives in the environment
and a signed cookie carries the fact of having entered it.

Everything under /admin is noindex, nofollow and no-store. That is belt and
braces on top of the authentication — a 401 has nothing to index — and the
path is deliberately *not* disallowed in robots.txt, because a blocked URL is
one a crawler cannot fetch, and therefore one whose noindex header it can
never read.
"""
from __future__ import annotations

import hmac
import os
import secrets
import time

from flask import (
    Blueprint, Response, flash, redirect, render_template, request, session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from app import critiques, db

bp = Blueprint("admin", __name__, url_prefix="/admin")

SESSION_KEY = "admin_ok"
CSRF_KEY = "admin_csrf"

# Generated with app/admin.py's own helper (see `python -m app.admin hash`).
# Absent means the admin area is closed entirely rather than open: a missing
# password must never be a missing lock.
PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "")

# Coarse brute-force throttle. Per-process, so on serverless it resets with
# every cold start and is worth exactly what it costs — the real defence is a
# long random password in the environment, not this counter.
_ATTEMPTS: dict[str, tuple[int, float]] = {}
MAX_ATTEMPTS = 8
ATTEMPT_WINDOW = 900.0


def _client_key() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() or (request.remote_addr or "unknown")


def _throttled() -> bool:
    count, first_seen = _ATTEMPTS.get(_client_key(), (0, 0.0))
    if time.time() - first_seen > ATTEMPT_WINDOW:
        return False
    return count >= MAX_ATTEMPTS


def _record_failure() -> None:
    key = _client_key()
    count, first_seen = _ATTEMPTS.get(key, (0, 0.0))
    if time.time() - first_seen > ATTEMPT_WINDOW:
        count, first_seen = 0, time.time()
    _ATTEMPTS[key] = (count + 1, first_seen)


def is_authenticated() -> bool:
    return bool(session.get(SESSION_KEY))


def csrf_token() -> str:
    """Per-session token for the moderation forms.

    The session cookie is SameSite=Lax, which already blocks a cross-site POST,
    but the whole authenticated surface here is state-changing forms and a
    second, explicit check is cheap.
    """
    token = session.get(CSRF_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_KEY] = token
    return token


def _csrf_ok() -> bool:
    sent = request.form.get("csrf_token", "")
    expected = session.get(CSRF_KEY, "")
    return bool(expected) and hmac.compare_digest(sent, expected)


@bp.after_request
def _never_index(resp: Response) -> Response:
    resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    resp.headers["Cache-Control"] = "no-store, private"
    return resp


@bp.route("/login", methods=["GET", "POST"])
def login():
    if is_authenticated():
        return redirect(url_for("admin.queue"))

    if not PASSWORD_HASH:
        return render_template(
            "admin/login.html",
            csrf=csrf_token(),
            disabled="No admin password is configured on this deployment.",
        ), 503

    if request.method == "POST":
        if _throttled():
            return render_template(
                "admin/login.html", csrf=csrf_token(),
                error="Too many attempts. Try again later.",
            ), 429
        password = request.form.get("password", "")
        if password and check_password_hash(PASSWORD_HASH, password):
            session.clear()
            session[SESSION_KEY] = True
            session.permanent = True
            csrf_token()
            return redirect(url_for("admin.queue"))
        _record_failure()
        return render_template(
            "admin/login.html", csrf=csrf_token(), error="Incorrect password.",
        ), 401

    return render_template("admin/login.html", csrf=csrf_token())


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("admin.login"))


@bp.route("/")
def index():
    return redirect(url_for("admin.queue"))


@bp.route("/queue")
def queue():
    if not is_authenticated():
        return redirect(url_for("admin.login"))

    status = request.args.get("status", "pending")
    if status not in critiques.STATUSES:
        status = "pending"

    if not db.is_configured():
        return render_template(
            "admin/queue.html", rows=[], counts={}, status=status,
            csrf=csrf_token(), db_error="No database is configured.",
        )
    try:
        rows = critiques.get_queue(status=status)
        counts = critiques.status_counts()
        db_error = None
    except Exception as exc:  # surfaced, not swallowed: this page is for me
        rows, counts, db_error = [], {}, str(exc)

    return render_template(
        "admin/queue.html", rows=rows, counts=counts, status=status,
        csrf=csrf_token(), db_error=db_error, reports=critiques.REPORTS,
    )


@bp.route("/critique/<int:critique_id>", methods=["POST"])
def moderate(critique_id: int):
    if not is_authenticated():
        return redirect(url_for("admin.login"))
    if not _csrf_ok():
        return redirect(url_for("admin.queue"))

    action = request.form.get("action", "")
    back = redirect(url_for("admin.queue", status=request.form.get("from", "pending")))

    try:
        if action == "delete":
            critiques.delete(critique_id)
            flash("Deleted.", "ok")
        elif action in ("publish", "accept", "reject"):
            status = {"publish": "published", "accept": "accepted",
                      "reject": "rejected"}[action]
            critiques.moderate(
                critique_id,
                status=status,
                response=request.form.get("response"),
                changelog=request.form.get("changelog"),
            )
            flash(f"Marked {status}.", "ok")
        else:
            flash("Unknown action.", "error")
    except Exception as exc:
        flash(f"Failed: {exc}", "error")

    return back


if __name__ == "__main__":  # pragma: no cover - operator helper
    import getpass
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "hash":
        pw = getpass.getpass("New admin password: ")
        if pw != getpass.getpass("Repeat: "):
            sys.exit("Passwords did not match.")
        if len(pw) < 12:
            sys.exit("Use at least 12 characters.")
        print("\nADMIN_PASSWORD_HASH=" + generate_password_hash(pw))
    else:
        print("Usage: python -m app.admin hash")
