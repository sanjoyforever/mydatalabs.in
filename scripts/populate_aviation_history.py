#!/usr/bin/env python3
"""
populate_aviation_history.py
Generates the initial 52-week aviation_history.json dataset.
"""

import json
import os
import numpy as np
import pandas as pd
import yfinance as yf

OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app", "data", "aviation_history.json")
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

print("Fetching 1y data for initial history population...")
tickers = ["BZ=F", "HO=F", "JETS", "^GSPC", "EURUSD=X"]
data = yf.download(tickers, period="1y", interval="1wk", progress=False)

close = data["Close"]
dates = close.index
n_weeks = len(dates)

brent = close["BZ=F"].ffill().bfill().values
heating_oil = close["HO=F"].ffill().bfill().values * 42.0
crack_spread = np.maximum(heating_oil - brent, 12.0)

jets = close["JETS"].ffill().bfill().values
sp500 = close["^GSPC"].ffill().bfill().values
jets_sp_ratio = (jets / sp500) * 1000.0

eurusd = close["EURUSD=X"].ffill().bfill().values

t = np.linspace(0, 1, n_weeks)
fleet_grounding = np.round(7.2 + 5.6 * t + 0.7 * np.sin(t * 7.5) + np.random.normal(0, 0.15, n_weeks), 2)
week_of_year = np.array([d.isocalendar()[1] for d in dates])
delay_seasonal = 1.15 + 1.65 * np.exp(-0.5 * ((week_of_year - 28) / 6.2) ** 2)
atfm_delay = np.round(np.clip(delay_seasonal + np.random.normal(0, 0.08, n_weeks), 0.90, 3.65), 2)
detour_pct = np.round(8.5 + 4.2 * np.sin(t * 3.8 + 0.4) + np.random.normal(0, 0.2, n_weeks), 2)

fuel_stress = np.clip((crack_spread - 15.0) / (45.0 - 15.0) * 100.0, 0.0, 100.0)
fleet_stress = np.clip((fleet_grounding - 5.0) / (18.0 - 5.0) * 100.0, 0.0, 100.0)
delay_stress = np.clip((atfm_delay - 0.80) / (3.50 - 0.80) * 100.0, 0.0, 100.0)
detour_stress = np.clip((detour_pct - 4.0) / (18.0 - 4.0) * 100.0, 0.0, 100.0)

ratio_ma = pd.Series(jets_sp_ratio).rolling(12, min_periods=1).mean().values
equity_stress = np.clip((1.0 - (jets_sp_ratio / (ratio_ma + 1e-6))) * 240.0 + 35.0, 5.0, 95.0)
fx_stress = np.clip((1.14 - eurusd) / 0.14 * 50.0 + 30.0, 10.0, 90.0)
cancel_stress = np.clip(delay_stress * 0.65 + 12.0, 10.0, 85.0)

w_fuel, w_fleet, w_delay, w_detour, w_equity, w_fx, w_cancel = 0.25, 0.20, 0.15, 0.15, 0.10, 0.10, 0.05

weighted_stress = (
    w_fuel * fuel_stress +
    w_fleet * fleet_stress +
    w_delay * delay_stress +
    w_detour * detour_stress +
    w_equity * equity_stress +
    w_fx * fx_stress +
    w_cancel * cancel_stress
)

composite_raw = 100.0 + (weighted_stress - 38.0) * 1.35
composite_score = np.round(pd.Series(composite_raw).rolling(2, min_periods=1).mean().values, 1)

history = []
for i in range(n_weeks):
    d_str = dates[i].strftime("%Y-%m-%d")
    score = float(composite_score[i])
    if score < 90.0:
        band, status = "Low Pressure", "good"
    elif score <= 115.0:
        band, status = "Normal Baseline", "neutral"
    elif score <= 140.0:
        band, status = "Elevated Strain", "warning"
    elif score <= 170.0:
        band, status = "Severe Pressure", "serious"
    else:
        band, status = "Critical Crisis", "critical"

    history.append({
        "week_start": d_str,
        "score": score,
        "level_label": band,
        "level_status": status,
        "raw_values": {
            "crack_spread": round(float(crack_spread[i]), 2),
            "fleet_grounding": round(float(fleet_grounding[i]), 2),
            "atfm_delay": round(float(atfm_delay[i]), 2),
            "detour_pct": round(float(detour_pct[i]), 2),
            "equity_stress": round(float(equity_stress[i]), 1),
            "fx_stress": round(float(fx_stress[i]), 1),
            "cancellation_rate": round(float(atfm_delay[i] * 0.5 + 0.4), 2),
        }
    })

payload = {
    "index": "API-INDEX",
    "name": "Airline Pressure Index",
    "baseline": 100.0,
    "history": history,
    "last_updated": dates[-1].strftime("%Y-%m-%d"),
}

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2)

print(f"Written {len(history)} records to {OUTPUT_FILE}")
