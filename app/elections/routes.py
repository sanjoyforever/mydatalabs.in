"""
Lok Sabha Projection Engine — page and API.

Ported from the standalone india-elections Flask app.

Where the numbers come from
---------------------------
Every GET below answers out of `app/data/precomputed/lok-sabha-index.json`,
written by `python update.py` on a machine that has pandas, numpy, scipy and
scikit-learn. The deployment has none of them, and does not ship a single CSV:
the raw dataset is ~10 MB and the scientific stack is most of a serverless
bundle, spent on work whose answer is identical for every visitor.

So the heavy code paths below are a **local fallback**, not the normal route.
They run when the artifact is missing and the CSVs are present — a developer
who has just pulled the dataset and not yet run the updater. On the deployment
neither condition holds, `_heavy_stack_available()` is False, and the endpoint
answers 503 rather than raising ImportError on `import pandas`.

Read endpoints are memoised on the artifact's mtime, so a refresh invalidates
everything at once.

Endpoints
---------
GET  /lok-sabha-index                             dashboard page
GET  /api/lok-sabha-index/overview                latest forecast + intervals
GET  /api/lok-sabha-index/daily_forecast          full daily series
GET  /api/lok-sabha-index/trend_analytics         trend/volatility/momentum
GET  /api/lok-sabha-index/events                  annotated chart events
GET  /api/lok-sabha-index/metrics_catalog         41 labelled metrics
GET  /api/lok-sabha-index/sentiment_breakdown     per-option contributions
GET  /api/lok-sabha-index/calibration             fitted constants
GET  /api/lok-sabha-index/ml_comparison           seat models side by side
GET  /api/lok-sabha-index/backtest_results        2019 + 2024 backtest
GET  /api/lok-sabha-index/state_projections       baseline state table
GET  /api/lok-sabha-index/insights                summary + top impacts
GET  /api/lok-sabha-index/data_status             dataset freshness
POST /api/lok-sabha-index/simulate_permutation    what-if with custom params
POST /api/lok-sabha-index/refresh_data            operator refresh (off by default)
"""

import json
import os
import threading

from flask import Blueprint, Response, jsonify, render_template, request

from app.elections.engine.paths import (
    CALIBRATION_JSON,
    CATALOG_JSON,
    DATA_DIR,
    MASTER_CSV,
    PROJECTIONS_CSV,
)

bp = Blueprint("elections", __name__)

PAGE_URL = "/lok-sabha-index"
API_PREFIX = "/api/lok-sabha-index"

MAJORITY = 272
MONTE_CARLO_RUNS = 20000
MONTE_CARLO_SEED = 42

# Whether the dashboard may trigger a data refresh over HTTP. Off by default so
# a published instance is read-only; the operator updates by running
# scripts/update_elections.py.
ALLOW_WEB_REFRESH = os.environ.get("ALLOW_WEB_REFRESH", "").lower() in ("1", "true", "yes")

_cache: dict = {}
_cache_lock = threading.Lock()
_refresh_lock = threading.Lock()
_key_locks: dict = {}
_key_locks_lock = threading.Lock()


# --- Cache -----------------------------------------------------------------


ARTIFACT = "lok-sabha-index"


def _artifact():
    """The precomputed payload for this dashboard. {} if it was never built."""
    from app import precomputed

    return precomputed.load(ARTIFACT)


def _heavy_stack_available():
    """Whether this process can recompute from source.

    False on the deployment, which ships neither the CSVs nor pandas. Checking
    for the data first keeps the answer cheap: no import is attempted unless
    there is something to compute from.
    """
    if not (os.path.exists(MASTER_CSV) and os.path.exists(PROJECTIONS_CSV)):
        return False
    try:
        import pandas  # noqa: F401
    except ImportError:
        return False
    return True


def _unavailable(what):
    return jsonify({
        "error": f"{what} is not available on this deployment.",
        "reason": "The published site serves precomputed results only; the source "
                  "dataset and the scientific stack live on the update machine.",
        "remedy": "Run `python update.py` locally, then `python push_to_prod.py --code`.",
    }), 503


def _data_version():
    """Cache key: mtimes of everything a response can derive from.

    The artifact is what the deployment reads; the CSVs matter only to a local
    fallback. Including both means a refresh through either path invalidates
    the in-process cache.
    """
    from app import precomputed

    paths = (precomputed.path_for(ARTIFACT), MASTER_CSV, PROJECTIONS_CSV, CALIBRATION_JSON)
    return tuple(os.path.getmtime(p) if os.path.exists(p) else 0 for p in paths)


def cached(key, builder):
    """Memoises `builder()` under `key`, invalidated whenever the data changes.

    Includes stampede protection: if multiple threads request an uncached key
    simultaneously, only the first thread executes `builder()` while others wait.
    """
    version = _data_version()
    with _cache_lock:
        if _cache.get("_version") != version:
            _cache.clear()
            _cache["_version"] = version
        if key in _cache:
            return _cache[key]

    with _key_locks_lock:
        if key not in _key_locks:
            _key_locks[key] = threading.Lock()
        lock = _key_locks[key]

    with lock:
        with _cache_lock:
            if _cache.get("_version") == version and key in _cache:
                return _cache[key]

        value = builder()

        with _cache_lock:
            if _cache.get("_version") == version:
                _cache[key] = value
        return value


def load_master():
    import pandas as pd

    return cached("master", lambda: pd.read_csv(MASTER_CSV))


def load_projections():
    def build():
        import pandas as pd

        if not os.path.exists(PROJECTIONS_CSV):
            from app.elections.engine.daily_predictor import run_daily_predictions

            return run_daily_predictions(data_dir=DATA_DIR, output_dir=DATA_DIR, verbose=False)
        return pd.read_csv(PROJECTIONS_CSV)

    return cached("projections", build)


def _missing_data_response():
    return jsonify({
        "error": "Dataset not found. Run `python update.py --elections` to fetch and build it.",
        "expected_path": MASTER_CSV,
    }), 404


def _no_store(resp):
    """Freshness and refresh answers are operational state; never cache them."""
    resp.headers["Cache-Control"] = "no-store"
    return resp


def headline():
    """Latest projected NDA seats, for the home page's report card.

    Prefers the artifact, which is all the deployment has. The CSV tail-read
    below is the local fallback: stdlib-only and deliberately not a Monte Carlo
    run, since the last line of the projections CSV already holds the number
    the card shows.

    Returns None if neither source is readable, and the caller then renders the
    card without a figure rather than a wrong one.
    """
    stored = _artifact().get("headline")
    if stored:
        return stored

    try:
        with open(PROJECTIONS_CSV, "rb") as fh:
            header = fh.readline().decode("utf-8").strip().split(",")
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            # Enough to cover one row of ~38 numeric columns.
            window = min(size, 4096)
            fh.seek(size - window)
            tail = fh.read().decode("utf-8").strip().splitlines()
        if not tail:
            return None
        row = tail[-1].split(",")
        if len(row) != len(header):
            return None
        values = dict(zip(header, row))
        return {
            "value": int(float(values["NDA_proj_seats"])),
            "unit": "NDA seats",
            "as_of": values["date"],
        }
    except (OSError, KeyError, ValueError, IndexError):
        return None


def _source_mtime():
    """Newest mtime across the CSVs the artifact derives from. 0 if absent."""
    return max(
        (os.path.getmtime(p) if os.path.exists(p) else 0)
        for p in (MASTER_CSV, PROJECTIONS_CSV, CALIBRATION_JSON)
    )


def _section(key, fallback_builder=None):
    """One slice of the precomputed artifact.

    Served whenever the artifact is at least as new as the CSVs it came from.
    That freshness check is the point: reading it whenever it merely exists
    means any path that rewrites the CSVs without re-running the precompute —
    scripts/elections_pipeline.py does exactly that, and so does editing a CSV
    by hand — leaves the dashboard serving last week's seat numbers
    indefinitely, with nothing anywhere to notice. Stale figures on a
    projection dashboard are worse than slow ones.

    On the deployment there are no CSVs, `_source_mtime()` is 0, and the
    artifact always wins — which is correct, because there is nothing newer it
    could be missing.

    Returns None when there is no artifact and no way to compute one; the
    caller turns that into a 503 rather than a traceback.
    """
    def build():
        from app import precomputed

        path = precomputed.path_for(ARTIFACT)
        if os.path.exists(path) and os.path.getmtime(path) >= _source_mtime():
            data = precomputed.load(ARTIFACT).get(key)
            if data is not None:
                return data

        if fallback_builder is None or not _heavy_stack_available():
            return None
        return fallback_builder()

    return cached(key, build)


# --- Page ------------------------------------------------------------------


def _get_overview_data():
    def build():
        from app.elections.engine.election_data import HISTORICAL_ELECTION_RESULTS
        from app.elections.engine.seat_predictive_model import LokSabhaSeatPredictor

        df = load_master()
        predictor = LokSabhaSeatPredictor(baseline_year=2024, data_dir=DATA_DIR)
        latest = df.iloc[-1]
        mc = predictor.run_monte_carlo_simulation(
            latest, n_simulations=MONTE_CARLO_RUNS, seed=MONTE_CARLO_SEED
        )

        summary = HISTORICAL_ELECTION_RESULTS[2024]["national_summary"]
        return {
            "as_of_date": str(latest["date"]),
            "total_days_analyzed": int(len(df)),
            "metrics_tracked": int(len(df.columns) - 1),
            "actual_2024_nda": summary["NDA"]["seats"],
            "actual_2024_india": summary["INDIA"]["seats"],
            "actual_2024_others": summary["OTHERS"]["seats"],
            "majority_threshold": MAJORITY,
            "latest_forecast": mc,
        }

    return _section("overview", build)


def _get_trend_analytics_data():
    def build():
        from app.elections.engine.trend_analytics import summarize

        df = load_projections()
        series = ["NDA_proj_seats", "INDIA_proj_seats", "composite_sentiment"]
        return {
            "as_of_date": str(df["date"].iloc[-1]),
            "majority_threshold": MAJORITY,
            "series": {col: summarize(df, value_col=col) for col in series if col in df.columns},
        }

    return _section("trend_analytics", build)


def _get_events_data():
    def build():
        from app.elections.engine.events import categories as event_categories
        from app.elections.engine.events import get_events

        return {
            "events": get_events(),
            "categories": event_categories(),
        }

    return _section("events", build)


def _get_backtest_data():
    def build():
        from app.elections.engine.backtest_engine import run_full_backtest
        from app.elections.engine.seat_predictive_model import LokSabhaSeatPredictor

        df = load_master()
        predictor = LokSabhaSeatPredictor(baseline_year=2024, data_dir=DATA_DIR)
        return run_full_backtest(predictor, df)

    return _section("backtest", build)


def _get_insights_data():
    def build():
        from app.elections.engine.insights import executive_summary, top_impacts
        from app.elections.engine.sentiment_index import option_contributions

        projections = load_projections()
        master = load_master()

        overview = _get_overview_data()
        backtest = _get_backtest_data()
        latest = master.iloc[-1]

        return {
            "summary": executive_summary(
                projections,
                overview,
                contributions=option_contributions(latest),
                backtest=backtest,
            ),
            "impacts": top_impacts(projections, n=5),
        }

    return _section("insights", build)


@bp.route(PAGE_URL)
def lok_sabha_index():
    from app.routes import _cached, _common

    overview = _get_overview_data()
    trend_analytics = _get_trend_analytics_data()
    events = _get_events_data()
    backtest = _get_backtest_data()
    insights = _get_insights_data()

    if overview is None or trend_analytics is None:
        # No artifact and nothing to build one from. Rendering the shell would
        # give a dashboard of empty boxes with no explanation; say what is
        # wrong instead.
        return Response(
            "<h1>Lok Sabha Projection unavailable</h1>"
            "<p>No precomputed artifact and no source dataset to build one from. "
            "Run <code>python update.py --elections</code>.</p>",
            status=503,
            mimetype="text/html",
        )

    preloaded = {
        "overview": overview,
        "trend_analytics": trend_analytics,
        "events": events,
        "backtest": backtest,
        "insights": insights,
    }

    html = render_template(
        "elections.html",
        **_common(
            api_prefix=API_PREFIX,
            overview=overview,
            trend_analytics=trend_analytics,
            events=events,
            backtest=backtest,
            insights=insights,
            # Emitted raw inside a <script type="application/json"> block, so
            # the one sequence that can break out of it has to be neutralised.
            # An event label or an insight sentence containing "</script>"
            # would otherwise end the block early and hand the rest of the
            # payload to the HTML parser. "<\/" is identical to "</" once the
            # JSON is parsed, so nothing downstream changes.
            preloaded_json=json.dumps(preloaded).replace("</", "<\\/"),
        ),
    )
    return _cached(Response(html, mimetype="text/html"))


# --- Forecast --------------------------------------------------------------


@bp.route(f"{API_PREFIX}/overview")
def api_overview():
    data = _get_overview_data()
    return jsonify(data) if data is not None else _unavailable("Overview")


@bp.route(f"{API_PREFIX}/daily_forecast")
def api_daily_forecast():
    """
    Full daily series. `?fields=` trims the payload to named columns (date is
    always included); `?from=` and `?to=` clip the date range.

    Filtering is a list comprehension over the precomputed rows rather than a
    DataFrame slice. Same answer, and it holds for a deployment with no pandas.
    """
    rows = _daily_forecast_rows()
    if rows is None:
        return _unavailable("Daily forecast")

    start, end = request.args.get("from"), request.args.get("to")
    if start:
        rows = [r for r in rows if str(r.get("date", "")) >= start]
    if end:
        rows = [r for r in rows if str(r.get("date", "")) <= end]

    fields = request.args.get("fields")
    if fields:
        available = set(rows[0]) if rows else set()
        wanted = ["date"] + [f for f in fields.split(",") if f in available and f != "date"]
        rows = [{k: r.get(k) for k in wanted} for r in rows]

    return Response(json.dumps(rows), mimetype="application/json")


def _daily_forecast_rows():
    def build():
        import json as _json

        df = load_projections()
        return _json.loads(df.to_json(orient="records"))

    return _section("daily_forecast", build)


@bp.route(f"{API_PREFIX}/trend_analytics")
def api_trend_analytics():
    """Headline trend block: current estimate, MAs, slope, volatility, momentum."""
    data = _get_trend_analytics_data()
    return jsonify(data) if data is not None else _unavailable("Trend analytics")


# --- Context: events, metric catalog, sentiment breakdown, calibration ------


@bp.route(f"{API_PREFIX}/events")
def api_events():
    """
    The annotated timeline. `?from=`, `?to=` and `?categories=` filter it.

    Filtering runs here rather than off the artifact because events.py is a
    plain module with no pandas dependency — it is the one heavy-looking import
    on this blueprint that is safe everywhere.
    """
    raw_categories = request.args.get("categories", "")
    if raw_categories or request.args.get("from") or request.args.get("to"):
        from app.elections.engine.events import categories as event_categories
        from app.elections.engine.events import get_events

        return jsonify({
            "events": get_events(
                start_date=request.args.get("from"),
                end_date=request.args.get("to"),
                categories=raw_categories.split(",") if raw_categories else None,
            ),
            "categories": event_categories(),
        })

    data = _get_events_data()
    return jsonify(data) if data is not None else _unavailable("Events")


@bp.route(f"{API_PREFIX}/metrics_catalog")
def api_metrics_catalog():
    """Every labelled metric with its polarity, weight and coverage."""
    def build():
        with open(CATALOG_JSON, encoding="utf-8") as fh:
            return {"metrics": json.load(fh)}

    data = _section("metrics_catalog", build if os.path.exists(CATALOG_JSON) else None)
    return jsonify(data) if data is not None else _unavailable("Metrics catalog")


@bp.route(f"{API_PREFIX}/sentiment_breakdown")
def api_sentiment_breakdown():
    """Which answer options are driving the index, on the latest day."""
    def build():
        from app.elections.engine.sentiment_index import option_contributions

        df = load_master()
        latest = df.iloc[-1]
        contributions = option_contributions(latest)
        return {
            "as_of_date": str(latest["date"]),
            "contributions": contributions,
            "positive_total": round(
                sum(c["contribution"] for c in contributions if c["contribution"] > 0), 3
            ),
            "negative_total": round(
                sum(c["contribution"] for c in contributions if c["contribution"] < 0), 3
            ),
        }

    data = _section("sentiment_breakdown", build)
    return jsonify(data) if data is not None else _unavailable("Sentiment breakdown")


@bp.route(f"{API_PREFIX}/calibration")
def api_calibration():
    def build():
        from app.elections.engine.calibration import load_calibration

        return load_calibration(data_dir=DATA_DIR)

    data = _section("calibration", build)
    return jsonify(data) if data is not None else _unavailable("Calibration")


# --- Model comparison and backtest -----------------------------------------


@bp.route(f"{API_PREFIX}/ml_comparison")
def api_ml_comparison():
    def build():
        from app.elections.engine.ml_models import MLSeatPredictorSuite

        df = load_master()
        latest = df.iloc[-1]
        suite = MLSeatPredictorSuite(baseline_year=2024, data_dir=DATA_DIR)
        return {"as_of_date": str(latest["date"]), "models": suite.compare_all_models(latest)}

    data = _section("ml_comparison", build)
    return jsonify(data) if data is not None else _unavailable("Model comparison")


@bp.route(f"{API_PREFIX}/backtest_results")
def api_backtest_results():
    data = _get_backtest_data()
    return jsonify(data) if data is not None else _unavailable("Backtest results")


@bp.route(f"{API_PREFIX}/state_projections")
def api_state_projections():
    def build():
        from app.elections.engine.election_data import HISTORICAL_ELECTION_RESULTS

        return HISTORICAL_ELECTION_RESULTS[2024]["state_baselines"]

    # A static table, but election_data.py imports pandas at module scope, so
    # it is served from the artifact like everything else.
    data = _section("state_projections", build)
    return jsonify(data) if data is not None else _unavailable("State projections")


@bp.route(f"{API_PREFIX}/insights")
def api_insights():
    """Executive summary plus the highest-impact events in each direction."""
    data = _get_insights_data()
    return jsonify(data) if data is not None else _unavailable("Insights")


@bp.route(f"{API_PREFIX}/simulate_permutation", methods=["POST"])
def api_simulate_permutation():
    """What-if: run one model with custom parameters against the latest day.

    The only endpoint that cannot be precomputed — the answer depends on
    parameters the caller chooses — so it is also the only one that needs the
    dataset and scikit-learn at request time. It answers 503 on the deployment.
    Nothing in the dashboard UI calls it; it exists for API users.
    """
    if not _heavy_stack_available():
        return _unavailable("Permutation simulation")

    from app.elections.engine.ml_models import MLSeatPredictorSuite

    payload = request.get_json(silent=True) or {}
    model_type = payload.get("ml_model", "cube_law")
    try:
        swing_multiplier = float(payload.get("swing_multiplier", 1.0))
    except (TypeError, ValueError):
        return jsonify({"error": "swing_multiplier must be a number."}), 400
    cube_exponent = payload.get("cube_exponent")

    df = load_master()
    latest = df.iloc[-1]
    suite = MLSeatPredictorSuite(baseline_year=2024, data_dir=DATA_DIR)

    if model_type == "logistic_softmax":
        result = suite.predict_logistic_softmax(latest)
    elif model_type == "ridge_regression":
        result = suite.predict_ridge_regression(latest)
    elif model_type == "random_forest":
        result = suite.predict_random_forest(latest)
    elif model_type == "regional_swing":
        result = suite.predict_regional_swing(latest)
    else:
        try:
            k = float(cube_exponent) if cube_exponent is not None else None
        except (TypeError, ValueError):
            return jsonify({"error": "cube_exponent must be a number."}), 400
        result = suite.predict_cube_law(latest, k=k, swing_mult=swing_multiplier)

    result["majority_winner"] = (
        "NDA" if result["NDA"] >= MAJORITY
        else "INDIA" if result["INDIA"] >= MAJORITY
        else "Hung Parliament"
    )

    return jsonify({
        "model_selected": result["model"],
        "note": result.get("note"),
        "predicted_seats": {k: result[k] for k in ("NDA", "INDIA", "OTHERS")},
        "majority_winner": result["majority_winner"],
        "majority_threshold": MAJORITY,
    })


# --- Data freshness --------------------------------------------------------


@bp.route(f"{API_PREFIX}/data_status")
def api_data_status():
    """How current the published dataset is.

    `?check_remote=1` asks cvoterindia.com how current it *could* be, which
    needs the source dataset to compare against and so only works locally. The
    dashboard calls this with check_remote=0 and gets the answer settled at
    build time — a page render must not make an outbound HTTP call.
    """
    if request.args.get("check_remote", "0") != "0":
        if not _heavy_stack_available():
            return _unavailable("Remote freshness check")
        from app.elections.engine.data_updater import data_status

        return _no_store(jsonify(data_status(data_dir=DATA_DIR, check_remote=True)))

    status = _artifact().get("data_status")
    if status is None:
        if not _heavy_stack_available():
            return _unavailable("Data status")
        from app.elections.engine.data_updater import data_status

        status = data_status(data_dir=DATA_DIR, check_remote=False)
    return _no_store(jsonify(status))


@bp.route(f"{API_PREFIX}/refresh_data", methods=["POST"])
def api_refresh_data():
    """
    Runs the updater.

    Disabled by default. On a published deployment an anonymous visitor must not
    be able to make the server fetch 41 upstream files and rewrite the dataset,
    so this returns 403 unless ALLOW_WEB_REFRESH is explicitly set. Updating is
    an operator task: run `python scripts/update_elections.py` instead.

    Refuses to start a second run while one is in flight, since a concurrent
    refresh would fight over the same CSVs.
    """
    if not ALLOW_WEB_REFRESH:
        return _no_store(jsonify({
            "status": "disabled",
            "reason": "Refresh over HTTP is disabled. Run `python scripts/update_elections.py` "
                      "on the server, or set ALLOW_WEB_REFRESH=1 to enable this endpoint.",
        })), 403

    if not _refresh_lock.acquire(blocking=False):
        return _no_store(jsonify({
            "status": "busy",
            "reason": "a refresh is already running",
        })), 409

    try:
        from app.elections.engine.data_updater import update_data

        force = bool((request.get_json(silent=True) or {}).get("force", False))
        result = update_data(data_dir=DATA_DIR, force=force, verbose=False)
        with _cache_lock:
            _cache.clear()
        return _no_store(jsonify(result))
    finally:
        _refresh_lock.release()
