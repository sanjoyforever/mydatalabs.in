"""Read/write the weekly history JSON.

Storage backend resolution, in order:

1. ``HISTORY_DATA_DIR`` env var, if set and writable — point this at a mounted
   volume (Docker / Cloud Run) for durable persistence.
2. The bundled ``app/data`` directory, if writable — this is the case for local
   development and any container with a writable layer.
3. ``/tmp`` — the only writable path on Vercel's serverless runtime. Writes here
   survive only for the life of the instance.

Reads always prefer the writable location and fall back to the bundled seed
data, so a fresh instance serves the committed history until the cron job
refreshes it.

``is_durable()`` reports whether writes will actually outlive the process, so
callers can tell the truth instead of returning 200 for a write that evaporated.
"""
from __future__ import annotations

import json
import os
import tempfile

BUNDLED_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def _dir_is_writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write-probe")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def _resolve_write_dir() -> tuple[str, bool]:
    """Return (directory, durable)."""
    configured = os.environ.get("HISTORY_DATA_DIR")
    if configured and _dir_is_writable(configured):
        return configured, True
    if _dir_is_writable(BUNDLED_DATA_DIR):
        return BUNDLED_DATA_DIR, True
    fallback = os.path.join(tempfile.gettempdir(), "mydatalabs-history")
    _dir_is_writable(fallback)
    return fallback, False


WRITE_DIR, DURABLE = _resolve_write_dir()


def is_durable() -> bool:
    """True when a write will still be there after this process exits."""
    return DURABLE


def storage_backend() -> str:
    """Human-readable description of where history is being written."""
    return f"{WRITE_DIR} ({'durable' if DURABLE else 'ephemeral — instance-local only'})"


def _write_path(index_key: str) -> str:
    return os.path.join(WRITE_DIR, f"{index_key}_history.json")


def _bundled_path(index_key: str) -> str:
    return os.path.join(BUNDLED_DATA_DIR, f"{index_key}_history.json")


def load_history(index_key: str) -> dict:
    for path in (_write_path(index_key), _bundled_path(index_key)):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, ValueError):
                continue
    return {"weeks": [], "manual_overrides": {}}


def save_history(index_key: str, data: dict) -> bool:
    """Persist history. Returns True if the write landed somewhere durable."""
    path = _write_path(index_key)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        return False
    return DURABLE


def latest_manual_values(index_key: str) -> dict[str, float]:
    history = load_history(index_key)
    return history.get("manual_overrides", {})
