"""
backtest_engine.py
------------------
Backtesting engine that evaluates Lok Sabha seat prediction model performance 
on past General Elections (2019 and 2024) using pre-election CVoter survey tracker data.
"""

import numpy as np
import pandas as pd
from app.elections.engine.election_data import HISTORICAL_ELECTION_RESULTS


# Actual Election Seat Outcomes & Coalition Mappings
ACTUAL_SEAT_OUTCOMES = {
    2019: {
        "polled_seats": 542,
        "NDA": 353,
        "INDIA": 91, # UPA alliance in 2019 (INC, DMK, NCP, JKNC, IUML, JMM)
        "OTHERS": 98, # Non-aligned regional (AITC, YSRCP, BJD, BSP, TRS, SP)
        "result_date": "2019-05-23"
    },
    2024: {
        "polled_seats": 543,
        "NDA": 293,
        "INDIA": 234, # INDIA alliance in 2024 (INC, SP, AITC, DMK, SS-UBT, etc.)
        "OTHERS": 16, # Regional / Non-aligned
        "result_date": "2024-06-04"
    }
}


def evaluate_seat_prediction_error(predicted_seats, actual_seats):
    """
    Computes absolute errors and Mean Absolute Error (MAE) between predicted 
    and actual Lok Sabha seat counts.
    """
    errors = {}
    total_abs_error = 0
    
    for alliance in ["NDA", "INDIA", "OTHERS"]:
        pred = predicted_seats.get(alliance, 0)
        act = actual_seats.get(alliance, 0)
        err = abs(pred - act)
        errors[f"{alliance}_error"] = err
        errors[f"{alliance}_pred"] = pred
        errors[f"{alliance}_actual"] = act
        total_abs_error += err
        
    errors["mae"] = total_abs_error / 3.0
    errors["total_abs_error"] = total_abs_error
    return errors


def run_backtest_for_year(predictor_instance, tracker_df, election_year):
    """
    Runs backtest for a target election year using pre-election survey tracker data.
    """
    if election_year not in ACTUAL_SEAT_OUTCOMES:
        raise ValueError(f"No actual election results recorded for year {election_year}")
        
    actual = ACTUAL_SEAT_OUTCOMES[election_year]
    result_date = pd.to_datetime(actual["result_date"])
    
    df = tracker_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    
    # Filter survey data in the 60-day window leading up to election result date
    start_window = result_date - pd.Timedelta(days=60)
    pre_election_df = df[(df["date"] >= start_window) & (df["date"] <= result_date)]
    
    if pre_election_df.empty:
        pre_election_df = df[df["date"] <= result_date].tail(10)
        
    if pre_election_df.empty:
        return None
        
    avg_survey = pre_election_df.mean(numeric_only=True).to_dict()

    # Rebuild the predictor against the target election's own baseline rather
    # than mutating the caller's instance in place. The vote-share fit is
    # global, but the baseline alliance split and polled-seat count are not.
    predictor = _rebase(predictor_instance, election_year)

    pred_res = predictor.predict_seats_for_survey_point(avg_survey)
    predicted_seats = pred_res["predicted_seats"]

    eval_metrics = evaluate_seat_prediction_error(predicted_seats, actual)
    eval_metrics["election_year"] = election_year
    eval_metrics["survey_sample_count"] = len(pre_election_df)
    eval_metrics["predicted_seats"] = predicted_seats
    eval_metrics["actual_seats"] = {k: actual[k] for k in ["NDA", "INDIA", "OTHERS"]}
    eval_metrics["composite_sentiment"] = pred_res.get("composite_sentiment")
    eval_metrics["projected_vote_share"] = pred_res.get("projected_vote_share")
    eval_metrics["window"] = f"{start_window.date()} .. {result_date.date()}"

    return eval_metrics


def _rebase(predictor_instance, election_year):
    """
    Returns a predictor configured for `election_year`'s baseline.

    Falls back to mutating a copy of the given instance when it is not a
    LokSabhaSeatPredictor (the optimizer passes its own predictor class).
    """
    from app.elections.engine.seat_predictive_model import LokSabhaSeatPredictor

    if isinstance(predictor_instance, LokSabhaSeatPredictor):
        return LokSabhaSeatPredictor(
            baseline_year=election_year,
            cube_exponent=predictor_instance.cube_exponent,
            calibration=predictor_instance.calibration,
            tracker_weights=predictor_instance.tracker_weights,
        )

    import copy

    clone = copy.copy(predictor_instance)
    clone.baseline_year = election_year
    clone.baseline = HISTORICAL_ELECTION_RESULTS[election_year]
    return clone


def run_full_backtest(predictor_instance, tracker_df):
    """
    Runs combined backtest across both 2019 and 2024 Lok Sabha elections.
    """
    results_2019 = run_backtest_for_year(predictor_instance, tracker_df, 2019)
    results_2024 = run_backtest_for_year(predictor_instance, tracker_df, 2024)
    
    combined_mae = 0
    count = 0
    if results_2019:
        combined_mae += results_2019["mae"]
        count += 1
    if results_2024:
        combined_mae += results_2024["mae"]
        count += 1
        
    overall_mae = (combined_mae / count) if count > 0 else 999.0
    
    return {
        "2019": results_2019,
        "2024": results_2024,
        "overall_mae": overall_mae
    }


if __name__ == "__main__":
    from app.elections.engine.seat_predictive_model import LokSabhaSeatPredictor
    csv_path = "data/cvoter_daily_trackers.csv"
    if pd.io.common.file_exists(csv_path):
        tracker_df = pd.read_csv(csv_path)
        predictor = LokSabhaSeatPredictor(baseline_year=2024)
        
        print("Running Backtest Evaluation for 2019 and 2024 Lok Sabha Elections...")
        res = run_full_backtest(predictor, tracker_df)
        print(f"\nOverall Backtest MAE: {res['overall_mae']:.2f} seats")
        if res["2019"]:
            print(f"2019 Backtest: Pred={res['2019']['predicted_seats']} | Actual={res['2019']['actual_seats']} (MAE: {res['2019']['mae']:.1f})")
        if res["2024"]:
            print(f"2024 Backtest: Pred={res['2024']['predicted_seats']} | Actual={res['2024']['actual_seats']} (MAE: {res['2024']['mae']:.1f})")
