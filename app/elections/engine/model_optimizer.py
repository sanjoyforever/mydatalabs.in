"""
model_optimizer.py
------------------
Grid search over tracker selection and seat-conversion parameters.

Searches for the configuration with the lowest backtest error against the two
observed elections (2019 and 2024), over:

    * which trackers enter the composite index (all subsets of size >= 2)
    * the relative weight given to the Self/Nation tracker, which carries the
      distress option the whole index is most sensitive to
    * the cube-law exponent

Because there are only two elections to score against, this is a small-sample
search and will happily overfit if you let it. The report therefore prints the
per-election errors alongside the aggregate, and flags any configuration whose
two elections disagree sharply -- a low mean with a wide spread is worse than a
slightly higher mean with consistent performance.

The previous version of this file searched over column names that existed in no
version of the dataset and called a method that did not exist, so it could never
have run.
"""

import itertools
import json
import os

import numpy as np
import pandas as pd

from app.elections.engine.paths import DATA_DIR
from app.elections.engine.backtest_engine import ACTUAL_SEAT_OUTCOMES, run_full_backtest
from app.elections.engine.calibration import calibrate
from app.elections.engine.seat_predictive_model import LokSabhaSeatPredictor
from app.elections.engine.sentiment_index import compute_composite
from app.elections.engine.tracker_schema import TRACKER_SCHEMA, TRACKER_WEIGHTS

# Trackers eligible for the composite (Media Usage has no political polarity).
CANDIDATE_TRACKERS = [t for t in sorted(TRACKER_SCHEMA) if TRACKER_WEIGHTS.get(t, 0) > 0]

SELF_NATION_WEIGHTS = [1.0, 1.5, 2.0, 2.5]
CUBE_EXPONENTS = [2.2, 2.4, 2.65, 2.9, 3.2]


def _weights_for(subset, self_nation_weight):
    """Tracker weight map restricted to `subset`, with tracker 6 rescaled."""
    weights = {}
    for tracker_id in subset:
        base = TRACKER_WEIGHTS[tracker_id]
        weights[tracker_id] = self_nation_weight if tracker_id == 6 else base
    return weights


def _calibration_for(df, weights, cube_exponent):
    """
    Refits the vote-share model for a given weighting, then pins the exponent.

    The composite index changes whenever the weights change, so the
    sentiment-to-vote-share fit has to be redone for each candidate, otherwise
    the search would be comparing indices against a fixed, wrong scale.
    """
    scoped = df.copy()
    scoped["composite_sentiment"] = compute_composite(scoped, tracker_weights=weights)
    calibration = calibrate(df=scoped, data_dir=DATA_DIR, write=False)
    calibration["cube_exponent"] = float(cube_exponent)
    return calibration, scoped


def find_ideal_model(tracker_df, output_dir=DATA_DIR, verbose=True):
    """
    Runs the search and writes the winning configuration to JSON.

    Returns (best_config, all_results).
    """
    os.makedirs(output_dir, exist_ok=True)

    subsets = []
    for size in range(2, len(CANDIDATE_TRACKERS) + 1):
        subsets.extend(itertools.combinations(CANDIDATE_TRACKERS, size))

    total = len(subsets) * len(SELF_NATION_WEIGHTS) * len(CUBE_EXPONENTS)
    if verbose:
        print("=" * 65)
        print("  Tracker selection & seat-conversion grid search")
        print("=" * 65)
        print(f"Evaluating {total} configurations against 2019 and 2024 outcomes...")

    results = []
    best = None

    for subset in subsets:
        for sn_weight in SELF_NATION_WEIGHTS:
            # Rescaling tracker 6 only matters when tracker 6 is in the subset.
            if 6 not in subset and sn_weight != SELF_NATION_WEIGHTS[0]:
                continue

            weights = _weights_for(subset, sn_weight)

            for k in CUBE_EXPONENTS:
                try:
                    calibration, scoped = _calibration_for(tracker_df, weights, k)
                except Exception:  # noqa: BLE001 - a degenerate subset is just skipped
                    continue

                predictor = LokSabhaSeatPredictor(
                    baseline_year=2024,
                    cube_exponent=k,
                    calibration=calibration,
                    tracker_weights=weights,
                )

                backtest = run_full_backtest(predictor, scoped)
                errors = [
                    backtest[str(year)]["mae"]
                    for year in ACTUAL_SEAT_OUTCOMES
                    if backtest.get(str(year))
                ]
                if not errors:
                    continue

                entry = {
                    "trackers": [int(t) for t in subset],
                    "tracker_names": [TRACKER_SCHEMA[t]["name"] for t in subset],
                    "self_nation_weight": sn_weight,
                    "cube_exponent": k,
                    "mean_mae": round(float(np.mean(errors)), 2),
                    "worst_mae": round(float(np.max(errors)), 2),
                    "mae_spread": round(float(np.max(errors) - np.min(errors)), 2),
                    "mae_2019": round(backtest["2019"]["mae"], 2) if backtest.get("2019") else None,
                    "mae_2024": round(backtest["2024"]["mae"], 2) if backtest.get("2024") else None,
                    "pred_2019": backtest["2019"]["predicted_seats"] if backtest.get("2019") else None,
                    "pred_2024": backtest["2024"]["predicted_seats"] if backtest.get("2024") else None,
                    "slope": calibration["vote_share_model"]["slope"],
                    "intercept": calibration["vote_share_model"]["intercept"],
                }
                results.append(entry)

                # Rank on worst-case error rather than the mean, so a config
                # that nails one election and misses the other badly cannot win.
                if best is None or entry["worst_mae"] < best["worst_mae"]:
                    best = entry

    if best is None:
        raise RuntimeError("Grid search produced no valid configurations.")

    if verbose:
        print("\n" + "=" * 65)
        print("  BEST CONFIGURATION (ranked on worst-case election error)")
        print("=" * 65)
        print(f"  Trackers            : {best['tracker_names']}")
        print(f"  Self/Nation weight  : {best['self_nation_weight']}")
        print(f"  Cube exponent       : {best['cube_exponent']}")
        print(f"  Mean MAE            : {best['mean_mae']} seats")
        print(f"  Worst-case MAE      : {best['worst_mae']} seats (spread {best['mae_spread']})")
        print(f"  2019                : pred {best['pred_2019']} (MAE {best['mae_2019']})")
        print(f"  2024                : pred {best['pred_2024']} (MAE {best['mae_2024']})")
        print("=" * 65)
        print("  Note: only two elections are available to score against.")
        print("  Treat this as a sanity check on the hand-set weights, not proof.")
        print("=" * 65)

        ranked = sorted(results, key=lambda r: r["worst_mae"])[:5]
        print("\nTop 5 by worst-case error:")
        for entry in ranked:
            print(f"  worst {entry['worst_mae']:>6} | mean {entry['mean_mae']:>6} | "
                  f"k={entry['cube_exponent']} | sn_w={entry['self_nation_weight']} | "
                  f"{entry['tracker_names']}")

    config_path = os.path.join(output_dir, "ideal_model_config.json")
    with open(config_path, "w", encoding="utf-8") as fh:
        json.dump({"best": best, "evaluated": len(results)}, fh, indent=2)
    if verbose:
        print(f"\nSaved to {config_path}")

    return best, results


if __name__ == "__main__":
    csv_path = os.path.join(DATA_DIR, "cvoter_daily_trackers.csv")
    if not os.path.exists(csv_path):
        raise SystemExit(f"{csv_path} not found. Run data_updater.py first.")
    find_ideal_model(pd.read_csv(csv_path))
