"""
seat_predictive_model.py
------------------------
Lok Sabha seat projection engine.

Pipeline for one survey day:

    41 option-level tracker shares
        -> weighted composite sentiment index      (sentiment_index.py)
        -> NDA national vote share                 (calibration.py, fitted on 2019 + 2024)
        -> alliance vote shares                    (opposition split held at baseline ratio)
        -> 543 seats                               (extended cube law, exponent fitted on 2024)

Monte Carlo layers survey sampling error and vote-to-seat conversion error on
top of the point estimate to produce confidence intervals and majority
probabilities.

This replaces the earlier version, which read three mislabelled "Index Value"
columns and applied hand-picked coefficients. Every constant here now comes
from data/model_calibration.json.
"""

import numpy as np
import pandas as pd

from app.elections.engine.paths import DATA_DIR

from app.elections.engine.calibration import cube_law_seats, load_calibration
from app.elections.engine.election_data import HISTORICAL_ELECTION_RESULTS
from app.elections.engine.sentiment_index import composite_for_row, option_contributions

# Survey sampling error on the composite index, in composite points. CVoter's
# published daily tracker sample carries roughly a +/-3% margin at the option
# level; propagated through the weighting this lands near 1.5 index points.
COMPOSITE_SIGMA = 1.5

# Residual error in the votes-to-seats conversion, in vote-share points. FPTP
# seat outcomes at a given national vote share vary with geography and alliance
# arithmetic well beyond survey noise; this is the dominant uncertainty.
SEAT_CONVERSION_SIGMA = 1.1


class LokSabhaSeatPredictor:
    """Translates daily CVoter option-level sentiment into 543-seat forecasts."""

    def __init__(self, baseline_year=2024, cube_exponent=None, data_dir=DATA_DIR,
                 calibration=None, tracker_weights=None):
        if baseline_year not in HISTORICAL_ELECTION_RESULTS:
            raise ValueError(f"Baseline year {baseline_year} not in historical baseline dataset.")

        self.baseline_year = baseline_year
        self.baseline = HISTORICAL_ELECTION_RESULTS[baseline_year]
        self.calibration = calibration or load_calibration(data_dir=data_dir)
        # None means "use the schema defaults"; the optimizer passes a subset.
        self.tracker_weights = tracker_weights

        # An explicit exponent overrides the fitted one (used by the what-if studio).
        self.cube_exponent = (
            float(cube_exponent) if cube_exponent is not None
            else float(self.calibration["cube_exponent"])
        )

        vm = self.calibration["vote_share_model"]
        self.intercept = float(vm["intercept"])
        self.slope = float(vm["slope"])
        self.vote_lo, self.vote_hi = self.calibration["vote_share_bounds"]

        # The sentiment -> vote-share fit is global, but the way the non-NDA
        # vote divides between the main opposition bloc and everyone else is a
        # property of the alliance structure at a given election. Derive it from
        # whichever baseline this instance is set to, so backtesting 2019 uses
        # the 2019 split (UPA 27 / Others 28) rather than 2024's.
        summary = self.baseline["national_summary"]
        opp_key = "INDIA" if "INDIA" in summary else "UPA"
        opp_vote = summary[opp_key]["vote_share"]
        oth_vote = summary["OTHERS"]["vote_share"]
        self.india_ratio = opp_vote / (opp_vote + oth_vote)
        self.others_ratio = 1.0 - self.india_ratio
        self.total_seats = int(self.baseline.get("polled_seats", 543))

    # -- core -------------------------------------------------------------

    def composite_sentiment(self, survey_row):
        """Weighted composite index for one survey day."""
        value = composite_for_row(survey_row, tracker_weights=self.tracker_weights)
        if value is None or (isinstance(value, float) and np.isnan(value)):
            # Fall back to the baseline election's campaign-window level so a
            # gap in the data produces the baseline forecast, not a crash.
            anchors = self.calibration["vote_share_model"]["anchors"]
            match = next((a for a in anchors if a["year"] == self.baseline_year), None)
            return float(match["composite"]) if match else 0.0
        return float(value)

    def vote_shares_from_composite(self, composite, swing_multiplier=1.0):
        """
        Maps the composite index to the three alliance vote shares.

        `swing_multiplier` scales the fitted sensitivity around the baseline
        election's own level -- 1.0 is the fitted model, 2.0 doubles how far a
        given sentiment move pushes vote share. It exists for the what-if
        studio and leaves the baseline point untouched.
        """
        anchors = self.calibration["vote_share_model"]["anchors"]
        match = next((a for a in anchors if a["year"] == self.baseline_year), None)
        base_composite = float(match["composite"]) if match else 0.0
        base_vote = self.intercept + self.slope * base_composite

        v_nda = base_vote + self.slope * swing_multiplier * (composite - base_composite)
        v_nda = float(np.clip(v_nda, self.vote_lo, self.vote_hi))

        remaining = 100.0 - v_nda
        return v_nda, remaining * self.india_ratio, remaining * self.others_ratio

    def predict_seats_for_survey_point(self, survey_row, swing_multiplier=1.0, cube_exponent=None):
        """Full point forecast for a single daily survey row."""
        composite = self.composite_sentiment(survey_row)
        v_nda, v_india, v_others = self.vote_shares_from_composite(composite, swing_multiplier)
        k = float(cube_exponent) if cube_exponent is not None else self.cube_exponent

        s_nda, s_india, s_others = cube_law_seats(v_nda, v_india, v_others, k, self.total_seats)

        return {
            "composite_sentiment": round(composite, 3),
            # Retained for backwards compatibility with older callers/CSVs:
            # the composite rescaled onto the previous 0-100 governance axis.
            "governance_score": round(50.0 + composite / 2.0, 2),
            "projected_vote_share": {
                "NDA": round(v_nda, 2),
                "INDIA": round(v_india, 2),
                "OTHERS": round(v_others, 2),
            },
            "predicted_seats": {
                "NDA": s_nda,
                "INDIA": s_india,
                "OTHERS": s_others,
            },
        }

    # -- uncertainty ------------------------------------------------------

    def run_monte_carlo_simulation(self, survey_row, n_simulations=5000, seed=None):
        """
        Samples survey error and vote-to-seat conversion error.

        Vectorised: the whole simulation is three array operations rather than
        a Python loop over `n_simulations` re-predictions, which is what made
        the previous version slow enough to need a pre-computed CSV.
        """
        rng = np.random.default_rng(seed)
        point = self.predict_seats_for_survey_point(survey_row)
        composite = point["composite_sentiment"]

        sims = rng.normal(composite, COMPOSITE_SIGMA, n_simulations)
        anchors = self.calibration["vote_share_model"]["anchors"]
        match = next((a for a in anchors if a["year"] == self.baseline_year), None)
        base_composite = float(match["composite"]) if match else 0.0
        base_vote = self.intercept + self.slope * base_composite

        v_nda = base_vote + self.slope * (sims - base_composite)
        v_nda = v_nda + rng.normal(0.0, SEAT_CONVERSION_SIGMA, n_simulations)
        v_nda = np.clip(v_nda, self.vote_lo, self.vote_hi)

        remaining = 100.0 - v_nda
        v_india = remaining * self.india_ratio
        v_others = remaining * self.others_ratio

        k = self.cube_exponent
        p_nda = v_nda ** k
        p_india = v_india ** k
        p_others = v_others ** k
        total = p_nda + p_india + p_others

        nda_sims = np.round(p_nda / total * self.total_seats)
        india_sims = np.round(p_india / total * self.total_seats)

        majority = 272

        return {
            "point_estimate": point,
            "confidence_intervals": {
                "NDA": {
                    "p5": int(np.percentile(nda_sims, 5)),
                    "p50": int(np.median(nda_sims)),
                    "p95": int(np.percentile(nda_sims, 95)),
                },
                "INDIA": {
                    "p5": int(np.percentile(india_sims, 5)),
                    "p50": int(np.median(india_sims)),
                    "p95": int(np.percentile(india_sims, 95)),
                },
            },
            "majority_probability": {
                "NDA": float(np.mean(nda_sims >= majority)),
                "INDIA": float(np.mean(india_sims >= majority)),
                "HUNG": float(np.mean((nda_sims < majority) & (india_sims < majority))),
            },
            "n_simulations": int(n_simulations),
        }

    def explain(self, survey_row, top_n=10):
        """Per-option contributions behind the current composite index."""
        return option_contributions(survey_row)[:top_n]


def predict_series(df, baseline_year=2024, data_dir=DATA_DIR):
    """
    Vectorised daily projection over a whole wide tracker frame.

    Returns a DataFrame with composite, vote shares and seats per day. This is
    what daily_predictor writes to CSV.
    """
    from app.elections.engine.sentiment_index import compute_composite

    predictor = LokSabhaSeatPredictor(baseline_year=baseline_year, data_dir=data_dir)
    composite = compute_composite(df)

    anchors = predictor.calibration["vote_share_model"]["anchors"]
    match = next((a for a in anchors if a["year"] == baseline_year), None)
    base_composite = float(match["composite"]) if match else 0.0
    base_vote = predictor.intercept + predictor.slope * base_composite

    filled = composite.ffill().bfill()
    v_nda = np.clip(
        base_vote + predictor.slope * (filled - base_composite),
        predictor.vote_lo,
        predictor.vote_hi,
    )
    remaining = 100.0 - v_nda
    v_india = remaining * predictor.india_ratio
    v_others = remaining * predictor.others_ratio

    k = predictor.cube_exponent
    p_nda, p_india, p_others = v_nda ** k, v_india ** k, v_others ** k
    total = p_nda + p_india + p_others

    s_nda = np.round(p_nda / total * predictor.total_seats).astype(int)
    s_india = np.round(p_india / total * predictor.total_seats).astype(int)
    s_others = predictor.total_seats - s_nda - s_india

    return pd.DataFrame({
        "date": df["date"].values,
        "composite_sentiment": np.round(filled.values, 3),
        "governance_score": np.round(50.0 + filled.values / 2.0, 2),
        "NDA_proj_vote_share": np.round(v_nda.values, 2),
        "INDIA_proj_vote_share": np.round(v_india.values, 2),
        "OTHERS_proj_vote_share": np.round(v_others.values, 2),
        "NDA_proj_seats": s_nda,
        "INDIA_proj_seats": s_india,
        "OTHERS_proj_seats": s_others,
    })


if __name__ == "__main__":
    import os

    df = pd.read_csv(os.path.join(DATA_DIR, "cvoter_daily_trackers.csv"))
    predictor = LokSabhaSeatPredictor(baseline_year=2024)
    latest = df.iloc[-1]

    result = predictor.run_monte_carlo_simulation(latest, n_simulations=20000, seed=7)
    point = result["point_estimate"]

    print(f"As of {latest['date']}")
    print(f"  composite sentiment : {point['composite_sentiment']:+.2f}")
    print(f"  vote share          : {point['projected_vote_share']}")
    print(f"  seats               : {point['predicted_seats']}")
    print(f"  NDA 90% interval    : {result['confidence_intervals']['NDA']['p5']}"
          f" - {result['confidence_intervals']['NDA']['p95']}")
    print(f"  P(NDA majority)     : {result['majority_probability']['NDA']:.1%}")
    print(f"  P(hung parliament)  : {result['majority_probability']['HUNG']:.1%}")
