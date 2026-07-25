"""Hormuz Crisis Index: component definitions, baseline, and data fetchers.

Baseline week: Feb 1-5, 2026 ("calm", composite = 100).

Three components (ship traffic, war-risk insurance, tanker freight) come from
paywalled sources (Lloyd's List, Reuters/S&P, Baltic Exchange) with no free API.
Until a paid feed is wired up, those are entered manually each week by editing
the "manual_overrides" block of app/data/hormuz_history.json — the fetch
functions below return None for them, and compute_weekly_snapshot() falls back
to the last manual value (marking it stale if it's more than one week old).
"""
from __future__ import annotations

from datetime import date, timedelta

from app.scoring import Component, CompositeResult, compute_composite
from app import storage

INDEX_KEY = "hormuz"

# --- Component definitions -------------------------------------------------

COMPONENTS: list[Component] = [
    Component(
        key="brent",
        label="Brent Crude",
        weight=0.30,
        source="yfinance (BZ=F)",
        cap_pct=55,
        unit="$/bbl",
    ),
    Component(
        key="ship_traffic",
        label="Hormuz Ship Traffic",
        weight=0.15,
        source="Lloyd's List",
        cap_pct=50,
        invert=True,  # a DECLINE in transits is the stress signal
        unit="transits/wk",
    ),
    Component(
        key="war_risk",
        label="War-Risk Insurance",
        weight=0.15,
        source="Reuters / S&P Global",
        cap_pct=400,
        unit="% hull value",
    ),
    Component(
        key="tanker_freight",
        label="Tanker Freight (BDTI)",
        weight=0.15,
        source="Baltic Exchange",
        cap_pct=75,
        unit="index",
    ),
    Component(
        key="ttf_gas",
        label="TTF European Gas",
        weight=0.10,
        source="yfinance (TTF=F)",
        cap_pct=95,
        unit="EUR/MWh",
    ),
    Component(
        key="vix",
        label="VIX Volatility Index",
        weight=0.10,
        source="yfinance (^VIX)",
        cap_pct=200,
        unit="",
    ),
    Component(
        key="reroutes",
        label="Cape of Good Hope Reroutes",
        weight=0.05,
        source="AIS / Vortexa",
        cap_pct=250,
        unit="% of traffic",
    ),
]

# Baseline week: Feb 1-5, 2026 weekly averages
BASELINE_VALUES: dict[str, float] = {
    "brent": 65.0,
    "ship_traffic": 34,
    "war_risk": 0.10,
    "tanker_freight": 900,
    "ttf_gas": 33.0,
    "vix": 14.5,
    "reroutes": 8.0,
}

YFINANCE_TICKERS = {
    "brent": "BZ=F",
    "ttf_gas": "TTF=F",
    "vix": "^VIX",
}

MANUAL_KEYS = {"ship_traffic", "war_risk", "tanker_freight", "reroutes"}


def fetch_live_values() -> dict[str, float | None]:
    """Fetch the free/live-sourced components via yfinance. Manual-only keys
    come back as None here; the caller fills them from manual_overrides."""
    try:
        import yfinance as yf
    except ImportError:
        return {k: None for k in YFINANCE_TICKERS}

    values: dict[str, float | None] = {}
    for key, ticker in YFINANCE_TICKERS.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            values[key] = float(hist["Close"].dropna().iloc[-1]) if not hist.empty else None
        except Exception:
            values[key] = None
    return values


def _current_week_start() -> str:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat()


def compute_snapshot(persist: bool = False) -> CompositeResult:
    """Fetch live values, merge with manual overrides, and score the composite.

    If persist=True, appends (or replaces, if same week) an entry to the
    history file. On Vercel serverless this only persists for the life of the
    instance unless the storage backend is swapped for Blob/DB (see README).
    """
    history = storage.load_history(INDEX_KEY)
    weeks = history.get("weeks", [])
    latest_raw = weeks[-1]["raw_values"] if weeks else BASELINE_VALUES
    manual = {**latest_raw, **history.get("manual_overrides", {})}

    live = fetch_live_values()
    stale_keys = MANUAL_KEYS | {k for k, v in live.items() if v is None}

    current_values: dict[str, float | None] = {**manual, **{k: v for k, v in live.items() if v is not None}}
    week_start = _current_week_start()

    result = compute_composite(
        components=COMPONENTS,
        current_values=current_values,
        baseline_values=BASELINE_VALUES,
        stale_keys=stale_keys,
        week_start=week_start,
    )

    if persist:
        weeks = history.setdefault("weeks", [])
        entry = {
            "week_start": week_start,
            "score": result.score,
            "level_label": result.level_label,
            "level_status": result.level_status,
            "raw_values": {k: current_values.get(k) for k in BASELINE_VALUES},
        }
        weeks = [w for w in weeks if w.get("week_start") != week_start]
        weeks.append(entry)
        history["weeks"] = sorted(weeks, key=lambda w: w["week_start"])
        storage.save_history(INDEX_KEY, history)

    return result


def get_history() -> list[dict]:
    return storage.load_history(INDEX_KEY).get("weeks", [])
