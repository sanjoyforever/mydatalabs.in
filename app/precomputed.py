"""
Per-route precomputed artifacts.

The rule this module enforces: **a page render never touches the network and
never touches the database.** Everything a route needs that costs more than
arithmetic is computed by the update scripts and written here as JSON, one file
per route. Rendering is then a disk read plus a template.

Why this exists
---------------
Before it, `/hormuz-index` cost ~19s on a cold hit: `votes.get_history()` and
`votes.get_summary()` waited on a sleeping Neon compute node (~19s between
them) and `fetch_live_values()` waited on yfinance (~6s). Both ran inside the
request. TTL caches made the second visitor fast and left the first — which on
a low-traffic site is most visitors — paying the whole bill.

Adding a dashboard
------------------
Add one entry to `BUILDERS` keyed on the route slug. `update_data.py` writes
every entry; routes read theirs with `load()`. Nothing else needs editing.

The Lok Sabha engine has its own equivalent under app/elections/engine/
(precompute.py, five files keyed on the same idea) because its artifacts are
rebuilt by the CVoter updater on a different schedule.

Freshness
---------
`load()` never falls back to computing. A missing or unreadable artifact
returns `{}` and the caller renders whatever it can — an empty perception
series draws no line, and absent live values carry the previous week's reading
forward, which is what `compute_snapshot` already does for a failed fetch. The
alternative, recomputing on demand, is exactly the request-time cost this
module exists to remove.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import date

PRECOMPUTED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "precomputed")

_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def path_for(name: str) -> str:
    return os.path.join(PRECOMPUTED_DIR, f"{name}.json")


def load(name: str) -> dict:
    """Read a precomputed artifact, memoised on its mtime.

    Returns {} when the file is missing or unreadable, so a route degrades to
    a thinner page rather than a 500.
    """
    path = path_for(name)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}

    with _cache_lock:
        cached = _cache.get(name)
        if cached and cached[0] == mtime:
            return cached[1]

    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}

    with _cache_lock:
        _cache[name] = (mtime, data)
    return data


def write(name: str, data: dict) -> bool:
    """Write an artifact. False on a read-only filesystem rather than raising."""
    try:
        os.makedirs(PRECOMPUTED_DIR, exist_ok=True)
        with open(path_for(name), "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, default=str)
    except OSError:
        return False
    with _cache_lock:
        _cache.pop(name, None)
    return True


# --- Builders ---------------------------------------------------------------
# Each returns the JSON body for one route. They are the only code allowed to
# make network or database calls on behalf of a page.


def _build_hormuz_index() -> dict:
    """Live component values and the settled perception series.

    The current week's vote aggregate is included as the server-rendered
    starting state only. vote.js re-fetches it on load, so a ballot cast since
    the last update run still appears immediately — it is the *page render*
    that must not wait on the database, not the widget.
    """
    from app import votes
    from app.indices import hormuz

    previous = load("hormuz-index")

    live = hormuz.fetch_live_values(allow_network=True)
    # Stamped here because this is the only place the values are actually
    # fetched. The request path reads them back off disk, where "when were
    # these obtained" is otherwise unrecoverable — it can only assume "now",
    # which is how a week-old artifact ends up reporting itself as current.
    live_at = date.today().isoformat()
    # A failed sweep must not overwrite good values with nulls: the page would
    # then carry every live component forward and mark the snapshot degraded
    # until the next successful run.
    if not any(v is not None for v in live.values()):
        live = previous.get("live_values") or live
        # Carry the original date with the carried-forward values. Leaving
        # today's date on them would let a run that fetched nothing advance the
        # page's "Updated" line, which is precisely the failure it should show.
        live_at = previous.get("live_values_at") or ""

    history = hormuz.get_history()

    sentiment = votes.get_summary()
    sentiment_history = votes.get_history()

    # votes.* never raise — an unreachable database returns an empty summary
    # that is indistinguishable from "nobody has voted". Writing that over a
    # good artifact would blank the perception line on the public chart because
    # of a transient connection failure, so a read that came back unavailable
    # is discarded in favour of what is already on disk.
    if not sentiment.get("available") and previous.get("sentiment"):
        sentiment = previous["sentiment"]
        sentiment_history = previous.get("sentiment_history", [])
        perception_by_week = previous.get("perception_by_week", {})
    else:
        perception_by_week = {h["week_start"]: h["index"] for h in sentiment_history}

    # Which PortWatch week the transit figure came from. Carried alongside the
    # values because, unlike the market components, it is not "as of the fetch"
    # — see hormuz.portwatch_asof.
    portwatch_week_end = hormuz.portwatch_asof(allow_network=True) or (
        previous.get("portwatch_week_end") or ""
    )

    return {
        "live_values": live,
        "live_values_at": live_at,
        "portwatch_week_end": portwatch_week_end,
        "sentiment": sentiment,
        "sentiment_history": sentiment_history,
        "perception_by_week": perception_by_week,
        # Plotted on the model's own week axis; weeks with no publishable
        # ballot map to null and draw a gap rather than a fabricated point.
        "perception_series": [perception_by_week.get(h["week_start"]) for h in history],
    }


def _build_airline_index() -> dict:
    """Live component values and historical series for the Airline Pressure Index."""
    from app.indices import aviation

    previous = load("airline-index")
    live = aviation.fetch_live_values(allow_network=True)
    live_at = date.today().isoformat()

    if not any(v is not None for v in live.values()):
        live = previous.get("live_values") or live
        live_at = previous.get("live_values_at") or ""

    history = aviation.get_history()
    snapshot = aviation.compute_snapshot(values=live, allow_network=False)

    return {
        "live_values": live,
        "live_values_at": live_at,
        "snapshot": {
            "score": snapshot.score,
            "level_label": snapshot.level_label,
            "level_status": snapshot.level_status,
            "week_start": snapshot.week_start,
        },
        "history": history,
    }


def _build_home() -> dict:
    """Headline figure for each report card on the landing page."""
    from app.indices import aviation, hormuz

    aviation_snap = aviation.compute_snapshot(allow_network=False)
    snapshot = hormuz.compute_snapshot(persist=False)
    ls = load("lok-sabha-index").get("headline")

    return {
        "cards": {
            "airline-index": {
                "value": f"{aviation_snap.score:.1f}",
                "unit": "score",
                "status": aviation_snap.level_status,
            },
            "hormuz-index": {
                "value": f"{snapshot.score:.1f}",
                "unit": "score",
                "status": snapshot.level_status,
            },
            "lok-sabha-index": {
                "value": str(ls["value"]) if ls else None,
                "unit": ls["unit"] if ls else None,
                # The projection has no crisis banding, so it carries the
                # neutral status rather than borrowing the Hormuz colour.
                "status": "good",
            },
        },
    }


def _build_lok_sabha_index() -> dict:
    """Every response the Lok Sabha dashboard serves, as one artifact.

    This is what lets the deployed site drop pandas, numpy, scipy and
    scikit-learn entirely. Each key below was previously computed inside a
    request from a 2,772-row CSV — a Monte Carlo draw, a backtest, a model
    comparison. All of it is deterministic given the dataset, so all of it can
    be settled here, on a machine that has the scientific stack, and shipped as
    JSON. The deployment then reads a dict.

    Run locally only: everything imported below needs pandas.
    """
    import json as _json

    import pandas as pd

    from app.elections.engine.paths import CATALOG_JSON, DATA_DIR, MASTER_CSV, PROJECTIONS_CSV
    from app.elections.routes import (
        MAJORITY,
        _get_backtest_data,
        _get_events_data,
        _get_insights_data,
        _get_overview_data,
        _get_trend_analytics_data,
    )

    if not (os.path.exists(MASTER_CSV) and os.path.exists(PROJECTIONS_CSV)):
        raise FileNotFoundError(
            f"{MASTER_CSV} or {PROJECTIONS_CSV} missing — run `python update.py --elections` first."
        )

    master = pd.read_csv(MASTER_CSV)
    projections = pd.read_csv(PROJECTIONS_CSV)
    latest = master.iloc[-1]

    # The six chart series plus the date. The full 38-column frame is ~10x
    # larger and nothing reads the rest.
    chart_cols = [
        "date",
        "NDA_proj_seats", "INDIA_proj_seats",
        "NDA_proj_seats_ma7", "NDA_proj_seats_ma30",
        "INDIA_proj_seats_ma7", "INDIA_proj_seats_ma30",
    ]
    present = [c for c in chart_cols if c in projections.columns]
    # via to_json: pandas writes NaN as null, whereas json.dump would emit a
    # bare NaN token that no browser JSON parser accepts.
    daily_forecast = _json.loads(projections[present].to_json(orient="records"))

    from app.elections.engine.calibration import load_calibration
    from app.elections.engine.election_data import HISTORICAL_ELECTION_RESULTS
    from app.elections.engine.ml_models import MLSeatPredictorSuite
    from app.elections.engine.sentiment_index import option_contributions

    contributions = option_contributions(latest)
    suite = MLSeatPredictorSuite(baseline_year=2024, data_dir=DATA_DIR)

    catalog = []
    if os.path.exists(CATALOG_JSON):
        with open(CATALOG_JSON, encoding="utf-8") as fh:
            catalog = _json.load(fh)

    # check_remote=False: the freshness pill compares two dates, and calling
    # cvoterindia.com from a page render is exactly the request-time network
    # call this module exists to remove. The pill shows how current the
    # published data is, which is settled at build time.
    from app.elections.engine.data_updater import data_status

    return {
        "overview": _get_overview_data(),
        "trend_analytics": _get_trend_analytics_data(),
        "events": _get_events_data(),
        "backtest": _get_backtest_data(),
        "insights": _get_insights_data(),
        "daily_forecast": daily_forecast,
        "sentiment_breakdown": {
            "as_of_date": str(latest["date"]),
            "contributions": contributions,
            "positive_total": round(
                sum(c["contribution"] for c in contributions if c["contribution"] > 0), 3
            ),
            "negative_total": round(
                sum(c["contribution"] for c in contributions if c["contribution"] < 0), 3
            ),
        },
        "ml_comparison": {
            "as_of_date": str(latest["date"]),
            "models": suite.compare_all_models(latest),
        },
        "calibration": load_calibration(data_dir=DATA_DIR),
        "metrics_catalog": {"metrics": catalog},
        "state_projections": HISTORICAL_ELECTION_RESULTS[2024]["state_baselines"],
        "data_status": data_status(data_dir=DATA_DIR, check_remote=False),
        "majority_threshold": MAJORITY,
        # Home page report card. Saves the deployment tail-reading a CSV that
        # is no longer shipped.
        "headline": {
            "value": int(float(projections["NDA_proj_seats"].iloc[-1])),
            "unit": "NDA seats",
            "as_of": str(projections["date"].iloc[-1]),
        },
    }


BUILDERS = {
    "airline-index": _build_airline_index,
    "hormuz-index": _build_hormuz_index,
    "lok-sabha-index": _build_lok_sabha_index,
    "home": _build_home,
}


def build_all(verbose: bool = True) -> dict:
    """Rebuild every route artifact. Called by update.py.

    Order matters, and BUILDERS is ordered deliberately: home reads the live
    values hormuz-index just wrote and the headline lok-sabha-index just wrote,
    so every card reports the same figure as the dashboard it links to rather
    than one refresh older.
    """
    written = {}
    for name, builder in BUILDERS.items():
        try:
            data = builder()
        except Exception as err:  # noqa: BLE001 - one bad route must not stop the rest
            if verbose:
                print(f"  precompute {name}: FAILED ({err})")
            written[name] = False
            continue
        ok = write(name, data)
        written[name] = ok
        if verbose:
            print(f"  precompute {name}: {'written' if ok else 'read-only filesystem'}")
    return written
