"""Postgres connection handling for everything that outlives a request.

The index itself is a file-backed JSON series (see ``storage.py``) — this
module exists for the data that genuinely needs a shared, concurrent, durable
store: community sentiment votes today, and whatever comes after.

Connections are opened per operation rather than pooled in-process. The site
runs on serverless/Cloud Run instances that are frequently frozen or recycled,
where a long-lived pool goes stale between invocations; the configured Neon
endpoint is the ``-pooler`` host, so PgBouncer already does the pooling on the
other side of the wire.

The DSN is read from ``DATABASE_URL``, falling back to ``db`` because that is
the key the local ``.env`` uses. If neither is set the module degrades quietly:
``is_configured()`` returns False and callers surface a disabled feature rather
than a 500.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager

try:  # psycopg is optional so the site still boots without the DB extra
    import psycopg
except ImportError:  # pragma: no cover - exercised only on a partial install
    psycopg = None  # type: ignore[assignment]

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


CONNECT_TIMEOUT = int(os.environ.get("DB_CONNECT_TIMEOUT", "10"))

_schema_lock = threading.Lock()
_schema_ready = False


def dsn() -> str | None:
    return os.environ.get("DATABASE_URL") or os.environ.get("db") or None


def is_configured() -> bool:
    return bool(dsn()) and psycopg is not None


@contextmanager
def connection():
    """Yield a connection, committing on clean exit and rolling back on error."""
    if not is_configured():
        raise RuntimeError("No database configured (set DATABASE_URL)")
    conn = psycopg.connect(dsn(), connect_timeout=CONNECT_TIMEOUT)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


@contextmanager
def cursor():
    with connection() as conn:
        with conn.cursor() as cur:
            yield cur


def ensure_schema(ddl_statements: list[str]) -> None:
    """Run idempotent DDL once per process.

    Cheaper and less error-prone than a migration tool for a site with one
    table, and it means a fresh Neon database or a fresh deploy is usable
    without a manual bootstrap step. Every statement must be ``IF NOT EXISTS``
    shaped so repeated runs are free.
    """
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        with cursor() as cur:
            for statement in ddl_statements:
                cur.execute(statement)
        _schema_ready = True
