"""
data_updater.py
---------------
The single function responsible for keeping the dataset current.

`update_data()` is the one entry point everything else calls -- the CLI, the
Flask app's refresh endpoint, and the optional `watch()` loop. It is safe to
call as often as you like: it first asks CVoter what its latest data date is
(one small request), and does nothing further unless there is genuinely
something new, or `force=True` is passed.

What a real update does, in order:

    1. probe   -- read the latest timestamp from one endpoint
    2. fetch   -- pull all 41 option-level series
    3. merge   -- union new rows onto the existing history, new values winning
                  on overlapping dates (CVoter revises recent days)
    4. write   -- atomically, via a temp file + replace, so a crash mid-write
                  cannot leave a truncated CSV behind
    5. derive  -- recompute the composite sentiment index, refit the
                  calibration, and regenerate the daily projections
    6. record  -- write data/update_status.json

Every stage is reported in the returned dict, so a caller can tell the
difference between "checked, nothing new", "updated", and "failed".
"""

import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone

import pandas as pd

from app.elections.engine.paths import DATA_DIR

from app.elections.engine.tracker_schema import BASE_URL, TRACKER_SCHEMA

MASTER_CSV = "cvoter_daily_trackers.csv"
LONG_CSV = "cvoter_metrics_long.csv"
PROJECTIONS_CSV = "ideal_model_daily_projections.csv"
STATUS_FILE = "update_status.json"

# Endpoint used for the cheap "is there anything new?" probe. Tracker 6 option 0
# is one of the series that runs the full length of the history.
PROBE_ENDPOINT = f"{BASE_URL}/t140.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write_csv(df, path):
    """Writes a CSV via temp file + os.replace so readers never see a partial file."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=directory)
    os.close(fd)
    try:
        df.to_csv(tmp_path, index=False)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def remote_latest_date(timeout=3):
    """Latest data date CVoter is currently publishing, as 'YYYY-MM-DD'."""
    import requests

    resp = requests.get(
        PROBE_ENDPOINT,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json,*/*"},
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict) or not payload:
        raise RuntimeError("Unexpected probe payload shape")

    latest_ms = max(float(k) for k in payload.keys())
    return datetime.fromtimestamp(latest_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")


def local_latest_date(data_dir=DATA_DIR):
    """Latest date present in the local master CSV, or None if there is none."""
    path = os.path.join(data_dir, MASTER_CSV)
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, usecols=["date"])
    except (ValueError, pd.errors.EmptyDataError):
        return None
    return str(df["date"].max()) if len(df) else None


def read_status(data_dir=DATA_DIR):
    """Last recorded update status, or an empty dict."""
    path = os.path.join(data_dir, STATUS_FILE)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def _write_status(data_dir, status):
    with open(os.path.join(data_dir, STATUS_FILE), "w", encoding="utf-8") as fh:
        json.dump(status, fh, indent=2)


def data_status(data_dir=DATA_DIR, check_remote=True):
    """
    Freshness report without touching anything. Cheap enough to call per request.
    """
    local = local_latest_date(data_dir)
    status = {
        "local_latest_date": local,
        "last_update": read_status(data_dir).get("finished_at"),
        "master_csv_exists": os.path.exists(os.path.join(data_dir, MASTER_CSV)),
    }

    if check_remote:
        try:
            remote = remote_latest_date()
            status["remote_latest_date"] = remote
            status["is_stale"] = bool(local is None or remote > local)
            status["days_behind"] = (
                (pd.to_datetime(remote) - pd.to_datetime(local)).days if local else None
            )
        except Exception as err:  # noqa: BLE001 - network state is informational
            status["remote_latest_date"] = None
            status["remote_error"] = str(err)
            status["is_stale"] = None

    return status


def _merge_history(existing, incoming):
    """
    Unions incoming rows onto existing history, keyed on date.

    Incoming values win wherever the two overlap, because CVoter restates the
    most recent days as late responses land. Columns present in only one frame
    are kept.
    """
    if existing is None or existing.empty:
        return incoming.sort_values("date").reset_index(drop=True)

    combined = pd.concat([existing, incoming], ignore_index=True, sort=False)
    combined = combined.sort_values("date")
    # groupby.last() keeps the newest non-null value per column per date.
    merged = combined.groupby("date", as_index=False).last()
    return merged.sort_values("date").reset_index(drop=True)


# ---------------------------------------------------------------------------
# The update function
# ---------------------------------------------------------------------------

def update_data(data_dir=DATA_DIR, force=False, rebuild_derived=True, verbose=True):
    """
    Brings the local dataset up to date with cvoterindia.com.

    Parameters
    ----------
    data_dir : str
        Directory holding the CSVs and status file.
    force : bool
        Refetch even when the probe says there is nothing new. Use after
        changing the schema or the weights.
    rebuild_derived : bool
        Also refit the calibration and regenerate the daily projections.
    verbose : bool
        Print progress.

    Returns
    -------
    dict with keys:
        status        'updated' | 'up_to_date' | 'failed'
        reason        short explanation
        rows_before / rows_after / new_rows
        local_latest_date / remote_latest_date
        started_at / finished_at / duration_seconds
        derived       what was regenerated (when rebuild_derived)
        error         present only on failure
    """
    os.makedirs(data_dir, exist_ok=True)
    started = time.time()
    report = {"started_at": _now_iso(), "forced": bool(force)}

    def finish(**extra):
        report.update(extra)
        report["finished_at"] = _now_iso()
        report["duration_seconds"] = round(time.time() - started, 2)
        _write_status(data_dir, report)
        return report

    # 1. Probe -------------------------------------------------------------
    local = local_latest_date(data_dir)
    report["local_latest_date"] = local

    try:
        remote = remote_latest_date()
        report["remote_latest_date"] = remote
    except Exception as err:  # noqa: BLE001 - reported, not raised
        if verbose:
            print(f"Probe failed: {err}")
        return finish(status="failed", reason="probe_failed", error=str(err))

    if not force and local is not None and remote <= local:
        if verbose:
            print(f"Already current: local {local}, remote {remote}. Nothing to do.")
        return finish(status="up_to_date", reason="no_new_data", new_rows=0)

    if verbose:
        print(f"New data available: local {local} -> remote {remote}. Fetching...")

    # 2. Fetch -------------------------------------------------------------
    from app.elections.engine.cvoter_scraper import build_catalog, fetch_all_series, long_to_wide

    try:
        long_df = fetch_all_series(verbose=verbose)
        if long_df.empty:
            return finish(status="failed", reason="empty_fetch", error="No series returned")
        wide_df = long_to_wide(long_df)
    except Exception as err:  # noqa: BLE001 - reported, not raised
        if verbose:
            print(f"Fetch failed: {err}")
        return finish(status="failed", reason="fetch_failed", error=str(err))

    # 3. Merge -------------------------------------------------------------
    master_path = os.path.join(data_dir, MASTER_CSV)
    existing = pd.read_csv(master_path) if os.path.exists(master_path) else None
    rows_before = len(existing) if existing is not None else 0
    merged = _merge_history(existing, wide_df)

    # 4. Write -------------------------------------------------------------
    if existing is not None and rows_before:
        backup = os.path.join(data_dir, f"{MASTER_CSV}.bak")
        shutil.copyfile(master_path, backup)

    _atomic_write_csv(merged, master_path)
    _atomic_write_csv(long_df, os.path.join(data_dir, LONG_CSV))

    for tracker_id, meta in TRACKER_SCHEMA.items():
        tracker_slice = long_df[long_df["tracker_id"] == tracker_id]
        if tracker_slice.empty:
            continue
        pivot = tracker_slice.pivot_table(
            index="date", columns="metric_name", values="value", aggfunc="last"
        ).reset_index().sort_values("date")
        clean = meta["name"].lower().replace(" ", "_").replace("/", "_")
        _atomic_write_csv(pivot, os.path.join(data_dir, f"tracker_{tracker_id}_{clean}.csv"))

    with open(os.path.join(data_dir, "cvoter_metrics_catalog.json"), "w", encoding="utf-8") as fh:
        json.dump(build_catalog(long_df), fh, indent=2)

    # 5. Derive ------------------------------------------------------------
    derived = {}
    if rebuild_derived:
        try:
            from app.elections.engine.calibration import calibrate
            from app.elections.engine.daily_predictor import run_daily_predictions

            calibration = calibrate(df=merged, data_dir=data_dir, write=True)
            derived["calibration"] = {
                "cube_exponent": calibration["cube_exponent"],
                "slope": calibration["vote_share_model"]["slope"],
                "intercept": calibration["vote_share_model"]["intercept"],
            }

            projections = run_daily_predictions(data_dir=data_dir, output_dir=data_dir, verbose=verbose)
            derived["projections_rows"] = int(len(projections))
            derived["latest_nda_seats"] = int(projections["NDA_proj_seats"].iloc[-1])

            from app.elections.engine.precompute import precompute_all

            precompute_all(data_dir=data_dir, verbose=verbose)
        except Exception as err:  # noqa: BLE001 - data itself is already saved
            derived["error"] = str(err)
            if verbose:
                print(f"Derived rebuild failed (raw data is saved): {err}")

    new_rows = len(merged) - rows_before
    if verbose:
        print(f"Updated: {rows_before} -> {len(merged)} rows (+{new_rows}), through {merged['date'].max()}")

    return finish(
        status="updated",
        reason="forced_refresh" if (force and local == remote) else "new_data",
        rows_before=rows_before,
        rows_after=int(len(merged)),
        new_rows=int(new_rows),
        metrics=int(len(merged.columns) - 1),
        local_latest_date=str(merged["date"].max()),
        derived=derived,
    )


def watch(interval_seconds=3600, data_dir=DATA_DIR, max_iterations=None, verbose=True):
    """
    Polls for new data on a fixed interval, calling `update_data` each time.

    Intended for running as a background service or a scheduled job. Errors are
    logged and the loop continues, so one bad night does not stop the watcher.
    """
    iteration = 0
    while max_iterations is None or iteration < max_iterations:
        iteration += 1
        try:
            result = update_data(data_dir=data_dir, verbose=verbose)
            if verbose:
                print(f"[{_now_iso()}] check #{iteration}: {result['status']} ({result['reason']})")
        except Exception as err:  # noqa: BLE001 - watcher must survive
            print(f"[{_now_iso()}] check #{iteration} raised: {err}")

        if max_iterations is not None and iteration >= max_iterations:
            break
        time.sleep(interval_seconds)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Keep the CVoter dataset up to date.")
    parser.add_argument("--force", action="store_true", help="refetch even if nothing is new")
    parser.add_argument("--status", action="store_true", help="report freshness and exit")
    parser.add_argument("--watch", type=int, metavar="SECONDS",
                        help="poll on this interval instead of running once")
    parser.add_argument("--data-dir", default=DATA_DIR)
    args = parser.parse_args()

    if args.status:
        print(json.dumps(data_status(data_dir=args.data_dir), indent=2))
    elif args.watch:
        watch(interval_seconds=args.watch, data_dir=args.data_dir)
    else:
        print(json.dumps(update_data(data_dir=args.data_dir, force=args.force), indent=2))
