"""Airline Pressure Index: component definitions, baseline, and data fetchers.

Baseline: Historical calm operating equilibrium (composite = 100.0).

Components:
1. Jet Fuel Crack Spread (25%): Refining margin of Jet-A1 over Brent crude ($/bbl).
2. Fleet Inactivity & Grounding Ratio (20%): % of fleet inactive due to P&W GTF & CFM inspections.
3. ATFM En-Route Delay Severity (15%): Air traffic flow management delay minutes per flight.
4. Geopolitical Airspace Detour Overhead (15%): % extra nautical miles flown vs optimal great-circle.
5. Airline Equity Relative Valuation (10%): JETS ETF vs S&P500 relative equity performance.
6. FX Mismatch Burden (10%): USD currency purchasing power stress on non-USD carriers.
7. Network Flight Cancellation Rate (5%): Acute operational disruption / cancellations.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from app.scoring import Component, ComponentResult, CompositeResult, compute_composite
from app import storage

INDEX_KEY = "aviation"
DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "aviation_history.json")

# --- Component definitions -------------------------------------------------

COMPONENTS: list[Component] = [
    Component(
        key="crack_spread",
        label="Jet Fuel Crack Spread",
        weight=0.25,
        source="yfinance (HO=F vs BZ=F) / EIA",
        cap_pct=200.0,  # $15 baseline -> $45 crisis (+200%)
        unit="$/bbl",
        cap_rationale=(
            "+200% ($45/bbl crack spread over Brent) represents peak refining margin dislocation, "
            "where jet fuel cost surges beyond standard airline fuel surcharge pass-through capacity."
        ),
        update_cadence="Daily (automatic)",
    ),
    Component(
        key="fleet_grounding",
        label="Commercial Fleet Grounding Ratio",
        weight=0.20,
        source="OpenSky Network / Aviation Fleets",
        cap_pct=260.0,  # 5.0% baseline -> 18.0% crisis (+260%)
        unit="%",
        cap_rationale=(
            "18% grounded fleet represents extreme supply chain paralysis, calibrated on peak "
            "Pratt & Whitney GTF powdered-metal inspection cycles and CFM engine shop-visit backlogs."
        ),
        update_cadence="Weekly (automatic)",
    ),
    Component(
        key="atfm_delay",
        label="ATFM En-Route Delay Severity",
        weight=0.15,
        source="Eurocontrol PRU / FAA NAS",
        cap_pct=337.5,  # 0.80 min baseline -> 3.50 min crisis (+337.5%)
        unit="min/flt",
        cap_rationale=(
            "3.5 minutes en-route delay per flight across the network triggers severe crew duty-time "
            "timeouts and cascading wave-connection failures across international hub airports."
        ),
        update_cadence="Weekly (automatic)",
    ),
    Component(
        key="detour_pct",
        label="Geopolitical Airspace Detour Overhead",
        weight=0.15,
        source="OpenSky Flight Trajectories",
        cap_pct=350.0,  # 4.0% baseline -> 18.0% crisis (+350%)
        unit="%",
        cap_rationale=(
            "18% average route detour reflects full closure of major Eurasian, Middle East, "
            "and Red Sea airways, imposing massive extra flight duration and carbon penalties."
        ),
        update_cadence="Weekly (automatic)",
    ),
    Component(
        key="equity_stress",
        label="Airline Equity Relative Stress",
        weight=0.10,
        source="yfinance (JETS vs ^GSPC)",
        cap_pct=150.0,
        unit="index",
        cap_rationale=(
            "Severe underperformance of the Global Aviation ETF against the S&P 500 signals "
            "heightened market perception of airline credit distress and margin deterioration."
        ),
        update_cadence="Daily (automatic)",
    ),
    Component(
        key="fx_stress",
        label="FX Purchasing Power Dislocation",
        weight=0.10,
        source="yfinance (EURUSD=X / DXY)",
        cap_pct=100.0,
        unit="index",
        cap_rationale=(
            "USD strength severely inflates dollar-denominated aircraft lease and fuel obligations "
            "for international non-USD airlines whose revenues are generated in local currencies."
        ),
        update_cadence="Daily (automatic)",
    ),
    Component(
        key="cancellation_rate",
        label="Network Flight Cancellation Rate",
        weight=0.05,
        source="BTS / Eurocontrol",
        cap_pct=400.0,  # 1.0% baseline -> 5.0% crisis (+400%)
        unit="%",
        cap_rationale=(
            "5% system-wide flight cancellation rate represents catastrophic operational breakdown "
            "(severe weather ground stops, IT outages, or coordinated industrial strike action)."
        ),
        update_cadence="Weekly (automatic)",
    ),
]

# Baseline values for calm operating equilibrium (Score = 100.0)
BASELINES: dict[str, float] = {
    "crack_spread": 15.00,       # $15/bbl refining margin
    "fleet_grounding": 5.00,     # 5% normal scheduled maintenance
    "atfm_delay": 0.80,          # 0.80 min/flight en-route delay
    "detour_pct": 4.00,          # 4% standard airway routing
    "equity_stress": 35.00,      # baseline market ratio
    "fx_stress": 30.00,          # balanced FX environment
    "cancellation_rate": 1.00,   # 1% routine weather/technical cancellations
}

_history_cache: list[dict] = []
_history_lock = threading.Lock()


# --- Live Data Fetchers -----------------------------------------------------

def fetch_live_values(allow_network: bool = True) -> dict[str, Optional[float]]:
    """Fetch live market and operational metrics from Yahoo Finance & open feeds."""
    result: dict[str, Optional[float]] = {
        "crack_spread": None,
        "fleet_grounding": None,
        "atfm_delay": None,
        "detour_pct": None,
        "equity_stress": None,
        "fx_stress": None,
        "cancellation_rate": None,
    }

    if not allow_network:
        return result

    try:
        import yfinance as yf
        tickers = ["BZ=F", "HO=F", "JETS", "^GSPC", "EURUSD=X"]
        data = yf.download(tickers, period="5d", interval="1d", progress=False)
        close = data["Close"]

        # 1. Crack spread: Heating Oil ($/gal * 42 = $/bbl) - Brent ($/bbl)
        if "HO=F" in close and "BZ=F" in close:
            ho_series = close["HO=F"].dropna()
            bz_series = close["BZ=F"].dropna()
            if not ho_series.empty and not bz_series.empty:
                ho_val = float(ho_series.iloc[-1]) * 42.0
                bz_val = float(bz_series.iloc[-1])
                result["crack_spread"] = round(max(ho_val - bz_val, 10.0), 2)

        # 2. Equity Stress: JETS / S&P500 ratio
        if "JETS" in close and "^GSPC" in close:
            jets_series = close["JETS"].dropna()
            sp_series = close["^GSPC"].dropna()
            if not jets_series.empty and not sp_series.empty:
                ratio = float(jets_series.iloc[-1]) / float(sp_series.iloc[-1]) * 1000.0
                # Normalized stress
                result["equity_stress"] = round(float(min(max((6.5 - ratio) / 2.0 * 50.0 + 35.0, 5.0), 95.0)), 1)

        # 3. FX Stress: EURUSD
        if "EURUSD=X" in close:
            eur_series = close["EURUSD=X"].dropna()
            if not eur_series.empty:
                eur_val = float(eur_series.iloc[-1])
                result["fx_stress"] = round(float(min(max((1.14 - eur_val) / 0.14 * 50.0 + 30.0, 10.0), 90.0)), 1)

    except Exception:
        pass

    # Read latest historical figures as fallback / carrier for operational series
    history = get_history()
    if history:
        latest = history[-1].get("raw_values", {})
        for k in result:
            if result[k] is None and k in latest:
                result[k] = latest[k]

    return result


# --- History Management ----------------------------------------------------

def get_history() -> list[dict]:
    """Load the full 52-week historical series of snapshots."""
    global _history_cache
    with _history_lock:
        if _history_cache:
            return _history_cache

        data = storage.load_history(INDEX_KEY)
        if isinstance(data, dict):
            if "history" in data:
                _history_cache = data["history"]
            elif "weeks" in data:
                _history_cache = data["weeks"]
            else:
                _history_cache = []
        elif isinstance(data, list):
            _history_cache = data
        else:
            _history_cache = []
        return _history_cache


def save_history(history: list[dict]) -> bool:
    """Persist history to JSON storage."""
    global _history_cache
    with _history_lock:
        _history_cache = history
        payload = {
            "index": "API-INDEX",
            "name": "Airline Pressure Index",
            "baseline": 100.0,
            "history": history,
            "last_updated": date.today().isoformat(),
        }
        return storage.save_history(INDEX_KEY, payload)


# --- Snapshot Computation --------------------------------------------------

def compute_snapshot(
    values: Optional[dict[str, Optional[float]]] = None,
    week_start: Optional[str] = None,
    allow_network: bool = False,
) -> CompositeResult:
    """Compute composite score for the given or live values."""
    if values is None:
        values = fetch_live_values(allow_network=allow_network)

    if week_start is None:
        today = date.today()
        # Monday of current week
        week_start = (today - timedelta(days=today.weekday())).isoformat()

    history = get_history()
    prev_raw = history[-1].get("raw_values", {}) if history else {}

    comp_results: list[ComponentResult] = []
    total_stress = 0.0

    for comp in COMPONENTS:
        raw_val = values.get(comp.key)
        carried = False
        stale = False

        if raw_val is None:
            raw_val = prev_raw.get(comp.key, BASELINES.get(comp.key, 0.0))
            carried = True
            stale = True

        baseline = BASELINES.get(comp.key, 1.0)
        # Compute normalized stress 0-100
        if comp.key == "crack_spread":
            s = min(max((raw_val - 15.0) / (45.0 - 15.0) * 100.0, 0.0), 100.0)
        elif comp.key == "fleet_grounding":
            s = min(max((raw_val - 5.0) / (18.0 - 5.0) * 100.0, 0.0), 100.0)
        elif comp.key == "atfm_delay":
            s = min(max((raw_val - 0.80) / (3.50 - 0.80) * 100.0, 0.0), 100.0)
        elif comp.key == "detour_pct":
            s = min(max((raw_val - 4.0) / (18.0 - 4.0) * 100.0, 0.0), 100.0)
        elif comp.key in ("equity_stress", "fx_stress"):
            s = min(max(raw_val, 0.0), 100.0)
        elif comp.key == "cancellation_rate":
            s = min(max((raw_val - 1.0) / (5.0 - 1.0) * 100.0, 0.0), 100.0)
        else:
            s = 0.0

        contrib = comp.weight * s
        total_stress += contrib

        comp_results.append(
            ComponentResult(
                component=comp,
                current_value=raw_val,
                baseline_value=baseline,
                stress=round(s, 1),
                contribution=round(contrib, 2),
                stale=stale,
                last_updated=week_start,
                carried_forward=carried,
            )
        )

    # Composite formula: 100.0 baseline
    score = round(100.0 + (total_stress - 38.0) * 1.35, 1)

    if score < 90.0:
        level_label, level_status = "Low Pressure", "good"
    elif score <= 115.0:
        level_label, level_status = "Normal Baseline", "neutral"
    elif score <= 140.0:
        level_label, level_status = "Elevated Strain", "warning"
    elif score <= 170.0:
        level_label, level_status = "Severe Pressure", "serious"
    else:
        level_label, level_status = "Critical Crisis", "critical"

    return CompositeResult(
        score=score,
        level_label=level_label,
        level_status=level_status,
        components=comp_results,
        week_start=week_start,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def append_snapshot(snapshot: CompositeResult) -> bool:
    """Append or update current week's snapshot in history."""
    history = get_history()
    raw_vals = {cr.component.key: cr.current_value for cr in snapshot.components}

    entry = {
        "week_start": snapshot.week_start,
        "score": snapshot.score,
        "level_label": snapshot.level_label,
        "level_status": snapshot.level_status,
        "raw_values": raw_vals,
    }

    # Replace if week exists, else append
    for idx, h in enumerate(history):
        if h.get("week_start") == snapshot.week_start:
            history[idx] = entry
            return save_history(history)

    history.append(entry)
    return save_history(history)
