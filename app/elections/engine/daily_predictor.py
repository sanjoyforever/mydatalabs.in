"""
daily_predictor.py
------------------
Pre-computes the daily seat projection series plus its trend analytics.

Output (data/ideal_model_daily_projections.csv) carries, per day:
    composite sentiment, alliance vote shares, alliance seats,
    election-period flags, and for NDA and INDIA seats the 7/30-day moving
    averages, 30-day regression slope, rolling volatility and momentum.

Computing the rolling statistics here rather than in the browser keeps the
chart and the API reading identical numbers, and keeps the front end simple.
"""

import os

import pandas as pd

from app.elections.engine.paths import DATA_DIR

from app.elections.engine.election_data import HISTORICAL_ELECTION_RESULTS, add_election_flags
from app.elections.engine.seat_predictive_model import predict_series
from app.elections.engine.trend_analytics import add_rolling_columns


def run_daily_predictions(data_dir=DATA_DIR, output_dir=DATA_DIR, baseline_year=2024, verbose=True):
    """
    Builds the full daily projection table and writes it to CSV.

    Returns the DataFrame.
    """
    csv_path = os.path.join(data_dir, "cvoter_daily_trackers.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Master CSV not found at {csv_path}. Run data_updater first.")

    df = pd.read_csv(csv_path)
    projections = predict_series(df, baseline_year=baseline_year, data_dir=data_dir)

    # Election-period flags, joined on date.
    flags = add_election_flags(df[["date"]].copy(), date_column="date")
    keep = ["date", "is_election_period", "is_mcc_active", "election_phase_tag",
            "days_to_nearest_election"]
    projections = projections.merge(flags[keep], on="date", how="left")

    baseline = HISTORICAL_ELECTION_RESULTS[baseline_year]["national_summary"]
    opp_key = "INDIA" if "INDIA" in baseline else "UPA"
    projections["NDA_actual_baseline_2024"] = baseline["NDA"]["seats"]
    projections["INDIA_actual_baseline_2024"] = baseline[opp_key]["seats"]
    projections["OTHERS_actual_baseline_2024"] = baseline["OTHERS"]["seats"]
    projections["NDA_majority"] = projections["NDA_proj_seats"] >= 272

    # Rolling analytics for the two headline series and the sentiment index.
    for col in ("NDA_proj_seats", "INDIA_proj_seats", "composite_sentiment"):
        projections = add_rolling_columns(projections, value_col=col)

    out_path = os.path.join(output_dir, "ideal_model_daily_projections.csv")
    os.makedirs(output_dir, exist_ok=True)
    projections.to_csv(out_path, index=False)

    if verbose:
        latest = projections.iloc[-1]
        print(f"Wrote {len(projections)} daily projections to {out_path}")
        print(
            f"  latest {latest['date']}: NDA {int(latest['NDA_proj_seats'])} | "
            f"INDIA {int(latest['INDIA_proj_seats'])} | "
            f"composite {latest['composite_sentiment']:+.2f}"
        )

    return projections


if __name__ == "__main__":
    run_daily_predictions()
