#!/usr/bin/env python
"""
scripts/elections_pipeline.py
-----------------------------
Full analytical pipeline for the Lok Sabha projection:
fetch -> calibrate -> project -> backtest -> report -> plot.

    python scripts/elections_pipeline.py              refresh only if new data
    python scripts/elections_pipeline.py --scrape     force a full refetch
    python scripts/elections_pipeline.py --no-fetch   work from cached CSVs
    python scripts/elections_pipeline.py --optimize   also run the grid search

For routine data refreshes use scripts/update_elections.py instead — this one
is for working on the model. It needs matplotlib, which is listed in
requirements-pipeline.txt rather than in the deployed runtime requirements.

Steps
    1. update the dataset            (data_updater.update_data)
    2. refit the calibration         (calibration.calibrate)
    3. build daily projections       (daily_predictor.run_daily_predictions)
    4. backtest against 2019/2024    (backtest_engine.run_full_backtest)
    5. Monte Carlo the latest day    (seat_predictive_model)
    6. write summary CSV + chart PNG
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib  # noqa: E402
import pandas as pd  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402 - must follow the backend selection

from app.elections.engine.backtest_engine import run_full_backtest  # noqa: E402
from app.elections.engine.calibration import calibrate  # noqa: E402
from app.elections.engine.daily_predictor import run_daily_predictions  # noqa: E402
from app.elections.engine.data_updater import update_data  # noqa: E402
from app.elections.engine.events import EVENTS  # noqa: E402
from app.elections.engine.paths import DATA_DIR  # noqa: E402
from app.elections.engine.seat_predictive_model import LokSabhaSeatPredictor  # noqa: E402
from app.elections.engine.trend_analytics import summarize  # noqa: E402


def run_pipeline(output_dir=DATA_DIR, baseline_year=2024, fetch=True, force_scrape=False, optimize=False):
    os.makedirs(output_dir, exist_ok=True)
    master_csv = os.path.join(output_dir, "cvoter_daily_trackers.csv")

    print("=" * 68)
    print("  CVoter daily survey -> Lok Sabha seat projection pipeline")
    print("=" * 68)

    # -- 1. data ---------------------------------------------------------
    if fetch:
        print("\n[1/6] Updating dataset from cvoterindia.com...")
        result = update_data(data_dir=output_dir, force=force_scrape, rebuild_derived=False)
        print(f"      {result['status']}: {result['reason']}")
        if result["status"] == "failed" and not os.path.exists(master_csv):
            print("      No cached data to fall back on. Aborting.")
            return
    else:
        print("\n[1/6] Skipping fetch, using cached data.")

    if not os.path.exists(master_csv):
        print(f"ERROR: {master_csv} not found. Run without --no-fetch first.")
        return

    df = pd.read_csv(master_csv)
    print(f"      {len(df)} daily rows x {len(df.columns) - 1} labelled metrics "
          f"({df['date'].min()} -> {df['date'].max()})")

    # -- 2. calibration --------------------------------------------------
    print("\n[2/6] Fitting the sentiment -> vote share -> seats mapping...")
    calibration = calibrate(df=df, data_dir=output_dir, baseline_year=baseline_year)
    vm = calibration["vote_share_model"]
    print(f"      vote share = {vm['intercept']:.3f} + {vm['slope']:.4f} x composite")
    print(f"      cube exponent k = {calibration['cube_exponent']:.3f} "
          f"({calibration['cube_exponent_fit']['method']})")
    for anchor in vm["anchors"]:
        print(f"      anchor {anchor['year']}: composite {anchor['composite']:+.2f} "
              f"-> actual vote {anchor['actual_nda_vote_share']}%")

    # -- 3. daily projections --------------------------------------------
    print("\n[3/6] Computing daily projections and trend analytics...")
    projections = run_daily_predictions(
        data_dir=output_dir, output_dir=output_dir, baseline_year=baseline_year, verbose=False
    )
    print(f"      {len(projections)} daily projections written")

    # -- 4. backtest ------------------------------------------------------
    print("\n[4/6] Backtesting against the 2019 and 2024 results...")
    predictor = LokSabhaSeatPredictor(baseline_year=baseline_year, data_dir=output_dir)
    backtest = run_full_backtest(predictor, df)
    for year in ("2019", "2024"):
        res = backtest.get(year)
        if res:
            print(f"      {year}: predicted {res['predicted_seats']} vs "
                  f"actual {res['actual_seats']}  (MAE {res['mae']:.1f})")
    print(f"      overall MAE: {backtest['overall_mae']:.2f} seats")

    # -- 5. latest forecast ------------------------------------------------
    print("\n[5/6] Monte Carlo on the latest survey day...")
    latest = df.iloc[-1]
    mc = predictor.run_monte_carlo_simulation(latest, n_simulations=20000, seed=42)
    point = mc["point_estimate"]
    ci = mc["confidence_intervals"]
    prob = mc["majority_probability"]
    trend = summarize(projections, value_col="NDA_proj_seats")

    print("\n" + "=" * 68)
    print(f"  LATEST FORECAST  (as of {latest['date']})")
    print("=" * 68)
    print(f"  Composite sentiment : {point['composite_sentiment']:+.2f}")
    print(f"  Vote share          : NDA {point['projected_vote_share']['NDA']}% | "
          f"INDIA {point['projected_vote_share']['INDIA']}% | "
          f"OTHERS {point['projected_vote_share']['OTHERS']}%")
    print(f"  Seats               : NDA {point['predicted_seats']['NDA']} | "
          f"INDIA {point['predicted_seats']['INDIA']} | "
          f"OTHERS {point['predicted_seats']['OTHERS']}")
    print(f"  NDA 90% interval    : {ci['NDA']['p5']} - {ci['NDA']['p95']}")
    print(f"  INDIA 90% interval  : {ci['INDIA']['p5']} - {ci['INDIA']['p95']}")
    print(f"  P(NDA majority)     : {prob['NDA']:.1%}")
    print(f"  P(INDIA majority)   : {prob['INDIA']:.1%}")
    print(f"  P(hung parliament)  : {prob['HUNG']:.1%}")
    print("-" * 68)
    print(f"  30-day trend        : {trend['trend_slope_per_day']:+.3f} seats/day "
          f"({trend['trend_direction']})")
    print(f"  7d / 30d moving avg : {trend['ma_7d']:.1f} / {trend['ma_30d']:.1f}")
    print(f"  Volatility (30d s)  : {trend['volatility']:.3f}")
    print(f"  Momentum (MA7-MA30) : {trend['momentum']:+.2f} (z {trend['momentum_z']:+.2f})")
    print("=" * 68)

    summary = pd.DataFrame([{
        "as_of_date": latest["date"],
        "baseline_election_used": baseline_year,
        "composite_sentiment": point["composite_sentiment"],
        "NDA_predicted_seats": point["predicted_seats"]["NDA"],
        "NDA_seats_90_CI": f"{ci['NDA']['p5']} - {ci['NDA']['p95']}",
        "NDA_majority_probability": f"{prob['NDA']:.1%}",
        "INDIA_predicted_seats": point["predicted_seats"]["INDIA"],
        "INDIA_seats_90_CI": f"{ci['INDIA']['p5']} - {ci['INDIA']['p95']}",
        "INDIA_majority_probability": f"{prob['INDIA']:.1%}",
        "OTHERS_predicted_seats": point["predicted_seats"]["OTHERS"],
        "hung_probability": f"{prob['HUNG']:.1%}",
        "trend_slope_per_day": trend["trend_slope_per_day"],
        "ma_7d": trend["ma_7d"],
        "ma_30d": trend["ma_30d"],
        "volatility": trend["volatility"],
        "momentum": trend["momentum"],
        "backtest_overall_mae": round(backtest["overall_mae"], 2),
    }])
    summary_path = os.path.join(output_dir, "lok_sabha_latest_forecast_summary.csv")
    summary.to_csv(summary_path, index=False)
    print(f"\nSummary written to {summary_path}")

    # -- 6. chart -----------------------------------------------------------
    print("\n[6/6] Rendering the projection chart...")
    plot_seat_projections(projections, output_dir=output_dir)

    # This step rewrites the CSVs directly rather than going through
    # update_data(rebuild_derived=True), so it has to refresh the precomputed
    # JSON the dashboard serves. Without it the site keeps answering from
    # artifacts built against the previous data.
    print("\n[+] Refreshing precomputed dashboard artifacts...")
    from app.elections.engine.precompute import precompute_all
    precompute_all(data_dir=output_dir, verbose=False)
    print("      overview, trend_analytics, events, backtest_results, insights")

    if optimize:
        print("\n[extra] Running the tracker/parameter grid search...")
        from app.elections.engine.model_optimizer import find_ideal_model
        find_ideal_model(df, output_dir=output_dir)

    print("\nPipeline complete.")


def plot_seat_projections(projections, output_dir=DATA_DIR):
    """Static PNG of the projection series with event markers."""
    df = projections.copy()
    df["date"] = pd.to_datetime(df["date"])

    fig, ax = plt.subplots(figsize=(15, 7.5), dpi=120)

    ax.plot(df["date"], df["NDA_proj_seats"], color="#FF9933", linewidth=1.3,
            alpha=0.55, label="NDA projected")
    ax.plot(df["date"], df["INDIA_proj_seats"], color="#19AAED", linewidth=1.3,
            alpha=0.55, label="INDIA projected")

    if "NDA_proj_seats_ma30" in df.columns:
        ax.plot(df["date"], df["NDA_proj_seats_ma30"], color="#B45309", linewidth=2.0,
                label="NDA 30-day moving average")
    if "INDIA_proj_seats_ma30" in df.columns:
        ax.plot(df["date"], df["INDIA_proj_seats_ma30"], color="#0369A1", linewidth=2.0,
                label="INDIA 30-day moving average")

    ax.axhline(y=272, color="red", linestyle=":", linewidth=1.4, label="Majority (272)")

    # Event markers, thinned so the static chart stays readable.
    for event in EVENTS:
        start = pd.to_datetime(event["date"])
        if start < df["date"].min() or start > df["date"].max():
            continue
        if "end_date" in event:
            ax.axvspan(start, pd.to_datetime(event["end_date"]), color="#94A3B8", alpha=0.13)
        else:
            ax.axvline(start, color="#94A3B8", linestyle="--", linewidth=0.7, alpha=0.5)

    ax.set_title(
        "Lok Sabha seat projection from CVoter daily option-level survey trackers",
        fontsize=14, fontweight="bold", pad=12,
    )
    ax.set_xlabel("Date")
    ax.set_ylabel("Projected seats (of 543)")
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend(loc="upper left", frameon=True, fontsize=9)
    fig.tight_layout()

    chart_path = os.path.join(output_dir, "lok_sabha_seat_projection_timeline.png")
    fig.savefig(chart_path)
    plt.close(fig)
    print(f"      chart saved to {chart_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the full projection pipeline.")
    parser.add_argument("--scrape", action="store_true", help="force a full refetch")
    parser.add_argument("--no-fetch", action="store_true", help="use cached CSVs only")
    parser.add_argument("--optimize", action="store_true", help="also run the grid search")
    parser.add_argument("--baseline-year", type=int, default=2024)
    parser.add_argument("--output-dir", default=DATA_DIR)
    args = parser.parse_args()

    run_pipeline(
        output_dir=args.output_dir,
        baseline_year=args.baseline_year,
        fetch=not args.no_fetch,
        force_scrape=args.scrape,
        optimize=args.optimize,
    )
