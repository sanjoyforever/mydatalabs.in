import csv
import io
import json
import os
import re
import threading
import time
from datetime import date, datetime

from flask import Blueprint, Response, abort, jsonify, redirect, render_template, request

from app import db, manual_data, precomputed, scoring, storage, votes
from app.indices import hormuz

bp = Blueprint("main", __name__)

# Canonical origin for every absolute URL the site emits (canonical tags, OG,
# sitemap, robots, JSON-LD). Override with SITE_ORIGIN if the canonical host
# ever changes so no template has to be edited.
SITE_ORIGIN = os.environ.get("SITE_ORIGIN", "https://mydatalabs.in").rstrip("/")

# Data licence, stated identically in the footer, the /data page and the
# Dataset JSON-LD so the three can never contradict each other.
DATA_LICENSE_NAME = "CC BY 4.0"
DATA_LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"

# Nav categories shown in the menu.
NAV_CATEGORIES = [
    {"slug": "geo-politics", "label": "Geo Politics"},
    {"slug": "energy-commodities", "label": "Energy & Commodities"},
    {"slug": "maritime-supply", "label": "Maritime & Supply Chain"},
    {"slug": "financial-stress", "label": "Financial Stress"},
    {"slug": "tech-infrastructure", "label": "Tech & Infrastructure"},
]

REPORTS = [
    {
        "slug": "hormuz-index",
        "title": "Hormuz Crisis Index",
        "ticker": "HMX-INDEX",
        "blurb": "Weekly composite index tracking geopolitical stress, vessel traffic disruption, and insurance risk in the Strait of Hormuz.",
        "category": "Geo Politics",
        "url": "/hormuz-index",
        "live": True,
    },
    {
        "slug": "lok-sabha-index",
        "title": "Lok Sabha Projection Engine",
        "ticker": "LS-PROJ",
        "blurb": "Daily 543-seat Lok Sabha projection from CVoter's option-level public opinion trackers, calibrated on the 2019 and 2024 general election results.",
        "category": "Geo Politics",
        "url": "/lok-sabha-index",
        "live": True,
    },
]

# Internal event log. These entries are MyDataLabs' own annotations of the
# index trajectory — they are not wire reports, so they are attributed to this
# log rather than to a news organisation. Attaching a newsroom's name to an
# entry with no article behind it would misrepresent that newsroom.
GEOPOLITICAL_EVENTS = [
    {
        "date": "2026-01-05",
        "title": "Baseline Index Initialized",
        "description": "Composite score anchored at 100.0 baseline across normal non-crisis maritime operations.",
        "impact": "Neutral",
        "source_name": "MyDataLabs methodology note",
        "source_url": "/hormuz-index#methodology",
    },
    {
        "date": "2026-02-23",
        "title": "Gulf of Oman Patrol Alert",
        "description": "Increased naval advisory presence reported. War-risk insurance premiums increased by +50%.",
        "impact": "Moderate (+9.5 pts)",
        "source_name": "MyDataLabs internal event log",
        "source_url": "/hormuz-index#methodology",
    },
    {
        "date": "2026-03-02",
        "title": "Commercial AIS Signal Dropouts",
        "description": "Tankers reporting GPS spoofing and elevated spoofing warnings near Qeshm Island.",
        "impact": "High (+8.4 pts)",
        "source_name": "MyDataLabs internal event log",
        "source_url": "/hormuz-index#methodology",
    },
    {
        "date": "2026-03-09",
        "title": "Joint Maritime Maneuvers",
        "description": "Naval live-fire exercises announced in international shipping lanes. Cape reroutes rise to 21%.",
        "impact": "High (+4.7 pts)",
        "source_name": "MyDataLabs internal event log",
        "source_url": "/hormuz-index#methodology",
    },
    {
        "date": "2026-03-16",
        "title": "Temporary Maritime Ceasefire Declared",
        "description": "72-hour diplomatic truce declared in Gulf transit zone; insurance surcharges temporarily ease.",
        "impact": "Ceasefire Easing (-7.1 pts)",
        "is_ceasefire": True,
        "source_name": "MyDataLabs internal event log",
        "source_url": "/hormuz-index#methodology",
    },
    {
        "date": "2026-04-06",
        "title": "Regional Maritime Ceasefire Signed",
        "description": "Multinational diplomatic truce signed establishing permanent escort corridor; stress index eases.",
        "impact": "Ceasefire Easing (-5.1 pts)",
        "is_ceasefire": True,
        "source_name": "MyDataLabs internal event log",
        "source_url": "/hormuz-index#methodology",
    },
    {
        "date": "2026-06-15",
        "title": "Mid-Summer Ceasefire Extension",
        "description": "Renewed ceasefire agreement signed by regional powers; vessel transits temporarily recover.",
        "impact": "Ceasefire Easing (-9.2 pts)",
        "is_ceasefire": True,
        "source_name": "MyDataLabs internal event log",
        "source_url": "/hormuz-index#methodology",
    },
]

CEASEFIRE_DATES = {e["date"] for e in GEOPOLITICAL_EVENTS if e.get("is_ceasefire")}

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


# --- Snapshot cache --------------------------------------------------------
# compute_snapshot() makes three blocking network calls to Yahoo Finance. Doing
# that per request put ~1.3s of third-party latency in front of every page view
# and made the headline number hostage to an external endpoint. The underlying
# data moves at most daily, so it is cached in-process and served from there.

SNAPSHOT_TTL_SECONDS = int(os.environ.get("SNAPSHOT_TTL_SECONDS", "3600"))
_snapshot_lock = threading.Lock()
_snapshot_cache: dict = {"value": None, "fetched_at": 0.0}


def get_snapshot(force: bool = False):
    """Cached composite snapshot. Falls back to the last good value on error."""
    now = time.time()
    cached = _snapshot_cache["value"]
    if not force and cached is not None and (now - _snapshot_cache["fetched_at"]) < SNAPSHOT_TTL_SECONDS:
        return cached

    with _snapshot_lock:
        # Re-check: another thread may have refreshed while we waited.
        cached = _snapshot_cache["value"]
        if not force and cached is not None and (time.time() - _snapshot_cache["fetched_at"]) < SNAPSHOT_TTL_SECONDS:
            return cached
        try:
            value = hormuz.compute_snapshot(persist=False)
        except Exception:
            if cached is not None:
                return cached  # serve stale rather than erroring the page
            raise
        _snapshot_cache["value"] = value
        _snapshot_cache["fetched_at"] = time.time()
        return value


def _cached(resp: Response, seconds: int = 1800) -> Response:
    """Let the CDN serve the page while a fresh copy is revalidated behind it."""
    resp.headers["Cache-Control"] = (
        f"public, max-age=0, s-maxage={seconds}, stale-while-revalidate=86400"
    )
    return resp


# --- Vessel incident dataset ----------------------------------------------
# Compiled separately from the seven index components. It is displayed on the
# dashboard but contributes nothing to the composite score and is not served by
# the API.

VESSEL_DATA_IS_SYNTHETIC = False


def _load_vessel_attacks():
    """Load the vessel incident dataset and compute flag-state analytics."""
    data_path = os.path.join(os.path.dirname(__file__), "data", "vessel_attacks.json")
    if not os.path.exists(data_path):
        return [], [], 0

    try:
        with open(data_path, "r", encoding="utf-8") as f:
            attacks = json.load(f)
    except (OSError, ValueError):
        return [], [], 0

    total_atks = len(attacks)
    if total_atks == 0:
        return [], [], 0

    flag_counts: dict[str, int] = {}
    flag_emoji: dict[str, str] = {}
    flag_codes: dict[str, str] = {}
    for atk in attacks:
        c = atk.get("flag_code") or atk.get("flag_country", "Unknown")
        flag_counts[c] = flag_counts.get(c, 0) + 1
        # flag_country is "<emoji> <name>" — keep only the emoji, the code
        # covers the label (e.g. "PA"), not the full country name.
        flag_emoji[c] = atk.get("flag_country", "").split(" ", 1)[0]
        flag_codes[c] = atk.get("flag_code", c)

    flag_stats = [
        {
            "country": f"{flag_emoji.get(k, '')} {flag_codes.get(k, k)}".strip(),
            "code": flag_codes.get(k, k),
            "count": v,
            "pct": round((v / total_atks) * 100, 1),
        }
        for k, v in sorted(flag_counts.items(), key=lambda item: item[1], reverse=True)
    ]

    return attacks, flag_stats, total_atks


# --- Derived narrative -----------------------------------------------------


def _pct_change(current, baseline):
    if current is None or not baseline:
        return None
    return (current - baseline) / baseline * 100


def build_press_dispatch(snapshot, total_attacks: int) -> dict:
    """Every figure and every qualitative word in the press dispatch, derived
    from the live snapshot.

    Nothing in a document offered to newsrooms for reproduction should be a
    string literal: a hardcoded price or severity word goes stale the moment
    the index moves and turns the dispatch into a contradiction of the page
    it sits on.
    """
    brent = hormuz.component_result(snapshot, "brent")
    traffic = hormuz.component_result(snapshot, "ship_traffic")
    war_risk = hormuz.component_result(snapshot, "war_risk")
    reroutes = hormuz.component_result(snapshot, "reroutes")
    driver = hormuz.top_driver(snapshot)

    ceasefire_months = []
    for ev in GEOPOLITICAL_EVENTS:
        if not ev.get("is_ceasefire"):
            continue
        try:
            d = date.fromisoformat(ev["date"])
        except ValueError:
            continue
        part = "early" if d.day <= 10 else ("mid" if d.day <= 20 else "late")
        ceasefire_months.append(f"{part}-{MONTH_NAMES[d.month - 1]}")

    traffic_drop = _pct_change(traffic.current_value if traffic else None,
                              traffic.baseline_value if traffic else 0)
    brent_change = _pct_change(brent.current_value if brent else None,
                              brent.baseline_value if brent else 0)
    war_risk_multiple = None
    if war_risk and war_risk.current_value and war_risk.baseline_value:
        war_risk_multiple = war_risk.current_value / war_risk.baseline_value

    # Second-largest contributor, so the "key drivers" sentence names what is
    # actually moving the index rather than a fixed pair of components.
    ranked = sorted(snapshot.components, key=lambda c: c.contribution, reverse=True)

    return {
        "score": snapshot.score,
        "level": snapshot.level_label,
        "level_lower": snapshot.level_label.lower(),
        "points_above_baseline": round(snapshot.score - scoring.SCALE_MIN, 1),
        "week_start": snapshot.week_start,
        "total_attacks": total_attacks,
        "brent": brent.current_value if brent else None,
        "brent_baseline": brent.baseline_value if brent else None,
        "brent_change_pct": round(brent_change, 1) if brent_change is not None else None,
        "brent_direction": "above" if (brent_change or 0) >= 0 else "below",
        "traffic": traffic.current_value if traffic else None,
        "traffic_baseline": traffic.baseline_value if traffic else None,
        "traffic_drop_pct": round(abs(traffic_drop), 1) if traffic_drop is not None else None,
        "traffic_direction": "below" if (traffic_drop or 0) < 0 else "above",
        "war_risk": war_risk.current_value if war_risk else None,
        "war_risk_multiple": round(war_risk_multiple, 1) if war_risk_multiple else None,
        "reroutes": reroutes.current_value if reroutes else None,
        "driver_label": driver.component.label if driver else None,
        "driver_points": round(driver.contribution, 1) if driver else None,
        "driver_2_label": ranked[1].component.label if len(ranked) > 1 else None,
        "driver_2_points": round(ranked[1].contribution, 1) if len(ranked) > 1 else None,
        "ceasefire_months": ceasefire_months,
        "degraded": snapshot.degraded,
    }


def _history_meta() -> dict:
    """Provenance flags stored alongside the weekly series."""
    return storage.load_history(hormuz.INDEX_KEY)


def _observation_meta(key: str) -> dict:
    """Provenance for one component's current hand-entered value, if it has one.

    Returns {} for a component with no observation on file, so an automatic
    series does not sprout empty "observed_by" fields in the API response.
    """
    keyed = manual_data.entry(key)
    if keyed is None:
        return {}
    return {
        "observed_on": keyed.as_of,
        "observed_source": keyed.source,
        "observation_note": keyed.note,
        "confidence": keyed.confidence,
    }


def component_correlations(history: list[dict]) -> dict:
    """Pearson correlation between every pair of component series in history.

    Published because Brent, TTF gas and VIX together carry 50% of index weight
    and tend to move together during an energy shock — the composite is less
    diversified than seven components implies, and a reader should be able to
    see by how much rather than take the caveat on trust.
    """
    keys = [c.key for c in hormuz.COMPONENTS]
    series: dict[str, list[float]] = {k: [] for k in keys}
    for week in history:
        raw = week.get("raw_values", {})
        if any(raw.get(k) is None for k in keys):
            continue
        for k in keys:
            series[k].append(float(raw[k]))

    n = len(next(iter(series.values()), []))
    if n < 3:
        return {"n": n, "columns": keys, "matrix": {}}

    means = {k: sum(v) / n for k, v in series.items()}

    def corr(a: str, b: str) -> float | None:
        va, vb = series[a], series[b]
        ma, mb = means[a], means[b]
        num = sum((x - ma) * (y - mb) for x, y in zip(va, vb))
        da = sum((x - ma) ** 2 for x in va) ** 0.5
        db = sum((y - mb) ** 2 for y in vb) ** 0.5
        if da == 0 or db == 0:
            return None
        return round(num / (da * db), 3)

    return {
        "n": n,
        "columns": keys,
        "labels": {c.key: c.label for c in hormuz.COMPONENTS},
        "matrix": {a: {b: corr(a, b) for b in keys} for a in keys},
    }


def _common(**extra):
    """Template context every page needs."""
    ctx = {
        "site_origin": SITE_ORIGIN,
        "license_name": DATA_LICENSE_NAME,
        "license_url": DATA_LICENSE_URL,
    }
    ctx.update(extra)
    return ctx


# --- Pages -----------------------------------------------------------------


def _report_cards(snapshot):
    """REPORTS with each entry's own headline figure and status attached.

    The home page's card loop previously read snapshot.score and
    snapshot.level_status directly, which was correct while there was exactly
    one report and silently wrong the moment there were two: the Lok Sabha card
    displayed the Hormuz index score.

    Figures come from the precomputed home artifact. The in-request fallback
    below only runs before the first update, and derives the Hormuz figure from
    the snapshot already in hand rather than fetching anything.
    """
    figures = dict(precomputed.load("home").get("cards") or {})

    if "hormuz-index" not in figures:
        figures["hormuz-index"] = {
            "value": f"{snapshot.score:.1f}",
            "unit": "score",
            "status": snapshot.level_status,
        }

    if "lok-sabha-index" not in figures:
        from app.elections.routes import headline as elections_headline

        ls = elections_headline()
        figures["lok-sabha-index"] = {
            "value": str(ls["value"]) if ls else None,
            "unit": ls["unit"] if ls else None,
            # The projection has no crisis banding, so it carries the neutral
            # status rather than borrowing the Hormuz index's colour.
            "status": "good",
        }

    cards = []
    for report in REPORTS:
        card = dict(report)
        card.update(figures.get(report["slug"], {"value": None, "unit": None, "status": "good"}))
        cards.append(card)
    return cards


@bp.route("/")
def home():
    snapshot = get_snapshot()
    history = hormuz.get_history()
    prev_score = history[-2]["score"] if len(history) >= 2 else None
    delta = (snapshot.score - prev_score) if prev_score is not None else 0.0

    html = render_template(
        "home.html",
        **_common(
            reports=_report_cards(snapshot),
            snapshot=snapshot,
            hormuz_score=snapshot.score,
            hormuz_level=snapshot.level_label,
            hormuz_status=snapshot.level_status,
            delta=delta,
            scale_pct=scoring.scale_pct(snapshot.score),
            scale_min=scoring.SCALE_MIN,
            scale_max=scoring.SCALE_MAX,
        ),
    )
    return _cached(Response(html, mimetype="text/html"))


@bp.route("/material-design")
def material_design():
    snapshot = get_snapshot()
    html = render_template(
        "material_demo.html",
        **_common(
            snapshot=snapshot,
        ),
    )
    return _cached(Response(html, mimetype="text/html"))


@bp.route("/hormuz-index")
def hormuz_index():
    snapshot = get_snapshot()
    history = hormuz.get_history()
    prev_score = history[-2]["score"] if len(history) >= 2 else None
    delta = (snapshot.score - prev_score) if prev_score is not None else 0.0

    attacks, flag_stats, total_attacks = _load_vessel_attacks()

    monthly_map: dict[str, int] = {}
    for a in attacks:
        m_key = a["date"][:7]
        monthly_map[m_key] = monthly_map.get(m_key, 0) + 1

    months = sorted(monthly_map) or ["2026-01"]
    month_labels = [
        f"{MONTH_NAMES[int(m[5:7]) - 1][:3]} {m[:4]}" for m in months
    ]

    cumulative_attacks = []
    running_total = 0
    for m in months:
        running_total += monthly_map.get(m, 0)
        cumulative_attacks.append(running_total)

    # Reader perception, plotted on the model's own week axis. Weeks with no
    # ballots (or too few to publish) map to None, which reaches the chart as
    # a null and draws a gap rather than a fabricated point.
    #
    # Read from the precomputed artifact, not from the database. These three
    # values used to cost ~19s on a cold hit while a sleeping Neon compute node
    # woke up, and they are settled weekly aggregates — there is nothing to
    # gain from asking Postgres for them on every page view. The current week's
    # figure is the one that moves, and vote.js re-fetches that from
    # /api/hormuz-index/sentiment as soon as the page loads.
    pre = precomputed.load("hormuz-index")
    sentiment_history = pre.get("sentiment_history", [])
    perception_by_week = pre.get("perception_by_week", {})
    perception_series = pre.get("perception_series") or [None] * len(history)
    sentiment = dict(pre.get("sentiment") or votes.empty_summary())

    # `available` in the artifact records whether the *build machine* could
    # reach Postgres, which says nothing about whether this request can. Baked
    # in, one failed update run left the block reading "Voting unavailable" on
    # a perfectly healthy deploy until the next successful precompute. Recheck
    # it here — is_configured() reads an environment variable and a cooldown
    # flag, so it costs nothing and never opens a connection.
    sentiment["available"] = db.is_configured()

    html = render_template(
        "hormuz.html",
        **_common(
            snapshot=snapshot,
            history=history,
            prev_score=prev_score,
            delta=delta,
            events=GEOPOLITICAL_EVENTS,
            baseline_values=hormuz.BASELINE_VALUES,
            baseline_window=hormuz.BASELINE_WINDOW,
            vessel_attacks=attacks,
            vessel_data_synthetic=VESSEL_DATA_IS_SYNTHETIC,
            flag_stats=flag_stats,
            total_attacks=total_attacks,
            month_labels=month_labels,
            cumulative_attacks=cumulative_attacks,
            sentiment=sentiment,
            sentiment_history=sentiment_history,
            perception_series=perception_series,
            perception_by_week=perception_by_week,
            press=build_press_dispatch(snapshot, total_attacks),
            top_driver=hormuz.top_driver(snapshot),
            band_positions=scoring.band_positions(),
            scale_pct=scoring.scale_pct(snapshot.score),
            scale_min=scoring.SCALE_MIN,
            scale_max=scoring.SCALE_MAX,
            license_name=DATA_LICENSE_NAME,
            license_url=DATA_LICENSE_URL,
            # The methodology now renders as a tab on this page.
            **_methodology_context(),
        ),
    )
    return _cached(Response(html, mimetype="text/html"))


@bp.route("/methodology")
def methodology():
    """Permanent redirect to the methodology tab on the index it documents.

    The methodology stopped being its own page: it describes one index's
    formula, weights and caps, so a reader checking the number should not have
    to leave the page showing it. The URL is kept as a 301 rather than deleted
    because it was indexed, is cited in the event log's source links, and may
    have been quoted externally — a 404 would break all three.
    """
    return redirect("/hormuz-index#methodology", code=301)


def _methodology_context():
    """Context the methodology partial needs, wherever it is rendered."""
    return dict(
        components=hormuz.COMPONENTS,
        bands=scoring.LEVEL_BANDS,
        degraded_threshold=scoring.DEGRADED_STALE_WEIGHT,
        durable_storage=storage.is_durable(),
    )



@bp.route("/data")
def data_page():
    """Permanent 301 redirect to the raw JSON data endpoint."""
    return redirect("/api/hormuz-index/data.json", code=301)


@bp.route("/terms")
def terms_page():
    html = render_template("terms.html", **_common())
    return _cached(Response(html, mimetype="text/html"))


@bp.route("/reports/<slug>")
def coming_soon(slug):
    category = next((c for c in NAV_CATEGORIES if c["slug"] == slug), None)
    if category is None:
        abort(404)
    html = render_template("coming_soon.html", **_common(category=category))
    return _cached(Response(html, mimetype="text/html"))


# --- API -------------------------------------------------------------------


@bp.route("/api/hormuz-index/data.json")
def api_hormuz_json():
    snapshot = get_snapshot()
    history = hormuz.get_history()
    resp = jsonify({
        "ticker": "HMX-INDEX",
        "index_name": "Hormuz Crisis Index",
        "license": {"name": DATA_LICENSE_NAME, "url": DATA_LICENSE_URL},
        "attribution": "MyDataLabs Hormuz Crisis Index (HMX-INDEX) — mydatalabs.in",
        "generated_at": snapshot.generated_at,
        "current_snapshot": {
            "week_start": snapshot.week_start,
            "score": snapshot.score,
            "level_label": snapshot.level_label,
            "level_status": snapshot.level_status,
            "degraded": snapshot.degraded,
            "stale_weight": snapshot.stale_weight,
        },
        "baseline": {
            "window": hormuz.BASELINE_WINDOW,
            "values": hormuz.BASELINE_VALUES,
        },
        # Series whose weekly history was re-anchored rather than measured. Both
        # this list and the notes below are generated on every update run from
        # the feeder file and the current snapshot (app/manual_data.py). They
        # were hand-written prose until 2026-08, which meant they described
        # whatever was true the day somebody typed them.
        "reconstructed_series": _history_meta().get("reconstructed_series", []),
        "series_source_notes": _history_meta().get("series_source_notes", {}),
        "scale": {"min": scoring.SCALE_MIN, "max": scoring.SCALE_MAX},
        "components": [
            {
                "key": c.component.key,
                "label": c.component.label,
                "weight": c.component.weight,
                "unit": c.component.unit,
                "current_value": c.current_value,
                "baseline_value": c.baseline_value,
                "cap_pct": c.component.cap_pct,
                "inverted": c.component.invert,
                "stress_score": round(c.stress, 2),
                "contribution": round(c.contribution, 2),
                "source": c.component.source,
                "manual": c.component.manual,
                "update_cadence": c.component.update_cadence,
                "last_updated": c.last_updated,
                "stale": c.stale,
                "carried_forward": c.carried_forward,
                # Per-point provenance for the hand-entered components. The
                # series-level reconstructed_series flag above cannot say that
                # this week's war-risk figure is a real broker quote while
                # earlier weeks were re-anchored; this can.
                **_observation_meta(c.component.key),
            }
            for c in snapshot.components
        ],
        "component_correlations": component_correlations(history),
        "history": history,
    })
    return _cached(resp)


@bp.route("/api/hormuz-index/data.csv")
def api_hormuz_csv():
    history = hormuz.get_history()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Week Start",
        "Composite Score",
        "Level",
        "Brent ($/bbl)",
        "Ship Traffic (transits/wk)",
        "War Risk Insurance (%)",
        "Tanker Freight (BDTI)",
        "TTF Gas (EUR/MWh)",
        "VIX Index",
        "Cape Reroutes (%)",
    ])

    for w in history:
        rv = w.get("raw_values", {})
        writer.writerow([
            w.get("week_start", ""),
            w.get("score", ""),
            w.get("level_label", ""),
            rv.get("brent", ""),
            rv.get("ship_traffic", ""),
            rv.get("war_risk", ""),
            rv.get("tanker_freight", ""),
            rv.get("ttf_gas", ""),
            rv.get("vix", ""),
            rv.get("reroutes", ""),
        ])

    return _cached(Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=hormuz_crisis_index_history.csv"},
    ))


@bp.route("/api/health")
def health():
    """Cheap liveness probe that also reports whether persistence is real."""
    return jsonify({
        "ok": True,
        "durable_storage": storage.is_durable(),
        "storage_backend": storage.storage_backend(),
        "snapshot_cached": _snapshot_cache["value"] is not None,
        "snapshot_age_seconds": (
            round(time.time() - _snapshot_cache["fetched_at"])
            if _snapshot_cache["value"] is not None else None
        ),
    })


@bp.route("/api/cron/update-hormuz", methods=["GET", "POST"])
def cron_update_hormuz():
    secret = os.environ.get("CRON_SECRET")
    if secret:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {secret}":
            abort(401)

    snapshot = hormuz.compute_snapshot(persist=True)
    # Refresh the read cache so the next page view sees the new numbers.
    _snapshot_cache["value"] = snapshot
    _snapshot_cache["fetched_at"] = time.time()

    # Report persistence honestly. On a read-only serverless filesystem the
    # write lands in /tmp and disappears with the instance; returning a bare
    # 200 would let a broken pipeline look healthy indefinitely.
    persisted = bool(snapshot.persisted)
    return jsonify({
        "score": snapshot.score,
        "level": snapshot.level_label,
        "week_start": snapshot.week_start,
        "degraded": snapshot.degraded,
        "stale_weight": snapshot.stale_weight,
        "persisted": persisted,
        "storage_backend": storage.storage_backend(),
    }), (200 if persisted else 202)


# --- Community sentiment ---------------------------------------------------
# The Public Perception Index: what readers say the crisis feels like, on the
# same 100–200 scale as the model score. See app/votes.py for the identity and
# data-protection design; nothing here reads or stores personal data.

# Accepted shape of the browser's anonymous vote token. Deliberately strict:
# the token is only ever a client-generated UUID, and refusing anything else
# keeps arbitrary caller-supplied strings out of the hash input.
_VOTER_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def _voter_token() -> str | None:
    token = request.headers.get("X-Voter-Token", "").strip()
    return token if _VOTER_TOKEN_RE.match(token) else None


def _origin_hash(week_start: str) -> str:
    """Coarse per-network fingerprint used only to cap ballot stuffing.

    Built from the forwarded client IP and user agent, immediately hashed with
    a week-derived salt. Neither input is stored or logged by this application.
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    ip = forwarded.split(",")[0].strip() or (request.remote_addr or "unknown")
    return votes.hash_origin(ip, request.headers.get("User-Agent", ""), week_start)


def _no_store(resp: Response) -> Response:
    """Sentiment responses are per-voter and live; never let a CDN hold them."""
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/api/hormuz-index/sentiment", methods=["GET"])
def api_sentiment():
    token = _voter_token()
    voter_hash = votes.hash_voter_token(token) if token else None
    summary = votes.get_summary(voter_hash=voter_hash)
    # The weekly series is a second query, so it is opt-in: the vote block
    # polls this endpoint after every ballot and only needs the current week.
    if request.args.get("history") in ("1", "true", "yes"):
        summary["history"] = votes.get_history()
    return _no_store(jsonify(summary))


@bp.route("/api/hormuz-index/sentiment", methods=["POST"])
def api_sentiment_vote():
    token = _voter_token()
    if not token:
        return _no_store(jsonify({"error": "Missing or malformed voter token."})), 400

    bad_rating = {
        "error": f"Rating must be a number from "
                 f"{votes.RATING_MIN} to {votes.RATING_MAX}."
    }
    payload = request.get_json(silent=True) or {}
    try:
        # The ballot is a dragged position, so it arrives fractional. Rounding
        # here as well as in the model keeps a client that sends fifteen decimal
        # places from writing them.
        value = round(float(payload.get("value")), votes.RATING_DP)
    except (TypeError, ValueError):
        return _no_store(jsonify(bad_rating)), 400
    # Range is checked here as well as in votes.cast_vote so a malformed ballot
    # answers 400 rather than sharing the 429 used for the rate limit. The
    # comparison also rejects NaN, which survives float() intact.
    if not votes.RATING_MIN <= value <= votes.RATING_MAX:
        return _no_store(jsonify(bad_rating)), 400

    # A missing database is not the caller being throttled. Answering the 429
    # below for it sent anyone reading the logs looking for a ballot-stuffer
    # when the real fault was an unset DATABASE_URL.
    if not db.is_configured():
        return _no_store(jsonify({"error": "Voting is not available right now."})), 503

    week_start = votes.current_week_start()
    try:
        summary = votes.cast_vote(
            value,
            voter_hash=votes.hash_voter_token(token),
            origin_hash=_origin_hash(week_start),
            week_start=week_start,
        )
    except votes.VoteRejected as exc:
        return _no_store(jsonify({"error": str(exc)})), 429
    except Exception:
        return _no_store(jsonify({"error": "Could not record your vote. Try again."})), 503

    return _no_store(jsonify(summary))


@bp.route("/api/hormuz-index/sentiment", methods=["DELETE"])
def api_sentiment_withdraw():
    """Let a visitor remove their own vote — the erasure path for the vote block."""
    token = _voter_token()
    if not token:
        return _no_store(jsonify({"error": "Missing or malformed voter token."})), 400
    try:
        summary = votes.withdraw_vote(votes.hash_voter_token(token))
    except votes.VoteRejected as exc:
        return _no_store(jsonify({"error": str(exc)})), 503
    except Exception:
        return _no_store(jsonify({"error": "Could not withdraw your vote."})), 503
    return _no_store(jsonify(summary))


# --- Crawler-facing files --------------------------------------------------


@bp.route("/sitemap.xml")
def sitemap():
    # Only substantive, indexable pages. The /reports/* placeholders render a
    # near-identical "in development" template and are noindexed, so listing
    # them here would submit five thin duplicates for indexing.
    pages = [
        {"loc": f"{SITE_ORIGIN}/", "priority": "1.0", "changefreq": "daily"},
        {"loc": f"{SITE_ORIGIN}/hormuz-index", "priority": "0.9", "changefreq": "daily"},
        {"loc": f"{SITE_ORIGIN}/lok-sabha-index", "priority": "0.9", "changefreq": "daily"},
        {"loc": f"{SITE_ORIGIN}/terms", "priority": "0.5", "changefreq": "monthly"},
    ]

    xml = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    today = date.today().isoformat()
    for p in pages:
        xml.append("  <url>")
        xml.append(f"    <loc>{p['loc']}</loc>")
        xml.append(f"    <lastmod>{today}</lastmod>")
        xml.append(f"    <changefreq>{p['changefreq']}</changefreq>")
        xml.append(f"    <priority>{p['priority']}</priority>")
        xml.append("  </url>")
    xml.append("</urlset>")

    return _cached(Response("\n".join(xml), mimetype="application/xml"), 3600)


@bp.route("/robots.txt")
def robots():
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /reports/\n"
        "\n"
        f"Sitemap: {SITE_ORIGIN}/sitemap.xml\n"
    )
    return _cached(Response(content, mimetype="text/plain"), 3600)


@bp.route("/llms.txt")
def llms_txt():
    """Structured pointer file for AI search crawlers.

    The index is factual, numeric and citation-shaped, which makes AI answer
    surfaces a more realistic channel than competing with wire services for
    head terms. This tells them what exists and how to attribute it.
    """
    snapshot = get_snapshot()
    content = f"""# MyDataLabs

> Quantitative composite indices tracking geopolitical stress, maritime
> chokepoint disruption, and energy dislocation. Flagship index: the Hormuz
> Crisis Index (HMX-INDEX), a weekly composite scored against a calm baseline
> of 100.0 (baseline week {hormuz.BASELINE_WINDOW}).

Current HMX-INDEX reading: {snapshot.score:.1f} ({snapshot.level_label}), week of {snapshot.week_start}.

## Core pages

- [Hormuz Crisis Index dashboard]({SITE_ORIGIN}/hormuz-index): live composite score, component breakdown, weekly trajectory since January 2026.
- [Lok Sabha Projection Engine]({SITE_ORIGIN}/lok-sabha-index): daily 543-seat projection from CVoter's option-level opinion trackers, Monte Carlo intervals, event impact analysis, 2019/2024 backtest.
- [Methodology]({SITE_ORIGIN}/hormuz-index#methodology): index formula, component weights, cap thresholds and their rationale, baseline selection, known limitations.

## Machine-readable data

- [JSON]({SITE_ORIGIN}/api/hormuz-index/data.json): current snapshot, per-component breakdown, full weekly history.
- [CSV]({SITE_ORIGIN}/api/hormuz-index/data.csv): weekly history with raw component values.

## Licence and attribution

Index data is published under {DATA_LICENSE_NAME} ({DATA_LICENSE_URL}).
Cite as: MyDataLabs Hormuz Crisis Index (HMX-INDEX), mydatalabs.in.

## Important limitations

- Four of seven components (50% of index weight) are entered manually from
  paywalled sources and refresh weekly, not continuously. Each component
  publishes its own last-updated date.
- The vessel incident log shown on the dashboard is compiled separately from
  the index components and contributes nothing to the composite score.
- The composite is a one-sided stress index with a floor of 100.0; it does not
  express conditions calmer than the baseline period.
"""
    return _cached(Response(content, mimetype="text/plain; charset=utf-8"), 3600)


@bp.route("/favicon.ico")
def favicon():
    return redirect("/static/img/favicon.png", code=301)
