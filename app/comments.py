"""Reader comments for Lab Notes and articles with multi-layer anti-spam.

Designed for serious, high-signal methodology discussions on mydatalabs.in.
Hostile to link-spammers and automated bots by construction:

1. Honeypot traps: Bots filling out hidden 'website' fields are rejected.
2. Fast-submission traps: Forms submitted faster than human reading speed are rejected.
3. Strict link & contact ban: Folds confusables/homoglyphs (e.g. Cyrillic) and strips
   zero-width characters to catch hidden URLs, @handles, phone numbers, and emails.
4. Anonymous identity & rate ceilings: Reuses the privacy-first voter token and
   origin hash from ``votes.py`` to rate-limit submissions without storing personal data.
5. Tri-mode storage engine:
   - Uses Firebase Cloud Firestore when configured (ideal for Vercel production).
   - Falls back to local zero-config SQLite (`app/data/comments.db`) for instant local dev.
   - Supports PostgreSQL (Neon) when available.
6. Default pending moderation: No comment reaches public eyes until reviewed.
"""
from __future__ import annotations

import os
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any

from app import db
from app.critiques import (
    fold_for_detection,
    find_link,
)
from app.votes import hash_origin, hash_voter_token

__all__ = [
    "CommentRejected",
    "DatabaseUnavailable",
    "STATUSES",
    "SCHEMA",
    "is_configured",
    "submit",
    "validate",
    "get_published",
    "get_queue",
    "status_counts",
    "moderate",
    "delete",
    "current_week_start",
    "hash_origin",
    "hash_voter_token",
]

STATUSES = ("pending", "published", "rejected")

# Limits
MIN_BODY = int(os.environ.get("COMMENT_MIN_BODY", "15"))
MAX_BODY = int(os.environ.get("COMMENT_MAX_BODY", "1200"))
MAX_NAME = 40
MAX_RESPONSE = 600

# Submissions allowed per coarse origin hash per week
MAX_PER_ORIGIN = int(os.environ.get("COMMENT_MAX_PER_ORIGIN", "6"))

# Minimum elapsed seconds between form load and submission
MIN_FILL_SECONDS = float(os.environ.get("COMMENT_MIN_FILL_SECONDS", "3.0"))

SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "comments.db")


class CommentRejected(Exception):
    """Submission refused. The message is shown to the visitor verbatim."""


class DatabaseUnavailable(Exception):
    """Database is down or unconfigured."""


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS article_comments (
        id            BIGSERIAL PRIMARY KEY,
        article_slug  TEXT        NOT NULL,
        author_name   TEXT,
        body          TEXT        NOT NULL,
        voter_hash    TEXT        NOT NULL,
        origin_hash   TEXT        NOT NULL,
        week_start    DATE        NOT NULL,
        status        TEXT        NOT NULL DEFAULT 'pending',
        response      TEXT,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        moderated_at  TIMESTAMPTZ,
        CONSTRAINT article_comments_status_valid
            CHECK (status IN ('pending', 'published', 'rejected'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS article_comments_public_idx
        ON article_comments (article_slug, status, created_at ASC)
    """,
    """
    CREATE INDEX IF NOT EXISTS article_comments_queue_idx
        ON article_comments (status, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS article_comments_origin_idx
        ON article_comments (origin_hash, week_start)
    """,
]

SQLITE_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS article_comments (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        article_slug  TEXT        NOT NULL,
        author_name   TEXT,
        body          TEXT        NOT NULL,
        voter_hash    TEXT        NOT NULL,
        origin_hash   TEXT        NOT NULL,
        week_start    TEXT        NOT NULL,
        status        TEXT        NOT NULL DEFAULT 'pending',
        response      TEXT,
        created_at    DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
        moderated_at  DATETIME,
        CHECK (status IN ('pending', 'published', 'rejected'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS article_comments_public_idx
        ON article_comments (article_slug, status, created_at ASC)
    """,
    """
    CREATE INDEX IF NOT EXISTS article_comments_queue_idx
        ON article_comments (status, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS article_comments_origin_idx
        ON article_comments (origin_hash, week_start)
    """,
]

# --- Firebase Firestore Setup ---
_firestore_db = None


def _use_firestore() -> bool:
    return bool(os.environ.get("FIREBASE_SERVICE_ACCOUNT_KEY") or os.environ.get("FIREBASE_CONFIG"))


def _get_firestore_client():
    global _firestore_db
    if _firestore_db is not None:
        return _firestore_db
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore

        if not firebase_admin._apps:
            key = os.environ.get("FIREBASE_SERVICE_ACCOUNT_KEY") or os.environ.get("FIREBASE_CONFIG")
            project_id = os.environ.get("FIREBASE_PROJECT_ID", "mydatalabs-comments")
            if key and os.path.exists(key):
                cred = credentials.Certificate(key)
                firebase_admin.initialize_app(cred, {"projectId": project_id})
            elif key and key.strip().startswith("{"):
                import json
                cred = credentials.Certificate(json.loads(key))
                firebase_admin.initialize_app(cred, {"projectId": project_id})
            else:
                firebase_admin.initialize_app(options={"projectId": project_id})
        _firestore_db = firestore.client()
        return _firestore_db
    except Exception:
        return None


def _use_sqlite() -> bool:
    if _use_firestore() and _get_firestore_client() is not None:
        return False
    mode = os.environ.get("COMMENTS_DB", "").lower()
    if mode == "postgres":
        return False
    return True


def is_configured() -> bool:
    """Always configured because SQLite provides a zero-latency local engine."""
    return True


@contextmanager
def _sqlite_cursor():
    os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    finally:
        conn.close()


def _ensure_sqlite_schema():
    with _sqlite_cursor() as cur:
        for stmt in SQLITE_SCHEMA:
            cur.execute(stmt)


def current_week_start(today: date | None = None) -> str:
    """Monday of the current week — the bucket the rate ceiling counts against."""
    d = today or date.today()
    return (d - timedelta(days=d.weekday())).isoformat()


def _clean(text: str | None, limit: int) -> str:
    """Collapse runaway whitespace and trim. Newlines survive, runs of them do not."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", str(text))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()[:limit]


def check_honeypot(payload: dict[str, Any]) -> None:
    """Detect automated bot submissions."""
    if (payload.get("website") or "").strip():
        raise CommentRejected("Submission rejected.")
    try:
        elapsed = float(payload.get("elapsed", 0))
    except (TypeError, ValueError):
        elapsed = 0.0
    if elapsed < MIN_FILL_SECONDS:
        raise CommentRejected("That was submitted very quickly — please take a moment before submitting.")


def reject_links(text: str, field: str) -> None:
    found = find_link(text)
    if found:
        raise CommentRejected(
            f"Your {field} looks like it contains {found}. Comments are "
            f"published without links or contact details of any kind — please "
            f"describe the source in words instead."
        )


def validate(payload: dict[str, Any], article_slug: str) -> dict[str, Any]:
    """Check one comment submission and return cleaned fields, or raise CommentRejected."""
    slug = (article_slug or "").strip().lower()
    if not slug or not re.match(r"^[a-z0-9_-]{2,80}$", slug):
        raise CommentRejected("Invalid article identifier.")

    body = _clean(payload.get("body"), MAX_BODY)
    if len(body) < MIN_BODY:
        raise CommentRejected(
            f"Please write a comment of at least {MIN_BODY} characters."
        )
    reject_links(body, "comment")

    author_name = _clean(payload.get("name") or payload.get("author_name"), MAX_NAME)
    if author_name:
        reject_links(author_name, "name")

    return {
        "article_slug": slug,
        "author_name": author_name or None,
        "body": body,
    }


def submit(
    payload: dict[str, Any],
    article_slug: str,
    *,
    voter_hash: str,
    origin_hash: str,
) -> dict[str, Any]:
    """Validate and store one comment as pending. Never publishes immediately."""
    check_honeypot(payload)
    fields = validate(payload, article_slug)

    week_start = current_week_start()

    # Firestore Engine
    if _use_firestore():
        fs = _get_firestore_client()
        if fs is not None:
            docs = list(fs.collection("comments").where("origin_hash", "==", origin_hash).where("week_start", "==", week_start).stream())
            if len(docs) >= MAX_PER_ORIGIN:
                raise CommentRejected(
                    "You have shared several comments this week already. "
                    "Thank you — please return next week."
                )
            doc_ref = fs.collection("comments").document()
            doc_ref.set({
                "article_slug": fields["article_slug"],
                "author_name": fields["author_name"],
                "body": fields["body"],
                "voter_hash": voter_hash,
                "origin_hash": origin_hash,
                "week_start": week_start,
                "status": "pending",
                "response": None,
                "created_at": datetime.now(),
                "moderated_at": None,
            })
            return {
                "ok": True,
                "id": doc_ref.id,
                "status": "pending",
                "message": "Thank you! Your comment has been submitted and will appear once reviewed.",
            }

    # SQLite Engine (Local fallback)
    if _use_sqlite():
        _ensure_sqlite_schema()
        with _sqlite_cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM article_comments WHERE origin_hash = ? AND week_start = ?",
                (origin_hash, week_start),
            )
            count = (cur.fetchone() or [0])[0]
            if count >= MAX_PER_ORIGIN:
                raise CommentRejected(
                    "You have shared several comments this week already. "
                    "Thank you — please return next week."
                )
            cur.execute(
                """
                INSERT INTO article_comments
                    (article_slug, author_name, body, voter_hash, origin_hash, week_start)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    fields["article_slug"],
                    fields["author_name"],
                    fields["body"],
                    voter_hash,
                    origin_hash,
                    week_start,
                ),
            )
            new_id = cur.lastrowid
        return {
            "ok": True,
            "id": new_id,
            "status": "pending",
            "message": "Thank you! Your comment has been submitted and will appear once reviewed.",
        }

    # Postgres Engine
    try:
        db.ensure_schema(SCHEMA)
        with db.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM article_comments WHERE origin_hash = %s AND week_start = %s",
                (origin_hash, week_start),
            )
            count = (cur.fetchone() or [0])[0]
            if count >= MAX_PER_ORIGIN:
                raise CommentRejected(
                    "You have shared several comments this week already. "
                    "Thank you — please return next week."
                )
            cur.execute(
                """
                INSERT INTO article_comments
                    (article_slug, author_name, body, voter_hash, origin_hash, week_start)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    fields["article_slug"],
                    fields["author_name"],
                    fields["body"],
                    voter_hash,
                    origin_hash,
                    week_start,
                ),
            )
            new_id = cur.fetchone()[0]
    except (CommentRejected, DatabaseUnavailable):
        raise
    except Exception:
        # Fallback to SQLite if Postgres fails
        _ensure_sqlite_schema()
        with _sqlite_cursor() as cur:
            cur.execute(
                """
                INSERT INTO article_comments
                    (article_slug, author_name, body, voter_hash, origin_hash, week_start)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    fields["article_slug"],
                    fields["author_name"],
                    fields["body"],
                    voter_hash,
                    origin_hash,
                    week_start,
                ),
            )
            new_id = cur.lastrowid

    return {
        "ok": True,
        "id": new_id,
        "status": "pending",
        "message": "Thank you! Your comment has been submitted and will appear once reviewed.",
    }


def get_published(article_slug: str) -> list[dict[str, Any]]:
    """Return all published comments for an article, ordered chronologically."""
    if _use_firestore():
        fs = _get_firestore_client()
        if fs is not None:
            try:
                docs = fs.collection("comments").where("article_slug", "==", article_slug).where("status", "==", "published").stream()
                items = []
                for doc in docs:
                    d = doc.to_dict()
                    created = d.get("created_at")
                    if hasattr(created, "strftime"):
                        created = created.strftime("%d %b %Y, %H:%M")
                    items.append({
                        "id": doc.id,
                        "article_slug": d.get("article_slug"),
                        "author_name": d.get("author_name"),
                        "body": d.get("body"),
                        "response": d.get("response"),
                        "created_at": created or "",
                    })
                items.sort(key=lambda x: str(x.get("created_at", "")))
                return items
            except Exception:
                pass

    if _use_sqlite():
        try:
            _ensure_sqlite_schema()
            with _sqlite_cursor() as cur:
                cur.execute(
                    """
                    SELECT id, article_slug, author_name, body, response, created_at
                      FROM article_comments
                     WHERE article_slug = ? AND status = 'published'
                     ORDER BY created_at ASC
                    """,
                    (article_slug,),
                )
                return [dict(row) for row in cur.fetchall()]
        except Exception:
            return []

    try:
        db.ensure_schema(SCHEMA)
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT id, article_slug, author_name, body, response, created_at
                  FROM article_comments
                 WHERE article_slug = %s AND status = 'published'
                 ORDER BY created_at ASC
                """,
                (article_slug,),
            )
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception:
        try:
            _ensure_sqlite_schema()
            with _sqlite_cursor() as cur:
                cur.execute(
                    """
                    SELECT id, article_slug, author_name, body, response, created_at
                      FROM article_comments
                     WHERE article_slug = ? AND status = 'published'
                     ORDER BY created_at ASC
                    """,
                    (article_slug,),
                )
                return [dict(row) for row in cur.fetchall()]
        except Exception:
            return []


def get_queue(status: str = "pending", limit: int = 100) -> list[dict[str, Any]]:
    """Moderation queue for the admin area."""
    if status not in STATUSES:
        status = "pending"

    if _use_firestore():
        fs = _get_firestore_client()
        if fs is not None:
            try:
                docs = fs.collection("comments").where("status", "==", status).stream()
                items = []
                for doc in docs:
                    d = doc.to_dict()
                    created = d.get("created_at")
                    if hasattr(created, "strftime"):
                        created_str = created.strftime("%Y-%m-%d %H:%M")
                    else:
                        created_str = str(created or "")
                    items.append({
                        "id": doc.id,
                        "article_slug": d.get("article_slug"),
                        "author_name": d.get("author_name"),
                        "body": d.get("body"),
                        "response": d.get("response"),
                        "status": d.get("status"),
                        "created_at": created_str,
                    })
                return items[:limit]
            except Exception:
                pass

    if _use_sqlite():
        _ensure_sqlite_schema()
        with _sqlite_cursor() as cur:
            cur.execute(
                """
                SELECT id, article_slug, author_name, body, response, status,
                       created_at, moderated_at
                  FROM article_comments
                 WHERE status = ?
                 ORDER BY created_at DESC
                 LIMIT ?
                """,
                (status, limit),
            )
            return [dict(row) for row in cur.fetchall()]

    try:
        db.ensure_schema(SCHEMA)
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT id, article_slug, author_name, body, response, status,
                       created_at, moderated_at
                  FROM article_comments
                 WHERE status = %s
                 ORDER BY created_at DESC
                 LIMIT %s
                """,
                (status, limit),
            )
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception:
        _ensure_sqlite_schema()
        with _sqlite_cursor() as cur:
            cur.execute(
                """
                SELECT id, article_slug, author_name, body, response, status,
                       created_at, moderated_at
                  FROM article_comments
                 WHERE status = ?
                 ORDER BY created_at DESC
                 LIMIT ?
                """,
                (status, limit),
            )
            return [dict(row) for row in cur.fetchall()]


def status_counts() -> dict[str, int]:
    """Pending/published/rejected counts for admin tabs."""
    counts = {s: 0 for s in STATUSES}

    if _use_firestore():
        fs = _get_firestore_client()
        if fs is not None:
            try:
                for doc in fs.collection("comments").stream():
                    st = doc.to_dict().get("status")
                    if st in counts:
                        counts[st] += 1
                return counts
            except Exception:
                pass

    if _use_sqlite():
        _ensure_sqlite_schema()
        with _sqlite_cursor() as cur:
            cur.execute("SELECT status, count(*) FROM article_comments GROUP BY status")
            for row in cur.fetchall():
                if row[0] in counts:
                    counts[row[0]] = int(row[1])
            return counts

    try:
        db.ensure_schema(SCHEMA)
        with db.cursor() as cur:
            cur.execute("SELECT status, count(*) FROM article_comments GROUP BY status")
            for status, count in cur.fetchall():
                if status in counts:
                    counts[status] = int(count)
            return counts
    except Exception:
        _ensure_sqlite_schema()
        with _sqlite_cursor() as cur:
            cur.execute("SELECT status, count(*) FROM article_comments GROUP BY status")
            for row in cur.fetchall():
                if row[0] in counts:
                    counts[row[0]] = int(row[1])
            return counts


def moderate(
    comment_id: Any,
    *,
    status: str,
    response: str | None = None,
) -> None:
    """Move a comment through the moderation lifecycle."""
    if status not in STATUSES:
        raise ValueError(f"Unknown status: {status}")

    clean_response = _clean(response, MAX_RESPONSE) or None

    if _use_firestore():
        fs = _get_firestore_client()
        if fs is not None:
            try:
                fs.collection("comments").document(str(comment_id)).update({
                    "status": status,
                    "response": clean_response,
                    "moderated_at": datetime.now(),
                })
                return
            except Exception:
                pass

    if _use_sqlite():
        _ensure_sqlite_schema()
        with _sqlite_cursor() as cur:
            cur.execute(
                """
                UPDATE article_comments
                   SET status = ?, response = ?, moderated_at = CURRENT_TIMESTAMP
                 WHERE id = ?
                """,
                (status, clean_response, comment_id),
            )
        return

    try:
        db.ensure_schema(SCHEMA)
        with db.cursor() as cur:
            cur.execute(
                """
                UPDATE article_comments
                   SET status = %s,
                       response = %s,
                       moderated_at = now()
                 WHERE id = %s
                """,
                (status, clean_response, comment_id),
            )
    except Exception:
        _ensure_sqlite_schema()
        with _sqlite_cursor() as cur:
            cur.execute(
                """
                UPDATE article_comments
                   SET status = ?, response = ?, moderated_at = CURRENT_TIMESTAMP
                 WHERE id = ?
                """,
                (status, clean_response, comment_id),
            )


def delete(comment_id: Any) -> None:
    """Permanently remove a comment."""
    if _use_firestore():
        fs = _get_firestore_client()
        if fs is not None:
            try:
                fs.collection("comments").document(str(comment_id)).delete()
                return
            except Exception:
                pass

    if _use_sqlite():
        _ensure_sqlite_schema()
        with _sqlite_cursor() as cur:
            cur.execute("DELETE FROM article_comments WHERE id = ?", (comment_id,))
        return

    try:
        db.ensure_schema(SCHEMA)
        with db.cursor() as cur:
            cur.execute("DELETE FROM article_comments WHERE id = %s", (comment_id,))
    except Exception:
        _ensure_sqlite_schema()
        with _sqlite_cursor() as cur:
            cur.execute("DELETE FROM article_comments WHERE id = ?", (comment_id,))
