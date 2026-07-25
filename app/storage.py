"""Read/write the weekly history JSON.

On Vercel's serverless runtime the filesystem is read-only outside /tmp, so
writes from the cron route only persist for that instance. Durable persistence
needs Vercel Blob or a real DB (see README) — the abstraction is isolated here
so swapping the backend later only touches this file.
"""
from __future__ import annotations

import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def _path(index_key: str) -> str:
    return os.path.join(DATA_DIR, f"{index_key}_history.json")


def load_history(index_key: str) -> dict:
    path = _path(index_key)
    if not os.path.exists(path):
        return {"weeks": [], "manual_overrides": {}}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_history(index_key: str, data: dict) -> None:
    path = _path(index_key)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def latest_manual_values(index_key: str) -> dict[str, float]:
    history = load_history(index_key)
    return history.get("manual_overrides", {})
