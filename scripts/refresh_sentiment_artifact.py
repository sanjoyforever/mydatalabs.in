#!/usr/bin/env python3
"""Refresh only the perception/vote figures inside a precomputed artifact.

`update_data.py` rebuilds the whole hormuz-index artifact, which also re-sweeps
yfinance for live component values. That is the right thing on a weekly run and
the wrong thing when the only stale part is the vote aggregate: a failed sweep
carries last week's component readings forward and marks the snapshot degraded,
which is a large side effect for "the vote count is out of date".

This touches the four sentiment keys and nothing else, so it is safe to run any
time the database has moved on but the components have not — in particular
after the database has been unreachable, which bakes `available: false` and
`votes: 0` into the artifact and leaves the server-rendered first paint
claiming nobody has voted until vote.js corrects it.

Usage:
    python scripts/refresh_sentiment_artifact.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, precomputed, votes  # noqa: E402
from app.indices import hormuz  # noqa: E402

SLUG = "hormuz-index"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change without writing")
    args = parser.parse_args()

    if not db.is_configured():
        print("No database configured (set DATABASE_URL). Nothing to refresh.")
        return 1

    artifact = dict(precomputed.load(SLUG))
    if not artifact:
        print(f"No existing {SLUG} artifact to update — run update_data.py first.")
        return 1

    votes.clear_read_cache()
    sentiment = votes.get_summary()
    if not sentiment.get("available"):
        # Same rule the full builder applies: never overwrite good figures with
        # the empty summary an unreachable database returns.
        print("Database read came back unavailable; refusing to blank the artifact.")
        return 1

    history = hormuz.get_history()
    sentiment_history = votes.get_history()
    perception_by_week = {h["week_start"]: h["index"] for h in sentiment_history}

    before = artifact.get("sentiment") or {}
    artifact["sentiment"] = sentiment
    artifact["sentiment_history"] = sentiment_history
    artifact["perception_by_week"] = perception_by_week
    artifact["perception_series"] = [
        perception_by_week.get(h["week_start"]) for h in history
    ]

    print(f"week {sentiment['week_start']}: "
          f"votes {before.get('votes')} -> {sentiment['votes']}, "
          f"index {before.get('index')} -> {sentiment['index']}, "
          f"available {before.get('available')} -> {sentiment['available']}")
    print(f"perception series: {len(sentiment_history)} week(s) with ballots")

    if args.dry_run:
        print("--dry-run: nothing written")
        return 0

    if not precomputed.write(SLUG, artifact):
        print("Could not write the artifact (read-only filesystem?).")
        return 1
    print(f"wrote {precomputed.path_for(SLUG)}")
    print("Commit and push for this to reach the live site.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
