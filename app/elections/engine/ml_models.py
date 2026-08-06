"""
ml_models.py
------------
Alternative votes-to-seats models, run side by side against the same input.

All five models consume the identical feature vector -- the per-tracker net
sentiment scores from sentiment_index.py -- and differ only in how they turn
sentiment into seats. Comparing them shows how much of the forecast is driven
by the data and how much by the choice of seat-conversion mechanism.

    1. Extended cube law        seats proportional to vote^k, k fitted
    2. Softmax swing transfer   smoother seat curve, temperature-controlled
    3. Ridge regression         seats regressed directly on tracker nets
    4. Gradient-boosted trees   non-linear fit on the same targets
    5. Uniform regional swing   national swing applied state by state

Models 3 and 4 are genuinely fitted rather than hard-coded: they train on the
daily projection history anchored to the two observed election outcomes. With
only two elections there is not enough signal to fit seats on election data
alone, so they learn the sentiment-to-seats surface implied by the calibrated
structural model and then apply it. That makes them smoothers over the
structural model, not independent evidence -- which is what `note` reports.
"""

import numpy as np
import pandas as pd

from app.elections.engine.paths import DATA_DIR
from scipy.special import softmax
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import Ridge

from app.elections.engine.calibration import cube_law_seats, load_calibration
from app.elections.engine.election_data import HISTORICAL_ELECTION_RESULTS
from app.elections.engine.sentiment_index import compute_tracker_nets, composite_for_row
from app.elections.engine.tracker_schema import TRACKER_WEIGHTS

MAJORITY = 272


class MLSeatPredictorSuite:
    """Runs and compares several seat-conversion models on one survey day."""

    def __init__(self, baseline_year=2024, data_dir=DATA_DIR):
        self.baseline_year = baseline_year
        self.baseline = HISTORICAL_ELECTION_RESULTS[baseline_year]
        self.calibration = load_calibration(data_dir=data_dir)
        self.data_dir = data_dir

        summary = self.baseline["national_summary"]
        self.opp_key = "INDIA" if "INDIA" in summary else "UPA"
        self.base_nda = summary["NDA"]["vote_share"]
        self.base_opp = summary[self.opp_key]["vote_share"]
        self.base_oth = summary["OTHERS"]["vote_share"]
        self.india_ratio = self.base_opp / (self.base_opp + self.base_oth)
        self.total_seats = int(self.baseline.get("polled_seats", 543))

        vm = self.calibration["vote_share_model"]
        self.intercept = float(vm["intercept"])
        self.slope = float(vm["slope"])
        anchor = next((a for a in vm["anchors"] if a["year"] == baseline_year), None)
        self.base_composite = float(anchor["composite"]) if anchor else 0.0

        self._trained = None
        self._softmax_t = None

    # -- shared helpers ---------------------------------------------------

    def _composite(self, survey_row):
        value = composite_for_row(survey_row)
        return self.base_composite if pd.isna(value) else float(value)

    def _tracker_nets(self, survey_row):
        """Per-tracker net scores as an ordered feature vector."""
        frame = pd.DataFrame([dict(survey_row)])
        nets = compute_tracker_nets(frame)
        ordered = sorted(t for t in TRACKER_WEIGHTS if TRACKER_WEIGHTS[t] > 0)
        return np.array([
            float(nets[f"net_t{t}"].iloc[0]) if f"net_t{t}" in nets.columns
            and pd.notna(nets[f"net_t{t}"].iloc[0]) else 0.0
            for t in ordered
        ])

    def _vote_shares(self, composite, swing_mult=1.0):
        base_vote = self.intercept + self.slope * self.base_composite
        v_nda = base_vote + self.slope * swing_mult * (composite - self.base_composite)
        v_nda = float(np.clip(v_nda, 25.0, 60.0))
        rem = 100.0 - v_nda
        return v_nda, rem * self.india_ratio, rem * (1.0 - self.india_ratio)

    # -- model 1: extended cube law ---------------------------------------

    def predict_cube_law(self, survey_row, k=None, swing_mult=1.0):
        composite = self._composite(survey_row)
        v_nda, v_india, v_oth = self._vote_shares(composite, swing_mult)
        exponent = float(k) if k is not None else float(self.calibration["cube_exponent"])
        s_nda, s_india, s_oth = cube_law_seats(v_nda, v_india, v_oth, exponent, self.total_seats)
        return {
            "NDA": s_nda, "INDIA": s_india, "OTHERS": s_oth,
            "model": f"Extended Cube Law (k={exponent:.2f})",
            "note": "Structural model, exponent fitted jointly on 2019 and 2024.",
        }

    # -- model 2: softmax swing transfer ----------------------------------

    def _fit_softmax_temperature(self, t_lo=1.0, t_hi=40.0, steps=1001):
        """
        Fits the softmax temperature the same way the cube exponent is fitted:
        the single value minimising total seat error across observed elections.

        Left unfitted this model is wildly miscalibrated -- softmax over raw
        vote-share points is extremely peaked at any small temperature.
        """
        if getattr(self, "_softmax_t", None) is not None:
            return self._softmax_t

        cases = []
        for year, res in HISTORICAL_ELECTION_RESULTS.items():
            summary = res["national_summary"]
            opp_key = "INDIA" if "INDIA" in summary else "UPA"
            cases.append((
                np.array([summary["NDA"]["vote_share"], summary[opp_key]["vote_share"],
                          summary["OTHERS"]["vote_share"]]),
                np.array([summary["NDA"]["seats"], summary[opp_key]["seats"],
                          summary["OTHERS"]["seats"]]),
                res.get("polled_seats", 543),
            ))

        best_t, best_cost = t_hi, float("inf")
        for t in np.linspace(t_lo, t_hi, steps):
            cost = 0.0
            for votes, seats, total in cases:
                pred = softmax(votes / t) * total
                cost += float(np.sum(np.abs(pred - seats)))
            if cost < best_cost:
                best_cost, best_t = cost, float(t)

        self._softmax_t = best_t
        return best_t

    def predict_logistic_softmax(self, survey_row, temperature=None):
        """
        Softmax over vote shares. Temperature plays the role the cube exponent
        plays above, but with a gentler tail, so it under-rewards the leader at
        wide margins -- a useful check on the cube law's seat bonus.
        """
        temperature = float(temperature) if temperature is not None else self._fit_softmax_temperature()
        composite = self._composite(survey_row)
        v_nda, v_india, v_oth = self._vote_shares(composite)
        probs = softmax(np.array([v_nda, v_india, v_oth]) / temperature)
        s_nda = int(round(probs[0] * self.total_seats))
        s_india = int(round(probs[1] * self.total_seats))
        return {
            "NDA": s_nda, "INDIA": s_india, "OTHERS": self.total_seats - s_nda - s_india,
            "model": f"Softmax Swing Transfer (T={temperature:.2f})",
            "note": "Temperature fitted across observed elections; softer tail than cube law.",
        }

    # -- fitted models 3 and 4 --------------------------------------------

    def _training_set(self):
        """
        Builds (X, y) from the daily projection history.

        X = per-tracker net scores, y = NDA and opposition seats from the
        calibrated structural model. Cached after the first call.
        """
        if self._trained is not None:
            return self._trained

        import os

        path = os.path.join(self.data_dir, "cvoter_daily_trackers.csv")
        df = pd.read_csv(path)
        nets = compute_tracker_nets(df)
        ordered = sorted(t for t in TRACKER_WEIGHTS if TRACKER_WEIGHTS[t] > 0)
        cols = [f"net_t{t}" for t in ordered if f"net_t{t}" in nets.columns]

        from app.elections.engine.seat_predictive_model import predict_series

        targets = predict_series(df, baseline_year=self.baseline_year, data_dir=self.data_dir)

        X = nets[cols].ffill().bfill().fillna(0.0).to_numpy()
        y_nda = targets["NDA_proj_seats"].to_numpy()
        y_india = targets["INDIA_proj_seats"].to_numpy()

        ridge_nda = Ridge(alpha=1.0).fit(X, y_nda)
        ridge_india = Ridge(alpha=1.0).fit(X, y_india)
        gb_nda = GradientBoostingRegressor(random_state=0, n_estimators=120, max_depth=3).fit(X, y_nda)
        gb_india = GradientBoostingRegressor(random_state=0, n_estimators=120, max_depth=3).fit(X, y_india)

        self._trained = {
            "columns": cols,
            "ridge": (ridge_nda, ridge_india),
            "gb": (gb_nda, gb_india),
            "r2_ridge": float(ridge_nda.score(X, y_nda)),
            "r2_gb": float(gb_nda.score(X, y_nda)),
        }
        return self._trained

    def predict_ridge_regression(self, survey_row):
        trained = self._training_set()
        feats = self._tracker_nets(survey_row).reshape(1, -1)
        m_nda, m_india = trained["ridge"]
        s_nda = int(round(float(m_nda.predict(feats)[0])))
        s_india = int(round(float(m_india.predict(feats)[0])))
        s_nda = int(np.clip(s_nda, 0, self.total_seats))
        s_india = int(np.clip(s_india, 0, self.total_seats - s_nda))
        return {
            "NDA": s_nda, "INDIA": s_india, "OTHERS": self.total_seats - s_nda - s_india,
            "model": "Ridge Regression",
            "note": f"Linear fit on tracker nets, in-sample R2 {trained['r2_ridge']:.3f}.",
        }

    def predict_random_forest(self, survey_row):
        trained = self._training_set()
        feats = self._tracker_nets(survey_row).reshape(1, -1)
        m_nda, m_india = trained["gb"]
        s_nda = int(round(float(m_nda.predict(feats)[0])))
        s_india = int(round(float(m_india.predict(feats)[0])))
        s_nda = int(np.clip(s_nda, 0, self.total_seats))
        s_india = int(np.clip(s_india, 0, self.total_seats - s_nda))
        return {
            "NDA": s_nda, "INDIA": s_india, "OTHERS": self.total_seats - s_nda - s_india,
            "model": "Gradient Boosted Trees",
            "note": f"Non-linear fit on tracker nets, in-sample R2 {trained['r2_gb']:.3f}.",
        }

    # -- model 5: uniform regional swing ----------------------------------

    def predict_regional_swing(self, survey_row):
        """
        Applies the national vote swing state by state, converting swing into
        seats through each state's own baseline vote-to-seat sensitivity rather
        than a single national curve.
        """
        composite = self._composite(survey_row)
        v_nda, _, _ = self._vote_shares(composite)
        national_swing = v_nda - self.base_nda

        states = self.baseline["state_baselines"]
        tot_nda = tot_opp = tot_oth = 0
        covered = 0

        for info in states.values():
            seats = info["total"]
            covered += seats
            base_n = info["NDA"]
            base_i = info.get("INDIA", info.get("UPA", 0))
            base_o = info["OTHERS"]

            # Seats respond to swing most sharply where the contest is close.
            share = base_n / seats if seats else 0.0
            marginality = 4.0 * share * (1.0 - share)  # peaks at a 50/50 split
            delta = national_swing * marginality * seats / 100.0 * 3.0

            proj_n = int(round(np.clip(base_n + delta, 0, seats)))
            rem = seats - proj_n
            denom = base_i + base_o
            proj_i = int(round(rem * (base_i / denom))) if denom > 0 else rem
            tot_nda += proj_n
            tot_opp += proj_i
            tot_oth += rem - proj_i

        # States not in the baseline table keep their national-model share.
        remaining = self.total_seats - covered
        if remaining > 0:
            nat = self.predict_cube_law(survey_row)
            scale = remaining / self.total_seats
            tot_nda += int(round(nat["NDA"] * scale))
            tot_opp += int(round(nat["INDIA"] * scale))
            tot_oth = self.total_seats - tot_nda - tot_opp

        return {
            "NDA": tot_nda, "INDIA": tot_opp, "OTHERS": max(0, tot_oth),
            "model": "Uniform Regional Swing",
            "note": "National swing applied per state, weighted by seat marginality.",
        }

    # -- comparison -------------------------------------------------------

    def compare_all_models(self, survey_row):
        results = [
            self.predict_cube_law(survey_row),
            self.predict_logistic_softmax(survey_row),
            self.predict_ridge_regression(survey_row),
            self.predict_random_forest(survey_row),
            self.predict_regional_swing(survey_row),
        ]
        for item in results:
            item["majority_winner"] = (
                "NDA" if item["NDA"] >= MAJORITY
                else "INDIA" if item["INDIA"] >= MAJORITY
                else "Hung Parliament"
            )
        return results


if __name__ == "__main__":
    import os

    df = pd.read_csv(os.path.join(DATA_DIR, "cvoter_daily_trackers.csv"))
    suite = MLSeatPredictorSuite(baseline_year=2024)
    latest = df.iloc[-1]

    print(f"Model comparison for {latest['date']}\n")
    for m in suite.compare_all_models(latest):
        print(f"  {m['model']:<34} NDA {m['NDA']:>3} | INDIA {m['INDIA']:>3} | "
              f"OTHERS {m['OTHERS']:>3}  -> {m['majority_winner']}")
        print(f"  {'':<34} {m['note']}")
