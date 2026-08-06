"""
calibration.py
--------------
Fits the sentiment -> vote share -> seats mapping against actual results.

The original model used two magic numbers: a swing multiplier of 0.35 vote
points per governance point, and a cube-law exponent of 2.4 (2.8 in main.py).
Neither was derived from anything. This module replaces both with values fitted
to the elections we actually observe in the tracker window.

Step 1 -- vote share.
    Take the mean composite sentiment index over each election's campaign
    window (MCC announcement through final polling day) and pair it with the
    NDA's actual national vote share. Two elections fall inside the CVoter
    series (2019: 45.0%, 2024: 43.6%), giving an exact two-point linear fit

        nda_vote_share = intercept + slope * composite_sentiment

Step 2 -- seats.
    Solve the extended cube-law exponent k such that the 2024 vote shares
    reproduce the 2024 seat count (NDA 293 of 543) exactly. This anchors the
    votes-to-seats conversion on the most recent observed election rather than
    on a textbook constant.

The fitted constants are written to data/model_calibration.json so the web app
and the daily predictor share one source of truth.
"""

import json
import os

import numpy as np
import pandas as pd

from app.elections.engine.paths import DATA_DIR

from app.elections.engine.election_data import ELECTION_TIMELINES, HISTORICAL_ELECTION_RESULTS
from app.elections.engine.sentiment_index import compute_composite

CALIBRATION_PATH = os.path.join(DATA_DIR, "model_calibration.json")

# Fallback slope (vote points per composite point) used when fewer than two
# elections fall inside the data window, or when the fit comes out perverse.
FALLBACK_SLOPE = 0.12
FALLBACK_K = 2.4


def campaign_window_mean(df, year, composite_col="composite_sentiment"):
    """Mean composite index over an election's MCC-to-final-poll window."""
    timeline = next((e for e in ELECTION_TIMELINES if e["year"] == year), None)
    if timeline is None:
        return np.nan

    dates = pd.to_datetime(df["date"])
    mask = (dates >= pd.to_datetime(timeline["mcc_date"])) & (
        dates <= pd.to_datetime(timeline["end_date"])
    )
    window = df.loc[mask, composite_col].dropna()
    return float(window.mean()) if len(window) else np.nan


def _nda_vote_share(year):
    return HISTORICAL_ELECTION_RESULTS[year]["national_summary"]["NDA"]["vote_share"]


def fit_vote_share_model(df):
    """
    Fits nda_vote_share = intercept + slope * composite.

    Uses every election whose campaign window is covered by the data. With two
    anchors this is an exact solve; with three or more it is a least squares
    fit. Returns (intercept, slope, anchors).
    """
    if "composite_sentiment" not in df.columns:
        df = df.copy()
        df["composite_sentiment"] = compute_composite(df)

    anchors = []
    for timeline in ELECTION_TIMELINES:
        year = timeline["year"]
        if year not in HISTORICAL_ELECTION_RESULTS:
            continue
        composite = campaign_window_mean(df, year)
        if np.isnan(composite):
            continue
        anchors.append({
            "year": year,
            "composite": round(composite, 4),
            "actual_nda_vote_share": _nda_vote_share(year),
            "window": f"{timeline['mcc_date']} .. {timeline['end_date']}",
        })

    if len(anchors) < 2:
        # Not enough coverage to fit; pin the intercept on whichever election we
        # do have (or the baseline) and use the prior slope.
        base = anchors[0] if anchors else {
            "composite": 0.0,
            "actual_nda_vote_share": _nda_vote_share(2024),
        }
        slope = FALLBACK_SLOPE
        intercept = base["actual_nda_vote_share"] - slope * base["composite"]
        return float(intercept), float(slope), anchors

    xs = np.array([a["composite"] for a in anchors], dtype=float)
    ys = np.array([a["actual_nda_vote_share"] for a in anchors], dtype=float)
    slope, intercept = np.polyfit(xs, ys, 1)

    if slope <= 0:
        # A negative slope would mean rising distress helps the incumbent.
        # Treat that as an unidentified fit and fall back to the prior.
        slope = FALLBACK_SLOPE
        intercept = float(ys.mean() - slope * xs.mean())

    return float(intercept), float(slope), anchors


def cube_law_seats(v_nda, v_india, v_others, k, total_seats=543):
    """Extended cube law: seats_i proportional to vote_i ** k."""
    powers = np.array([max(v, 1e-6) ** k for v in (v_nda, v_india, v_others)], dtype=float)
    shares = powers / powers.sum()
    s_nda = int(round(shares[0] * total_seats))
    s_india = int(round(shares[1] * total_seats))
    return s_nda, s_india, total_seats - s_nda - s_india


def fit_cube_exponent(year=2024, tolerance=1e-4, k_lo=1.0, k_hi=6.0):
    """
    Solves for the exponent k that reproduces `year`'s actual seat split.

    NDA seat share rises monotonically in k whenever the NDA leads on votes, so
    a simple bisection is sufficient and stable.
    """
    summary = HISTORICAL_ELECTION_RESULTS[year]["national_summary"]
    opp_key = "INDIA" if "INDIA" in summary else "UPA"
    total_seats = HISTORICAL_ELECTION_RESULTS[year].get("polled_seats", 543)

    v_nda = summary["NDA"]["vote_share"]
    v_opp = summary[opp_key]["vote_share"]
    v_oth = summary["OTHERS"]["vote_share"]
    target_share = summary["NDA"]["seats"] / total_seats

    def nda_share(k):
        powers = np.array([v_nda ** k, v_opp ** k, v_oth ** k], dtype=float)
        return powers[0] / powers.sum()

    lo, hi = k_lo, k_hi
    if not (nda_share(lo) - target_share) * (nda_share(hi) - target_share) < 0:
        return FALLBACK_K

    for _ in range(200):
        mid = (lo + hi) / 2.0
        if abs(nda_share(mid) - target_share) < tolerance:
            return float(mid)
        if nda_share(mid) < target_share:
            lo = mid
        else:
            hi = mid
    return float((lo + hi) / 2.0)


def fit_cube_exponent_joint(years=(2019, 2024), k_lo=1.0, k_hi=6.0, steps=1001):
    """
    Solves for the single exponent k that best reproduces *all* observed
    elections, minimising total absolute seat error across alliances.

    Fitting k to 2024 alone gives k ~ 3.9, which then badly overstates the
    leader's seat bonus when applied to 2019's far more fragmented opposition
    (NDA 45% vs UPA 27% / Others 28%). A joint fit trades a little accuracy on
    2024 for a model that generalises across alliance structures, which is what
    a forward-looking projection needs.

    Returns (k, per_year_errors).
    """
    cases = []
    for year in years:
        if year not in HISTORICAL_ELECTION_RESULTS:
            continue
        summary = HISTORICAL_ELECTION_RESULTS[year]["national_summary"]
        opp_key = "INDIA" if "INDIA" in summary else "UPA"
        total = HISTORICAL_ELECTION_RESULTS[year].get("polled_seats", 543)
        cases.append({
            "year": year,
            "votes": (summary["NDA"]["vote_share"], summary[opp_key]["vote_share"], summary["OTHERS"]["vote_share"]),
            "seats": (summary["NDA"]["seats"], summary[opp_key]["seats"], summary["OTHERS"]["seats"]),
            "total": total,
        })

    if not cases:
        return FALLBACK_K, {}

    best_k, best_cost = FALLBACK_K, float("inf")
    for k in np.linspace(k_lo, k_hi, steps):
        cost = 0.0
        for case in cases:
            pred = cube_law_seats(*case["votes"], k, case["total"])
            cost += sum(abs(p - a) for p, a in zip(pred, case["seats"]))
        if cost < best_cost:
            best_cost, best_k = cost, float(k)

    errors = {}
    for case in cases:
        pred = cube_law_seats(*case["votes"], best_k, case["total"])
        errors[case["year"]] = {
            "predicted": list(pred),
            "actual": list(case["seats"]),
            "mae": round(sum(abs(p - a) for p, a in zip(pred, case["seats"])) / 3.0, 2),
        }

    return best_k, errors


def calibrate(df=None, data_dir=DATA_DIR, write=True, baseline_year=2024, joint_exponent=True):
    """
    Runs the full calibration and (optionally) persists it.

    Returns the calibration dict consumed by seat_predictive_model.
    """
    if df is None:
        df = pd.read_csv(os.path.join(data_dir, "cvoter_daily_trackers.csv"))
    df = df.copy()
    if "composite_sentiment" not in df.columns:
        df["composite_sentiment"] = compute_composite(df)

    intercept, slope, anchors = fit_vote_share_model(df)
    if joint_exponent:
        k, exponent_fit = fit_cube_exponent_joint(
            years=tuple(a["year"] for a in anchors) or (2019, 2024)
        )
    else:
        k, exponent_fit = fit_cube_exponent(year=baseline_year), {}

    summary = HISTORICAL_ELECTION_RESULTS[baseline_year]["national_summary"]
    opp_key = "INDIA" if "INDIA" in summary else "UPA"
    base_opp = summary[opp_key]["vote_share"]
    base_oth = summary["OTHERS"]["vote_share"]

    calibration = {
        "baseline_year": baseline_year,
        "vote_share_model": {
            "intercept": round(intercept, 6),
            "slope": round(slope, 6),
            "form": "nda_vote_share = intercept + slope * composite_sentiment",
            "anchors": anchors,
        },
        "cube_exponent": round(k, 6),
        "cube_exponent_fit": {
            "method": "joint across observed elections" if joint_exponent else f"exact match on {baseline_year}",
            "per_year": exponent_fit,
        },
        "opposition_split": {
            # How the non-NDA vote divides between the main opposition bloc and
            # everyone else, held at its baseline-election ratio.
            "india_ratio": round(base_opp / (base_opp + base_oth), 6),
            "others_ratio": round(base_oth / (base_opp + base_oth), 6),
        },
        "total_seats": HISTORICAL_ELECTION_RESULTS[baseline_year].get("polled_seats", 543),
        "vote_share_bounds": [25.0, 60.0],
        "data_range": {
            "first_date": str(df["date"].min()),
            "last_date": str(df["date"].max()),
            "rows": int(len(df)),
        },
    }

    if write:
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, "model_calibration.json"), "w", encoding="utf-8") as fh:
            json.dump(calibration, fh, indent=2)

    return calibration


def load_calibration(data_dir=DATA_DIR, df=None):
    """Loads the persisted calibration, fitting it first if absent."""
    path = os.path.join(data_dir, "model_calibration.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return calibrate(df=df, data_dir=data_dir)


if __name__ == "__main__":
    cal = calibrate()
    print(json.dumps(cal, indent=2))

    vm = cal["vote_share_model"]
    print("\nBack-check against actual results:")
    for anchor in vm["anchors"]:
        year = anchor["year"]
        # Each election is scored against its own alliance structure -- the
        # non-NDA vote split differed sharply between 2019 and 2024.
        summary = HISTORICAL_ELECTION_RESULTS[year]["national_summary"]
        opp_key = "INDIA" if "INDIA" in summary else "UPA"
        opp_v, oth_v = summary[opp_key]["vote_share"], summary["OTHERS"]["vote_share"]
        india_ratio = opp_v / (opp_v + oth_v)
        total_seats = HISTORICAL_ELECTION_RESULTS[year].get("polled_seats", 543)

        v = vm["intercept"] + vm["slope"] * anchor["composite"]
        rem = 100.0 - v
        s_nda, s_opp, s_oth = cube_law_seats(
            v, rem * india_ratio, rem * (1.0 - india_ratio), cal["cube_exponent"], total_seats
        )
        actual = summary["NDA"]["seats"]
        print(
            f"  {year}: composite {anchor['composite']:+.2f} -> "
            f"vote {v:.2f}% (actual {anchor['actual_nda_vote_share']}%), "
            f"NDA seats {s_nda} (actual {actual})"
        )
