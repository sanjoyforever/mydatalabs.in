#!/usr/bin/env python3
"""MyDataLabs data updater.

Recomputes the index snapshot, appends it to the weekly history, and reports
what actually happened — including whether the write was durable and which
components are running stale. In production/cron mode it then commits the
updated data files and pushes to GitHub, which is what triggers the Vercel
deployment; Vercel's own filesystem is read-only, so a push is the only way a
weekly update actually reaches the live site.

Usage:
    python update_data.py                  # recompute, persist, commit + push
    python update_data.py --local          # recompute and persist; skip git
    python update_data.py --dry-run        # recompute without writing anything
    python update_data.py --stamp-manual   # mark manual inputs as updated today

Before a weekly run, update the "manual_overrides" block in
app/data/hormuz_history.json with this week's ship traffic, war-risk
insurance, tanker freight and reroute figures, and set the matching dates in
"manual_updated" (or pass --stamp-manual to set them all to today).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import storage  # noqa: E402
from app.indices import hormuz  # noqa: E402

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app", "data")


def stamp_manual_dates() -> None:
    """Mark every manual component as updated today."""
    history = storage.load_history(hormuz.INDEX_KEY)
    today = datetime.date.today().isoformat()
    history["manual_updated"] = {k: today for k in hormuz.MANUAL_KEYS}
    storage.save_history(hormuz.INDEX_KEY, history)
    print(f"  Stamped manual components as updated {today}: {sorted(hormuz.MANUAL_KEYS)}")


_MARKET_LABELS = {
    hormuz.COMPONENTS_BY_KEY[k].label
    for k in hormuz.YFINANCE_TICKERS
    if k in hormuz.COMPONENTS_BY_KEY
}


def failed_live_components(snapshot) -> list[str]:
    """Automatic components whose live fetch did not land this run.

    A manual component going stale is expected — it is waiting on a human, and
    the dashboard says so. An automatic one carrying forward is a different
    animal: yfinance returned nothing, and the score is last week's number
    wearing this week's date.

    That distinction matters because the failure is invisible. A crash gets
    noticed; a silently carried-forward price looks exactly like a quiet
    market. Brent, TTF and VIX sat frozen for a month behind a dashboard that
    looked fine, because every layer here degrades politely: a missing
    yfinance returns all-None, a failed fetch returns None per ticker, and
    compute_snapshot turns None into "keep last week's value".
    """
    return [
        cr.component.label
        for cr in snapshot.components
        if not cr.component.manual and cr.carried_forward
    ]


def update_index(persist: bool) -> int:
    print("=" * 62)
    print("Hormuz Crisis Index (HMX-INDEX)")
    # Computed without persisting first, so a failed live sweep can be caught
    # before it is written to history. The values are cached for
    # LIVE_CACHE_TTL_SECONDS, so the persisting call below reuses this run's
    # fetch rather than going back out to yfinance.
    #
    # allow_network=True: this is the one place that is supposed to wait on
    # yfinance. Every page render reads what this run writes.
    snapshot = hormuz.compute_snapshot(persist=False, allow_network=True)

    failed = failed_live_components(snapshot)
    if failed:
        print(f"\n  ERROR: the live sweep returned nothing for {len(failed)} automatic"
              f" component(s):", file=sys.stderr)
        for label in failed:
            print(f"    - {label}", file=sys.stderr)
        print("\n  These would be published as this week's reading while actually"
              " holding\n  the previous week's value. Refusing to write or deploy.",
              file=sys.stderr)
        market = [c for c in failed if c in _MARKET_LABELS]
        transits = [c for c in failed if c not in _MARKET_LABELS]
        if market:
            print("\n  For the market components: yfinance may not be installed in this"
                  "\n  interpreter, or may be too old for Yahoo's current API (see"
                  " requirements-pipeline.txt).", file=sys.stderr)
        if transits:
            print("\n  For the transit components: IMF PortWatch was unreachable, or has"
                  "\n  published no complete Mon-Sun week inside the lookback window.",
                  file=sys.stderr)
        return 1

    if persist:
        snapshot = hormuz.compute_snapshot(persist=True, allow_network=True)

    print(f"  Week of {snapshot.week_start}: {snapshot.score:.1f} ({snapshot.level_label})")
    print(f"  Storage: {storage.storage_backend()}")

    print("\n  Components:")
    for cr in snapshot.components:
        flags = []
        if cr.stale:
            flags.append("STALE")
        if cr.carried_forward:
            flags.append("carried forward")
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        value = f"{cr.current_value:.2f}" if cr.current_value is not None else "—"
        print(
            f"    {cr.component.label:<28} {value:>10} {cr.component.unit:<14}"
            f" stress={cr.stress:5.1f}  +{cr.contribution:5.2f}{suffix}"
        )

    if snapshot.degraded:
        print(
            f"\n  WARNING: {snapshot.stale_weight * 100:.0f}% of index weight is stale."
            " This week's score is provisional."
        )

    # Rebuild the per-route artifacts the site serves. Without this the pages
    # keep rendering the previous run's live values and perception series.
    #
    # Skipped on a dry run: build_all writes app/data/precomputed/*.json, so
    # running it here made --dry-run modify tracked files while printing
    # "nothing written". A dry run that edits the working tree is worse than no
    # dry run, because it is trusted.
    if persist:
        print("\n  Precomputing route artifacts:")
        from app import precomputed
        precomputed.build_all(verbose=True)
    else:
        print("\n  Skipping precompute (dry run writes no artifacts).")

    if persist:
        if snapshot.persisted:
            print(f"\n  Persisted. History now has {len(hormuz.get_history())} weekly snapshots.")
        else:
            print(
                "\n  WARNING: the write did NOT land anywhere durable."
                " Set HISTORY_DATA_DIR to a writable volume, or run this locally"
                " and commit app/data/hormuz_history.json."
            )
            return 1
    else:
        print("\n  Dry run — nothing written.")
    return 0


def report_incident_dataset() -> None:
    print("=" * 62)
    print("Vessel incident dataset")
    path = os.path.join(DATA_DIR, "vessel_attacks.json")
    if not os.path.exists(path):
        print("  WARNING: vessel_attacks.json not found.")
        return
    with open(path, "r", encoding="utf-8") as f:
        rows = json.load(f)
    print(f"  {len(rows)} records. Compiled separately from the index; contributes"
          " nothing to the composite score and is not served by the API.")


# push_to_github() lived here. It is now push_to_prod.py, so that publishing is
# a separate, deliberate command rather than a flag on the updater — and so the
# "only ever add the data paths, never `git add .`" rule has a single home.


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="recompute without writing anything")
    parser.add_argument("--local", "-l", action="store_true",
                        help="persist locally but skip the git commit + push")
    parser.add_argument("--stamp-manual", action="store_true",
                        help="mark all manual components as updated today, then run")
    args = parser.parse_args()

    mode = "DRY RUN" if args.dry_run else ("LOCAL (git push skipped)" if args.local else "PRODUCTION / CRON (git push)")
    print(f"MyDataLabs data update — {datetime.datetime.now().isoformat(timespec='seconds')}")
    print(f"Mode: {mode}")
    if args.stamp_manual:
        stamp_manual_dates()

    code = update_index(persist=not args.dry_run)
    report_incident_dataset()

    if code == 0 and not args.dry_run and not args.local:
        # Publishing moved to push_to_prod.py. This path is kept so the
        # documented `python update_data.py` invocation still deploys, but the
        # git logic now lives in one place instead of two.
        from push_to_prod import push_to_prod
        code = push_to_prod()

    print("=" * 62)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
