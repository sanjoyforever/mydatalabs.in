#!/usr/bin/env python
"""
scripts/update_elections.py
---------------------------
The one command to run when you want the Lok Sabha dashboard to show fresh
numbers.

    python scripts/update_elections.py

That is the whole workflow. It checks whether CVoter has published anything
new, and if so pulls it, refits the model, rebuilds every derived file, and
prints what changed. If nothing is new it says so and exits without touching
anything, so it is safe to run on a timer.

Why this exists separately from scripts/elections_pipeline.py: that one is the
full analytical pipeline with backtests and charts, useful when you are working
on the model. This is the operational one — the thing you put in Task Scheduler
or cron and forget about. It is the elections counterpart of
scripts/update_hormuz.py.

Options
-------
    python scripts/update_elections.py            update if there is new data
    python scripts/update_elections.py --force    refetch and rebuild even if
                                                  nothing is new (use after
                                                  changing weights or schema)
    python scripts/update_elections.py --check    report freshness and exit
    python scripts/update_elections.py --quiet    print only on a real change
                                                  or an error

Scheduling
----------
Windows Task Scheduler, daily at 07:30:

    schtasks /create /tn "LokSabhaProjection" /tr ^
      "C:\\Path\\To\\python.exe C:\\Path\\To\\mydatalabs-in\\scripts\\update_elections.py --quiet" ^
      /sc daily /st 07:30

cron, daily at 07:30:

    30 7 * * * cd /path/to/mydatalabs-in && /usr/bin/python3 scripts/update_elections.py --quiet

The web app picks up new data automatically: its cache is keyed on the CSV
modification times, so the next request after an update rebuilds everything.
No restart is needed.

Exit codes
----------
    0  updated, or already current
    1  the update failed (network, parse, or rebuild error)
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.elections.engine.data_updater import data_status, update_data  # noqa: E402
from app.elections.engine.paths import DATA_DIR  # noqa: E402


def run_update(force=False, quiet=False, data_dir=DATA_DIR):
    """
    Brings the dataset and every derived file up to date.

    Returns the report dict from data_updater.update_data.
    """
    def say(*args):
        if not quiet:
            print(*args)

    say("=" * 62)
    say("  Lok Sabha Projection Engine -- data update")
    say("=" * 62)

    result = update_data(data_dir=data_dir, force=force, rebuild_derived=True, verbose=not quiet)

    if result["status"] == "failed":
        # Always print failures, even under --quiet: a silent failure on a
        # schedule means stale numbers going unnoticed for days.
        print(f"FAILED ({result['reason']}): {result.get('error')}", file=sys.stderr)
        print(f"Local data remains at {result.get('local_latest_date')}.", file=sys.stderr)
        return result

    if result["status"] == "up_to_date":
        say(f"\nAlready current through {result['local_latest_date']}. Nothing to do.")
        return result

    derived = result.get("derived", {})
    lines = [
        "",
        f"Updated through {result['local_latest_date']}",
        f"  rows        : {result['rows_before']} -> {result['rows_after']} (+{result['new_rows']})",
        f"  metrics     : {result['metrics']} labelled series",
        f"  duration    : {result['duration_seconds']}s",
    ]
    if "calibration" in derived:
        cal = derived["calibration"]
        lines.append(f"  calibration : k={cal['cube_exponent']}, slope={cal['slope']}")
    if "latest_nda_seats" in derived:
        lines.append(f"  projection  : NDA {derived['latest_nda_seats']} seats")
    if "error" in derived:
        lines.append(f"  WARNING     : raw data saved but the rebuild failed -- {derived['error']}")

    # A real change is worth printing even under --quiet.
    print("\n".join(lines))
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Update the Lok Sabha projection dataset and all derived files.",
    )
    parser.add_argument("--force", action="store_true",
                        help="refetch and rebuild even if the source has nothing new")
    parser.add_argument("--check", action="store_true",
                        help="report freshness and exit without writing anything")
    parser.add_argument("--quiet", action="store_true",
                        help="print only on a real change or an error (for scheduled runs)")
    parser.add_argument("--data-dir", default=DATA_DIR)
    args = parser.parse_args()

    if args.check:
        status = data_status(data_dir=args.data_dir)
        local = status.get("local_latest_date") or "no data"
        remote = status.get("remote_latest_date") or "unreachable"
        print(f"Local  : {local}")
        print(f"Source : {remote}")
        if status.get("is_stale"):
            print(f"Status : {status.get('days_behind')} day(s) behind. Run without --check.")
        elif status.get("is_stale") is False:
            print("Status : current.")
        else:
            print(f"Status : could not reach the source. {status.get('remote_error', '')}")
        return 0

    result = run_update(force=args.force, quiet=args.quiet, data_dir=args.data_dir)
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
