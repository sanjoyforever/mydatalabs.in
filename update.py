#!/usr/bin/env python3
"""
update.py — refresh every data point behind every page. One command.

    python update.py

That is the whole workflow. It updates both live indices and rebuilds every
precomputed artifact the site renders from:

    Hormuz Crisis Index   /hormuz-index
      - yfinance sweep (Brent, TTF gas, VIX)
      - manual overrides merged, composite scored, weekly history appended
      - vessel incident dataset reported

    Lok Sabha Projection  /lok-sabha-index
      - CVoter tracker fetch (41 option-level series), if anything is new
      - calibration refit, daily projections rebuilt
      - overview / trend_analytics / events / backtest / insights JSON

    Per-route artifacts   app/data/precomputed/
      - one JSON per route, so a page render never touches the network or a
        database. See app/precomputed.py for why.

It writes to the working tree and nothing else. Publishing is a separate,
deliberate step:

    python push_to_prod.py

The split is the point. Updating is safe and repeatable and you may want to
eyeball the numbers before the world sees them; pushing is irreversible in the
sense that it deploys. Bundling them meant every dry run was one flag away
from a live deploy.

Options
-------
    python update.py                  update everything
    python update.py --hormuz         Hormuz index only
    python update.py --elections      Lok Sabha projection only
    python update.py --check          report freshness of both, write nothing
    python update.py --dry-run        recompute without persisting
    python update.py --force          refetch even if the source has nothing new
    python update.py --stamp-manual   mark manual Hormuz components as updated today
    python update.py --quiet          print only on a real change or an error

Exit codes
----------
    0  everything updated, or already current
    1  at least one index failed
"""

import argparse
import datetime
import os
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

SEP = "=" * 66


def _hr(title: str) -> None:
    print(SEP)
    print(title)
    print(SEP)


# --- Hormuz ----------------------------------------------------------------


def update_hormuz(dry_run: bool = False, stamp_manual: bool = False) -> int:
    """Refresh the Hormuz Crisis Index. Returns 0 on success."""
    import update_data

    if stamp_manual:
        update_data.stamp_manual_dates()

    code = update_data.update_index(persist=not dry_run)
    update_data.report_incident_dataset()
    return code


# --- Lok Sabha -------------------------------------------------------------


def update_elections(dry_run: bool = False, force: bool = False, quiet: bool = False) -> int:
    """Refresh the Lok Sabha projection. Returns 0 on success or already-current."""
    from app.elections.engine.data_updater import update_data as update_cvoter
    from app.elections.engine.paths import DATA_DIR

    _hr("Lok Sabha Projection Engine (LS-PROJ)")

    if dry_run:
        from app.elections.engine.data_updater import data_status
        status = data_status(data_dir=DATA_DIR)
        print(f"  Local  : {status.get('local_latest_date') or 'no data'}")
        print(f"  Source : {status.get('remote_latest_date') or 'unreachable'}")
        print("  Dry run — nothing written.")
        return 0

    result = update_cvoter(data_dir=DATA_DIR, force=force, rebuild_derived=True, verbose=not quiet)

    if result["status"] == "failed":
        # Always printed, even under --quiet: a silent failure on a schedule
        # means stale numbers going unnoticed for days.
        print(f"  FAILED ({result['reason']}): {result.get('error')}", file=sys.stderr)
        print(f"  Local data remains at {result.get('local_latest_date')}.", file=sys.stderr)
        return 1

    if result["status"] == "up_to_date":
        print(f"  Already current through {result['local_latest_date']}. Nothing to do.")
        return 0

    derived = result.get("derived", {})
    print(f"  Updated through {result['local_latest_date']}")
    print(f"    rows        : {result['rows_before']} -> {result['rows_after']} (+{result['new_rows']})")
    print(f"    metrics     : {result['metrics']} labelled series")
    if "calibration" in derived:
        cal = derived["calibration"]
        print(f"    calibration : k={cal['cube_exponent']}, slope={cal['slope']}")
    if "latest_nda_seats" in derived:
        print(f"    projection  : NDA {derived['latest_nda_seats']} seats")
    if "error" in derived:
        print(f"    WARNING     : raw data saved but the rebuild failed — {derived['error']}")
        return 1
    return 0


# --- Freshness -------------------------------------------------------------


def check_freshness() -> int:
    """Report where both datasets stand without writing anything."""
    from app.elections.engine.data_updater import data_status
    from app.elections.engine.paths import DATA_DIR
    from app.indices import hormuz

    _hr("Freshness check — no writes")

    history = hormuz.get_history()
    last_week = history[-1]["week_start"] if history else "none"
    print(f"  Hormuz    : {len(history)} weekly snapshots, latest {last_week}")

    status = data_status(data_dir=DATA_DIR)
    local = status.get("local_latest_date") or "no data"
    remote = status.get("remote_latest_date") or "unreachable"
    print(f"  Lok Sabha : local {local}, source {remote}")
    if status.get("is_stale"):
        print(f"              {status.get('days_behind')} day(s) behind — run `python update.py`.")
    elif status.get("is_stale") is False:
        print("              current.")
    else:
        print(f"              could not reach the source. {status.get('remote_error', '')}")
    return 0


# --- Entry point -----------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh every data point behind every page.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--hormuz", action="store_true", help="Hormuz Crisis Index only")
    parser.add_argument("--elections", action="store_true", help="Lok Sabha projection only")
    parser.add_argument("--check", action="store_true", help="report freshness and exit, no writes")
    parser.add_argument("--dry-run", action="store_true", help="recompute without persisting")
    parser.add_argument("--force", action="store_true",
                        help="refetch even if the source has nothing new")
    parser.add_argument("--stamp-manual", action="store_true",
                        help="mark manual Hormuz components as updated today")
    parser.add_argument("--quiet", action="store_true",
                        help="print only on a real change or an error")
    args = parser.parse_args()

    if args.check:
        return check_freshness()

    # Neither flag means both, which is the normal case.
    do_hormuz = args.hormuz or not args.elections
    do_elections = args.elections or not args.hormuz

    started = datetime.datetime.now()
    print(f"MyDataLabs data update — {started.isoformat(timespec='seconds')}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'WRITE (no git push — run push_to_prod.py to publish)'}")

    failures = []

    if do_hormuz:
        try:
            if update_hormuz(dry_run=args.dry_run, stamp_manual=args.stamp_manual) != 0:
                failures.append("hormuz")
        except Exception as err:  # noqa: BLE001 - one index must not stop the other
            print(f"  ERROR: Hormuz update raised: {err}", file=sys.stderr)
            failures.append("hormuz")

    if do_elections:
        try:
            if update_elections(dry_run=args.dry_run, force=args.force, quiet=args.quiet) != 0:
                failures.append("elections")
        except Exception as err:  # noqa: BLE001
            print(f"  ERROR: Lok Sabha update raised: {err}", file=sys.stderr)
            failures.append("elections")

    # Route artifacts last: they read what the two updates above just wrote.
    # update_hormuz() already rebuilds them via update_data.update_index(), but
    # an elections-only run would otherwise leave the home page's Lok Sabha
    # card reporting the previous seat count.
    if not args.dry_run and do_elections:
        _hr("Per-route precomputed artifacts")
        try:
            from app import precomputed
            precomputed.build_all(verbose=True)
        except Exception as err:  # noqa: BLE001
            print(f"  ERROR: precompute failed: {err}", file=sys.stderr)
            failures.append("precompute")

    elapsed = (datetime.datetime.now() - started).total_seconds()
    print(SEP)
    if failures:
        print(f"FAILED: {', '.join(failures)}  ({elapsed:.1f}s)")
        return 1
    print(f"All data current. ({elapsed:.1f}s)")
    if not args.dry_run:
        print("Publish with: python push_to_prod.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
