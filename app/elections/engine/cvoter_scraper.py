"""
cvoter_scraper.py
-----------------
Extracts every option-level daily survey series from cvoterindia.com.

CVoter serves each answer option of each tracker as its own JSON file at
https://cvoterindia.com/chartdata/<prefix><option_index>.json, in the form
{"<epoch_ms>": <percent>, ...}. The full battery is 41 series across 7
trackers, each ~2,770 daily points running from 2019-01-01 to the present.

The previous version of this scraper fetched only the first option of each
tracker and wrote it out as "<Tracker> - Index Value", losing every answer
label. This version walks the schema in tracker_schema.py and captures all
41 labelled series.

Fetching is plain HTTP (requests) -- the endpoints are static JSON with no
auth, no cookies and no JS gate, so driving a headless browser was pure
overhead. Selenium is retained only as a fallback for the case where direct
requests are blocked (e.g. by an intermediary), in which case the same fetches
are issued from inside a browser page context.

Outputs (in `output_dir`):
    cvoter_metrics_long.csv     tidy long format, one row per date x metric
    cvoter_daily_trackers.csv   wide format, one column per option series
    tracker_<id>_<name>.csv     per-tracker wide slice
    cvoter_metrics_catalog.json schema + weights + coverage per series
"""

import io
import json
import os
import time
from datetime import datetime, timezone

import pandas as pd

from app.elections.engine.paths import DATA_DIR

from app.elections.engine.tracker_schema import (
    TRACKER_SCHEMA,
    iter_series,
    total_series_count,
)

CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF = 1.5


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

def _http_get_json(url, session=None):
    """Fetches one chartdata JSON file over plain HTTP, with retries."""
    import requests

    sess = session or requests.Session()
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = sess.get(
                url,
                headers={"User-Agent": CHROME_USER_AGENT, "Accept": "application/json,*/*"},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            payload = resp.json()
            # A few endpoints return a JSON-encoded string containing JSON.
            if isinstance(payload, str):
                payload = json.loads(payload)
            return payload
        except Exception as err:  # noqa: BLE001 - retried below, reported by caller
            last_err = err
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF ** attempt)
    raise RuntimeError(f"GET {url} failed after {MAX_RETRIES} attempts: {last_err}")


def _setup_selenium(headless=True):
    """Fallback transport: headless Chrome used only if direct HTTP fails."""
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument(f"user-agent={CHROME_USER_AGENT}")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.set_script_timeout(REQUEST_TIMEOUT)
    driver.get("https://cvoterindia.com/")
    time.sleep(3)
    return driver


def _browser_get_json(driver, url):
    """Issues the fetch from inside the page's own origin."""
    script = """
    var done = arguments[arguments.length - 1];
    fetch(arguments[0])
        .then(r => r.text())
        .then(t => done({ok: true, text: t}))
        .catch(e => done({ok: false, error: e.toString()}));
    """
    res = driver.execute_async_script(script, url)
    if not res or not res.get("ok"):
        raise RuntimeError(f"browser fetch failed for {url}: {res and res.get('error')}")
    payload = json.loads(res["text"])
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _payload_to_points(payload):
    """
    Normalizes a chartdata payload into [(date_str, value), ...].

    Handles the two shapes CVoter has used: an {epoch_ms: value} mapping, and a
    Highcharts-style list of [epoch_ms, value] pairs or {x, y} objects.
    """
    points = []

    def add(ts, val):
        if ts is None or val is None:
            return
        try:
            ts = float(ts)
            val = float(val)
        except (TypeError, ValueError):
            return
        date = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")
        points.append((date, val))

    if isinstance(payload, dict):
        for ts, val in payload.items():
            add(ts, val)
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                add(item[0], item[1])
            elif isinstance(item, dict):
                add(item.get("x"), item.get("y"))

    return points


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------

def fetch_all_series(use_browser_fallback=True, verbose=True):
    """
    Fetches all 41 option-level series and returns a tidy long DataFrame.

    Columns: date, tracker_id, tracker_name, metric_name, option_index,
             polarity, weight, value
    """
    import requests

    session = requests.Session()
    driver = None
    records = []
    failures = []

    series_list = list(iter_series())
    if verbose:
        print(f"Fetching {len(series_list)} option-level series from cvoterindia.com...")

    for spec in series_list:
        payload = None
        try:
            payload = _http_get_json(spec["url"], session=session)
        except Exception as http_err:  # noqa: BLE001 - fall back to browser
            if use_browser_fallback:
                try:
                    if driver is None:
                        if verbose:
                            print("  direct HTTP blocked, starting headless Chrome fallback...")
                        driver = _setup_selenium(headless=True)
                    payload = _browser_get_json(driver, spec["url"])
                except Exception as browser_err:  # noqa: BLE001
                    failures.append((spec["endpoint"], f"{http_err} / {browser_err}"))
            else:
                failures.append((spec["endpoint"], str(http_err)))

        if payload is None:
            continue

        points = _payload_to_points(payload)
        for date, value in points:
            records.append({
                "date": date,
                "tracker_id": spec["tracker_id"],
                "tracker_name": spec["tracker_name"],
                "metric_name": spec["metric_name"],
                "option_index": spec["option_index"],
                "polarity": spec["polarity"],
                "weight": spec["weight"],
                "value": value,
            })

        if verbose:
            print(f"  [{spec['endpoint']:<8}] {len(points):>5} pts  {spec['column']}")

    if driver is not None:
        driver.quit()

    if failures:
        print(f"\nWARNING: {len(failures)} series failed:")
        for endpoint, err in failures:
            print(f"  {endpoint}: {err}")

    long_df = pd.DataFrame.from_records(records)
    if not long_df.empty:
        long_df = long_df.sort_values(["date", "tracker_id", "option_index"]).reset_index(drop=True)
    return long_df


def long_to_wide(long_df):
    """Pivots the tidy frame into one column per option series, indexed by date."""
    if long_df.empty:
        return pd.DataFrame()

    frame = long_df.copy()
    frame["column"] = frame.apply(
        lambda r: f"T{int(r['tracker_id'])} {r['tracker_name']} - {r['metric_name']}", axis=1
    )
    wide = frame.pivot_table(index="date", columns="column", values="value", aggfunc="last")
    wide = wide.reset_index().sort_values("date").reset_index(drop=True)
    return wide


def build_catalog(long_df):
    """Describes every series -- label, weight, coverage -- for the API/UI."""
    catalog = []
    coverage = {}
    if not long_df.empty:
        grouped = long_df.groupby(["tracker_id", "metric_name"])
        for key, grp in grouped:
            coverage[key] = {
                "points": int(len(grp)),
                "first_date": str(grp["date"].min()),
                "last_date": str(grp["date"].max()),
                "latest_value": float(grp.sort_values("date")["value"].iloc[-1]),
            }

    for spec in iter_series():
        cov = coverage.get((spec["tracker_id"], spec["metric_name"]), {})
        catalog.append({
            "tracker_id": spec["tracker_id"],
            "tracker_name": spec["tracker_name"],
            "question": spec["question"],
            "metric_name": spec["metric_name"],
            "column": spec["column"],
            "endpoint": spec["endpoint"],
            "polarity": spec["polarity"],
            "weight": spec["weight"],
            **cov,
        })
    return catalog


def extract_cvoter_trackers(output_dir=DATA_DIR, use_browser_fallback=True, verbose=True):
    """
    Full extraction: fetches all option-level series and writes every artifact.

    Returns the wide DataFrame (date + one column per option series).
    """
    os.makedirs(output_dir, exist_ok=True)

    if verbose:
        print("=" * 62)
        print(f" CVoter option-level extraction ({total_series_count()} series)")
        print("=" * 62)

    long_df = fetch_all_series(use_browser_fallback=use_browser_fallback, verbose=verbose)
    if long_df.empty:
        print("ERROR: no tracker data extracted.")
        return pd.DataFrame()

    long_path = os.path.join(output_dir, "cvoter_metrics_long.csv")
    long_df.to_csv(long_path, index=False)

    wide_df = long_to_wide(long_df)
    wide_path = os.path.join(output_dir, "cvoter_daily_trackers.csv")
    wide_df.to_csv(wide_path, index=False)

    # Per-tracker slices
    for tracker_id, meta in TRACKER_SCHEMA.items():
        slice_df = long_df[long_df["tracker_id"] == tracker_id]
        if slice_df.empty:
            continue
        pivot = slice_df.pivot_table(index="date", columns="metric_name", values="value", aggfunc="last")
        pivot = pivot.reset_index().sort_values("date")
        clean = meta["name"].lower().replace(" ", "_").replace("/", "_")
        pivot.to_csv(os.path.join(output_dir, f"tracker_{tracker_id}_{clean}.csv"), index=False)

    catalog = build_catalog(long_df)
    with open(os.path.join(output_dir, "cvoter_metrics_catalog.json"), "w", encoding="utf-8") as fh:
        json.dump(catalog, fh, indent=2)

    if verbose:
        print("=" * 62)
        print(f"Wrote {wide_path}")
        print(f"  {len(wide_df)} daily rows x {len(wide_df.columns) - 1} labelled metrics")
        print(f"  date range: {wide_df['date'].min()} -> {wide_df['date'].max()}")
        print("=" * 62)

    return wide_df


if __name__ == "__main__":
    extract_cvoter_trackers(output_dir=DATA_DIR)
