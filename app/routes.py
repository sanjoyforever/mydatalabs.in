import csv
import io
import json
import os
from datetime import date, timedelta

from flask import Blueprint, Response, abort, jsonify, render_template, request, send_from_directory

from app.indices import hormuz

bp = Blueprint("main", __name__)


@bp.route("/app-static/<path:filename>")
def serve_static_asset(filename):
    app_dir = os.path.dirname(os.path.abspath(__file__))
    static_dir = os.path.join(app_dir, "static")
    return send_from_directory(static_dir, filename)

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
]

GEOPOLITICAL_EVENTS = [
    {
        "date": "2026-01-05",
        "title": "Baseline Index Initialized",
        "description": "Composite score anchored at 100.0 baseline across normal non-crisis maritime operations.",
        "impact": "Neutral",
        "source_name": "MyDataLabs Methodology",
        "source_url": "https://mydatalabs.in",
    },
    {
        "date": "2026-02-23",
        "title": "Gulf of Oman Patrol Alert",
        "description": "Increased naval advisory presence reported. War-risk insurance premiums increased by +50%.",
        "impact": "Moderate (+9.5 pts)",
        "source_name": "Reuters Middle East",
        "source_url": "https://www.reuters.com/world/middle-east/",
    },
    {
        "date": "2026-03-02",
        "title": "Commercial AIS Signal Dropouts",
        "description": "Tankers reporting GPS spoofing and elevated spoofing warnings near Qeshm Island.",
        "impact": "High (+8.4 pts)",
        "source_name": "Lloyd's List Intelligence",
        "source_url": "https://lloydslist.maritimeintelligence.informa.com/",
    },
    {
        "date": "2026-03-09",
        "title": "Joint Maritime Maneuvers",
        "description": "Naval live-fire exercises announced in international shipping lanes. Cape reroutes rise to 21%.",
        "impact": "High (+4.7 pts)",
        "source_name": "Reuters Energy",
        "source_url": "https://www.reuters.com/business/energy/",
    },
    {
        "date": "2026-03-16",
        "title": "Temporary Maritime Ceasefire Declared",
        "description": "72-hour diplomatic truce declared in Gulf transit zone; insurance surcharges temporarily ease.",
        "impact": "Ceasefire Easing (-7.1 pts)",
        "is_ceasefire": True,
        "source_name": "Reuters Middle East Dispatch",
        "source_url": "https://www.reuters.com/world/middle-east/",
    },
    {
        "date": "2026-04-06",
        "title": "Regional Maritime Ceasefire Signed",
        "description": "Multinational diplomatic truce signed establishing permanent escort corridor; stress index eases.",
        "impact": "Ceasefire Easing (-5.1 pts)",
        "is_ceasefire": True,
        "source_name": "Financial Times World Coverage",
        "source_url": "https://www.ft.com/world",
    },
    {
        "date": "2026-06-15",
        "title": "Mid-Summer Ceasefire Extension",
        "description": "Renewed ceasefire agreement signed by regional powers; vessel transits temporarily recover.",
        "impact": "Ceasefire Easing (-9.2 pts)",
        "is_ceasefire": True,
        "source_name": "S&P Global Commodity Insights",
        "source_url": "https://www.spglobal.com/commodityinsights/en",
    },
]

CEASEFIRE_DATES = {"2026-03-16", "2026-04-06", "2026-06-15"}
CEASEFIRE_MAP = {e["date"]: e for e in GEOPOLITICAL_EVENTS if e.get("is_ceasefire")}


@bp.route("/")
def home():
    snapshot = hormuz.compute_snapshot(persist=False)
    history = hormuz.get_history()
    prev_score = history[-2]["score"] if len(history) >= 2 else None
    delta = (snapshot.score - prev_score) if prev_score is not None else 0.0

    return render_template(
        "home.html",
        nav_categories=NAV_CATEGORIES,
        reports=REPORTS,
        snapshot=snapshot,
        hormuz_score=snapshot.score,
        hormuz_level=snapshot.level_label,
        hormuz_status=snapshot.level_status,
        delta=delta,
        events=GEOPOLITICAL_EVENTS[-4:],
    )


def _trend_chart(history, width=760, height=270, pad_x=32, pad_y_top=42, pad_y_bottom=46):
    """Scale weekly scores into SVG coordinates for an institutional interactive line & area chart with X-axis."""
    if not history:
        return None

    scores = [w["score"] for w in history]
    min_val = min(scores + [100.0])
    max_val = max(scores + [160.0])
    span = (max_val - min_val) or 1.0

    n = len(history)
    points = []
    ceasefire_points = []
    axis_y = height - pad_y_bottom

    # Month name mapping
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    cf_count = 0
    for i, week in enumerate(history):
        x = pad_x if n == 1 else pad_x + (i / (n - 1)) * (width - 2 * pad_x)
        # Scale Y within [pad_y_top, axis_y]
        y = axis_y - ((week["score"] - min_val) / span) * (axis_y - pad_y_top)
        
        ws = week.get("week_start", "")
        try:
            parts = ws.split("-")
            m_idx = int(parts[1]) - 1
            short_date = f"{months[m_idx]} {parts[2]}"
        except Exception:
            short_date = ws

        is_cf = ws in CEASEFIRE_DATES
        show_label = (i % 4 == 0) or (i == n - 1)

        cf_info = CEASEFIRE_MAP.get(ws, {})
        
        pt = {
            "x": round(x, 1),
            "y": round(y, 1),
            "week": week,
            "score_str": f"{week['score']:.1f}",
            "short_date": short_date,
            "show_label": show_label,
            "is_ceasefire": is_cf,
            "ceasefire_title": cf_info.get("title", "Ceasefire Declared"),
            "source_name": cf_info.get("source_name", "News Report"),
            "source_url": cf_info.get("source_url", "#"),
        }

        if is_cf:
            # Stagger badge Y position between 12 and 34 to avoid horizontal box collisions
            pt["badge_y"] = 12 if (cf_count % 2 == 0) else 34
            cf_count += 1
            ceasefire_points.append(pt)

        points.append(pt)

    baseline_y = axis_y - ((100.0 - min_val) / span) * (axis_y - pad_y_top)
    polyline = " ".join(f"{p['x']},{p['y']}" for p in points)

    # Area polygon goes from first point down to baseline, across to last point baseline, and back up
    first_x = points[0]["x"]
    last_x = points[-1]["x"]
    area_polygon = f"{first_x},{axis_y} {polyline} {last_x},{axis_y}"

    return {
        "width": width,
        "height": height,
        "pad_x": pad_x,
        "points": points,
        "ceasefire_points": ceasefire_points,
        "polyline": polyline,
        "area_polygon": area_polygon,
        "baseline_y": round(baseline_y, 1),
        "axis_y": round(axis_y, 1),
        "min_val": min_val,
        "max_val": max_val,
    }


def _load_vessel_attacks():
    """Load vessel attack incidents dataset and compute flag state & weekly analytics."""
    data_path = os.path.join(os.path.dirname(__file__), "data", "vessel_attacks.json")
    if not os.path.exists(data_path):
        return [], [], 0

    try:
        with open(data_path, "r", encoding="utf-8") as f:
            attacks = json.load(f)
    except Exception:
        return [], [], 0

    total_atks = len(attacks)
    if total_atks == 0:
        return [], [], 0

    # Aggregate by Flag State / Country
    flag_counts = {}
    flag_codes = {}
    for atk in attacks:
        c = atk.get("flag_country", "Unknown")
        flag_counts[c] = flag_counts.get(c, 0) + 1
        flag_codes[c] = atk.get("flag_code", "")

    flag_stats = [
        {
            "country": k,
            "code": flag_codes.get(k, ""),
            "count": v,
            "pct": round((v / total_atks) * 100, 1),
        }
        for k, v in sorted(flag_counts.items(), key=lambda item: item[1], reverse=True)
    ]

    return attacks, flag_stats, total_atks


@bp.route("/hormuz-index")
def hormuz_index():
    snapshot = hormuz.compute_snapshot(persist=False)
    history = hormuz.get_history()
    trend = _trend_chart(history)
    prev_score = history[-2]["score"] if len(history) >= 2 else None
    delta = (snapshot.score - prev_score) if prev_score is not None else 0.0

    attacks, flag_stats, total_attacks = _load_vessel_attacks()

    # Calculate cumulative monthly attack counts
    monthly_map = {}
    for a in attacks:
        m_key = a["date"][:7]
        monthly_map[m_key] = monthly_map.get(m_key, 0) + 1

    months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]
    month_labels = ["Jan 2026", "Feb 2026", "Mar 2026", "Apr 2026", "May 2026", "Jun 2026", "Jul 2026"]

    cumulative_attacks = []
    running_total = 0
    for m in months:
        running_total += monthly_map.get(m, 0)
        cumulative_attacks.append(running_total)

    return render_template(
        "hormuz.html",
        nav_categories=NAV_CATEGORIES,
        snapshot=snapshot,
        history=history,
        trend=trend,
        prev_score=prev_score,
        delta=delta,
        events=GEOPOLITICAL_EVENTS,
        baseline_values=hormuz.BASELINE_VALUES,
        vessel_attacks=attacks,
        flag_stats=flag_stats,
        total_attacks=total_attacks,
        month_labels=month_labels,
        cumulative_attacks=cumulative_attacks,
    )


@bp.route("/reports/<slug>")
def coming_soon(slug):
    category = next((c for c in NAV_CATEGORIES if c["slug"] == slug), None)
    if category is None:
        abort(404)
    return render_template("coming_soon.html", nav_categories=NAV_CATEGORIES, category=category)


@bp.route("/api/hormuz-index/data.json")
def api_hormuz_json():
    snapshot = hormuz.compute_snapshot(persist=False)
    history = hormuz.get_history()
    return jsonify({
        "ticker": "HMX-INDEX",
        "index_name": "Hormuz Crisis Index",
        "current_snapshot": {
            "week_start": snapshot.week_start,
            "score": snapshot.score,
            "level_label": snapshot.level_label,
            "level_status": snapshot.level_status,
        },
        "baseline_values": hormuz.BASELINE_VALUES,
        "components": [
            {
                "key": c.component.key,
                "label": c.component.label,
                "weight": c.component.weight,
                "unit": c.component.unit,
                "current_value": c.current_value,
                "baseline_value": c.baseline_value,
                "stress_score": round(c.stress, 2),
                "contribution": round(c.contribution, 2),
                "source": c.component.source,
            }
            for c in snapshot.components
        ],
        "history": history,
    })


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

    csv_data = output.getvalue()
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=hormuz_crisis_index_history.csv"},
    )


@bp.route("/api/cron/update-hormuz", methods=["GET", "POST"])
def cron_update_hormuz():
    secret = os.environ.get("CRON_SECRET")
    if secret:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {secret}":
            abort(401)

    snapshot = hormuz.compute_snapshot(persist=True)
    return jsonify(
        {
            "score": snapshot.score,
            "level": snapshot.level_label,
            "week_start": snapshot.week_start,
        }
    )

