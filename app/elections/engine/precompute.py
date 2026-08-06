"""
precompute.py
-------------
Precomputes the derived election dataset JSON files (overview, trend_analytics,
events, backtest_results, insights) into app/data/elections/.

NOTE: no route reads these files any more. The site serves
app/data/precomputed/lok-sabha-index.json, built by `_build_lok_sabha_index` in
app/precomputed.py, which is a superset of what this writes and is the only
artifact shipped to the deployment. This module remains as the engine's own
intermediate output — the CVoter updater calls it, and the files are useful when
inspecting the dataset by hand — but editing it will not change what the site
serves. Change app/precomputed.py for that.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import pandas as pd

from app.elections.engine.backtest_engine import run_full_backtest
from app.elections.engine.election_data import HISTORICAL_ELECTION_RESULTS
from app.elections.engine.events import categories as event_categories
from app.elections.engine.events import get_events
from app.elections.engine.insights import executive_summary, top_impacts
from app.elections.engine.paths import DATA_DIR
from app.elections.engine.seat_predictive_model import LokSabhaSeatPredictor
from app.elections.engine.sentiment_index import option_contributions
from app.elections.engine.trend_analytics import summarize

MAJORITY = 272
MONTE_CARLO_RUNS = 20000
MONTE_CARLO_SEED = 42

OVERVIEW_JSON = "overview.json"
TREND_ANALYTICS_JSON = "trend_analytics.json"
EVENTS_JSON = "events.json"
BACKTEST_JSON = "backtest_results.json"
INSIGHTS_JSON = "insights.json"


def precompute_all(data_dir=DATA_DIR, verbose=True):
    """
    Pre-calculates all derived JSON files and writes them to data_dir.
    """
    started = time.time()
    master_path = os.path.join(data_dir, "cvoter_daily_trackers.csv")
    proj_path = os.path.join(data_dir, "ideal_model_daily_projections.csv")

    if not os.path.exists(master_path) or not os.path.exists(proj_path):
        if verbose:
            print("Precompute skipped: master or projections CSV missing.")
        return {}

    df_master = pd.read_csv(master_path)
    df_proj = pd.read_csv(proj_path)
    latest = df_master.iloc[-1]

    # 1. Overview
    predictor = LokSabhaSeatPredictor(baseline_year=2024, data_dir=data_dir)
    mc = predictor.run_monte_carlo_simulation(
        latest, n_simulations=MONTE_CARLO_RUNS, seed=MONTE_CARLO_SEED
    )
    summary_2024 = HISTORICAL_ELECTION_RESULTS[2024]["national_summary"]
    overview = {
        "as_of_date": str(latest["date"]),
        "total_days_analyzed": int(len(df_master)),
        "metrics_tracked": int(len(df_master.columns) - 1),
        "actual_2024_nda": summary_2024["NDA"]["seats"],
        "actual_2024_india": summary_2024["INDIA"]["seats"],
        "actual_2024_others": summary_2024["OTHERS"]["seats"],
        "majority_threshold": MAJORITY,
        "latest_forecast": mc,
    }

    # 2. Trend Analytics
    series_cols = ["NDA_proj_seats", "INDIA_proj_seats", "composite_sentiment"]
    trend_analytics = {
        "as_of_date": str(df_proj["date"].iloc[-1]),
        "majority_threshold": MAJORITY,
        "series": {col: summarize(df_proj, value_col=col) for col in series_cols if col in df_proj.columns},
    }

    # 3. Events
    events = {
        "events": get_events(),
        "categories": event_categories(),
    }

    # 4. Backtest Results
    backtest = run_full_backtest(predictor, df_master)

    # 5. Insights
    insights = {
        "summary": executive_summary(
            df_proj,
            overview,
            contributions=option_contributions(latest),
            backtest=backtest,
        ),
        "impacts": top_impacts(df_proj, n=5),
    }

    files = {
        OVERVIEW_JSON: overview,
        TREND_ANALYTICS_JSON: trend_analytics,
        EVENTS_JSON: events,
        BACKTEST_JSON: backtest,
        INSIGHTS_JSON: insights,
    }

    for name, data in files.items():
        out_path = os.path.join(data_dir, name)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)

    duration = round(time.time() - started, 2)
    if verbose:
        print(f"Precomputed all derived election JSON files in {duration}s")

    return files


if __name__ == "__main__":
    precompute_all()
