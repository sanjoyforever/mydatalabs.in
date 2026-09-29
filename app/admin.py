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

from app import comments, critiques, db

ADMIN_PREFIX = os.environ.get("ADMIN_PREFIX", "/admin").strip()
if not ADMIN_PREFIX.startswith("/"):
    ADMIN_PREFIX = "/" + ADMIN_PREFIX
ADMIN_PREFIX = ADMIN_PREFIX.rstrip("/") or "/admin"

bp = Blueprint("admin", __name__, url_prefix=ADMIN_PREFIX)

SESSION_KEY = "admin_ok"
CSRF_KEY = "admin_csrf"

# Configured either with ADMIN_PASSWORD (plain text in .env) or ADMIN_PASSWORD_HASH
PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "")
PLAIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


def _password_configured() -> bool:
    return bool(os.environ.get("ADMIN_PASSWORD_HASH") or os.environ.get("ADMIN_PASSWORD") or PASSWORD_HASH or PLAIN_PASSWORD)


def _verify_password(candidate: str) -> bool:
    if not candidate:
        return False
    pw_hash = os.environ.get("ADMIN_PASSWORD_HASH") or PASSWORD_HASH
    plain_pw = os.environ.get("ADMIN_PASSWORD") or PLAIN_PASSWORD
    if pw_hash and check_password_hash(pw_hash, candidate):
        return True
    if plain_pw and hmac.compare_digest(candidate, plain_pw):
        return True
    return False

# Multi-layered brute-force defense:
# - In-memory cache for sub-millisecond rejection
# - Persistent DB tracking (Firestore / SQLite) surviving cold starts and horizontal scaling
# - Invisible honeypot trap catching automated bot form scanners
# - IP rate limiting: 5 failed attempts locks the IP out for 15 minutes
_ATTEMPTS: dict[str, tuple[int, float, float]] = {}  # key -> (failures, first_seen, locked_until)
MAX_ATTEMPTS = int(os.environ.get("ADMIN_MAX_ATTEMPTS", "5"))
ATTEMPT_WINDOW = float(os.environ.get("ADMIN_ATTEMPT_WINDOW", "900.0"))
LOCKOUT_DURATION = float(os.environ.get("ADMIN_LOCKOUT_DURATION", "900.0"))


def _client_key() -> str:
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _get_lockout_record(key: str) -> tuple[int, float, float]:
    """Return (failures, first_seen, locked_until) from memory or persistent store."""
    now = time.time()
    if key in _ATTEMPTS:
        failures, first_seen, locked_until = _ATTEMPTS[key]
        if locked_until > now:
            return failures, first_seen, locked_until
        if now - first_seen <= ATTEMPT_WINDOW:
            return failures, first_seen, locked_until
        _ATTEMPTS.pop(key, None)

    # 1. Firestore on production / Vercel
    if comments._use_firestore():
        try:
            fdb = comments._get_firestore_client()
            if fdb:
                import hashlib
                doc_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
                doc = fdb.collection("admin_lockout").document(doc_id).get()
                if doc.exists:
                    d = doc.to_dict() or {}
                    failures = int(d.get("failures", 0))
                    first_seen = float(d.get("first_seen", 0.0))
                    locked_until = float(d.get("locked_until", 0.0))
                    if locked_until > now or (now - first_seen <= ATTEMPT_WINDOW):
                        _ATTEMPTS[key] = (failures, first_seen, locked_until)
                        return failures, first_seen, locked_until
        except Exception:
            pass

    # 2. SQLite local fallback
    if comments._use_sqlite():
        try:
            with comments._sqlite_cursor() as cur:
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS admin_lockout ("
                    "  client_ip TEXT PRIMARY KEY,"
                    "  failures INTEGER NOT NULL DEFAULT 0,"
                    "  first_seen REAL NOT NULL DEFAULT 0,"
                    "  locked_until REAL NOT NULL DEFAULT 0"
                    ")"
                )
                cur.execute(
                    "SELECT failures, first_seen, locked_until FROM admin_lockout WHERE client_ip = ?",
                    (key,)
                )
                row = cur.fetchone()
                if row:
                    failures, first_seen, locked_until = int(row[0]), float(row[1]), float(row[2])
                    if locked_until > now or (now - first_seen <= ATTEMPT_WINDOW):
                        _ATTEMPTS[key] = (failures, first_seen, locked_until)
                        return failures, first_seen, locked_until
        except Exception:
            pass

    return (0, 0.0, 0.0)


def _lockout_status() -> tuple[bool, int]:
    """Returns (is_locked, remaining_seconds)."""
    key = _client_key()
    now = time.time()
    failures, first_seen, locked_until = _get_lockout_record(key)
    if locked_until > now:
        return True, max(1, int(locked_until - now))
    if failures >= MAX_ATTEMPTS and (now - first_seen <= ATTEMPT_WINDOW):
        return True, max(1, int(ATTEMPT_WINDOW - (now - first_seen)))
    return False, 0


def _throttled() -> bool:
    blocked, _ = _lockout_status()
    return blocked


def _record_failure(force_lock: bool = False) -> None:
    key = _client_key()
    now = time.time()
    failures, first_seen, locked_until = _get_lockout_record(key)

    if now - first_seen > ATTEMPT_WINDOW or force_lock:
        failures, first_seen = 0, now

    failures += 1
    if force_lock or failures >= MAX_ATTEMPTS:
        locked_until = now + LOCKOUT_DURATION

    _ATTEMPTS[key] = (failures, first_seen, locked_until)

    if comments._use_firestore():
        try:
            fdb = comments._get_firestore_client()
            if fdb:
                import hashlib
                doc_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
                fdb.collection("admin_lockout").document(doc_id).set({
                    "failures": failures,
                    "first_seen": first_seen,
                    "locked_until": locked_until,
                    "updated_at": now,
                })
        except Exception:
            pass

    if comments._use_sqlite():
        try:
            with comments._sqlite_cursor() as cur:
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS admin_lockout ("
                    "  client_ip TEXT PRIMARY KEY,"
                    "  failures INTEGER NOT NULL DEFAULT 0,"
                    "  first_seen REAL NOT NULL DEFAULT 0,"
                    "  locked_until REAL NOT NULL DEFAULT 0"
                    ")"
                )
                cur.execute(
                    "INSERT INTO admin_lockout (client_ip, failures, first_seen, locked_until) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(client_ip) DO UPDATE SET "
                    "  failures = excluded.failures,"
                    "  first_seen = excluded.first_seen,"
                    "  locked_until = excluded.locked_until",
                    (key, failures, first_seen, locked_until)
                )
        except Exception:
            pass


def _clear_lockout() -> None:
    key = _client_key()
    _ATTEMPTS.pop(key, None)
    if comments._use_firestore():
        try:
            fdb = comments._get_firestore_client()
            if fdb:
                import hashlib
                doc_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
                fdb.collection("admin_lockout").document(doc_id).delete()
        except Exception:
            pass
    if comments._use_sqlite():
        try:
            with comments._sqlite_cursor() as cur:
                cur.execute("DELETE FROM admin_lockout WHERE client_ip = ?", (key,))
        except Exception:
            pass


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
    next_url = request.args.get("next") or request.form.get("next") or ""
    if not (next_url.startswith(ADMIN_PREFIX) and not next_url.startswith("//")):
        next_url = url_for("admin.comments_queue")

    if is_authenticated():
        return redirect(next_url)

    from app.routes import _common, get_home_context

    try:
        home_ctx = get_home_context()
    except Exception:
        home_ctx = {}

    if not _password_configured():
        return render_template(
            "admin/login.html",
            csrf=csrf_token(),
            disabled="No admin password is configured on this deployment.",
            next_url=next_url,
            **_common(**home_ctx),
        ), 503

    if request.method == "POST":
        # 1. Honeypot check: Automated crawlers fill invisible username inputs
        bot_field = (request.form.get("admin_username") or request.form.get("username") or "").strip()
        if bot_field:
            _record_failure(force_lock=True)
            return render_template(
                "admin/login.html",
                csrf=csrf_token(),
                next_url=next_url,
                error="Access denied.",
                **_common(**home_ctx),
            ), 403

        # 2. Lockout throttle check
        is_blocked, remaining = _lockout_status()
        if is_blocked:
            mins = max(1, (remaining + 59) // 60)
            return render_template(
                "admin/login.html",
                csrf=csrf_token(),
                next_url=next_url,
                error=f"Too many failed attempts. Access locked for {mins} minute{'s' if mins > 1 else ''}.",
                **_common(**home_ctx),
            ), 429

        password = request.form.get("password", "")
        if password and _verify_password(password):
            _clear_lockout()
            session.clear()
            session[SESSION_KEY] = True
            session.permanent = True
            csrf_token()
            return redirect(next_url)

        _record_failure()
        return render_template(
            "admin/login.html",
            csrf=csrf_token(),
            next_url=next_url,
            error="Incorrect password.",
            **_common(**home_ctx),
        ), 401

    return render_template(
        "admin/login.html",
        csrf=csrf_token(),
        next_url=next_url,
        **_common(**home_ctx),
    )


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("admin.login"))


@bp.route("/")
def index():
    return redirect(url_for("admin.comments_queue"))


@bp.route("/queue")
def queue():
    if not is_authenticated():
        return redirect(url_for("admin.login", next=request.path))

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


@bp.route("/comments")
def comments_queue():
    if not is_authenticated():
        return redirect(url_for("admin.login", next=request.path))

    status = request.args.get("status", "pending")
    if status not in comments.STATUSES:
        status = "pending"

    if not comments.is_configured():
        return render_template(
            "admin/comments.html", rows=[], counts={}, status=status,
            csrf=csrf_token(), db_error="No database is configured.",
        )
    try:
        rows = comments.get_queue(status=status)
        counts = comments.status_counts()
        db_error = None
    except Exception as exc:
        rows, counts, db_error = [], {}, str(exc)

    return render_template(
        "admin/comments.html", rows=rows, counts=counts, status=status,
        csrf=csrf_token(), db_error=db_error,
    )


@bp.route("/comment/<comment_id>", methods=["POST"])
def moderate_comment(comment_id):
    if not is_authenticated():
        return redirect(url_for("admin.login"))
    if not _csrf_ok():
        return redirect(url_for("admin.comments_queue"))

    action = request.form.get("action", "")
    back = redirect(url_for("admin.comments_queue", status=request.form.get("from", "pending")))

    try:
        if action == "delete":
            comments.delete(comment_id)
            flash("Comment deleted.", "ok")
        elif action in ("publish", "reject"):
            status = {"publish": "published", "reject": "rejected"}[action]
            comments.moderate(
                comment_id,
                status=status,
                response=request.form.get("response"),
            )
            flash(f"Comment marked {status}.", "ok")
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
