"""
insights.py
-----------
Event impact attribution and the executive summary.

Two questions this answers:

    1. Which marked events coincided with the largest moves in the projection?
    2. What does the whole dashboard add up to, in words?

Impact method
-------------
For each event in events.py, compare the mean projection over a window *after*
the event to the mean over a window *before* it:

    pre  = [start - pre_days, start - 1]
    post = [start, end + post_days]          (end == start for point events)

    impact = mean(post) - mean(pre)

The post-window opens at the event's *start*, not its end, so a long-running
event is scored on the move that happens during it as well as after it. For a
50-day protest the effect shows up while it is running; waiting for it to
finish before measuring would miss the whole move.

reported both in NDA seats and in composite index points. A `z` score divides
the seat impact by the standard deviation of 30-day changes across the whole
series, so a move is judged against how much this series normally drifts rather
than against an arbitrary threshold.

This is association, not causation, and it is stated as such everywhere it
surfaces. Three limits in particular:

  * Events overlap. The 2026 protest wave, the NEET cancellation and the CJI
    remark all sit inside eight weeks, so their windows share days and their
    attributed impacts are not independent.
  * The model has no event variable. It only sees survey answers, so an impact
    here means "the electorate's answers moved across this window", not "this
    event caused the move".
  * A window straddling an election inherits the campaign swing.

`confounded_by` lists other events whose windows overlap, so a reader can see
which numbers are entangled.
"""

import numpy as np
import pandas as pd

from app.elections.engine.paths import DATA_DIR
from app.elections.engine.events import EVENTS
from app.elections.engine.trend_analytics import summarize

DEFAULT_PRE_DAYS = 30
DEFAULT_POST_DAYS = 30
# Shortest post-window we will still score, when the data ends mid-window.
MIN_POST_DAYS = 10
# Smallest move worth reporting at all, and the threshold below which a move is
# flagged as indistinguishable from the series' ordinary 30-day drift. Both are
# in units of that drift's standard deviation.
MIN_REPORTABLE_Z = 0.4
NOISE_Z = 1.0
MAJORITY = 272


def _window_mean(df, start, end, column):
    """Mean of `column` over an inclusive date window, or NaN if unavailable."""
    mask = (df["date"] >= start) & (df["date"] <= end)
    values = df.loc[mask, column].dropna()
    return float(values.mean()) if len(values) else np.nan


def compute_event_impacts(projections, events=None, pre_days=DEFAULT_PRE_DAYS,
                          post_days=DEFAULT_POST_DAYS, min_post_days=MIN_POST_DAYS,
                          seat_col="NDA_proj_seats", composite_col="composite_sentiment"):
    """
    Scores every event by the shift in the projection across it.

    Returns a list of dicts sorted by impact, most positive first.

    An event needs its full pre-window, but its post-window may be truncated by
    the end of the data down to `min_post_days`. Without that allowance the most
    recent events -- the ones a reader most wants scored -- would all be
    dropped. Truncated rows carry `partial: True` and the day count actually
    used, and should be read as provisional: a 10-day read on an event can still
    reverse as more data arrives.
    """
    events = events if events is not None else EVENTS

    df = projections.copy()
    df["date"] = pd.to_datetime(df["date"])
    data_start, data_end = df["date"].min(), df["date"].max()

    # Scale for the z score: how much this series normally moves over 30 days.
    drift = df[seat_col].astype(float).diff(pre_days).dropna()
    drift_sd = float(drift.std()) if len(drift) > 1 else np.nan

    results = []
    for event in events:
        start = pd.to_datetime(event["date"])
        end = pd.to_datetime(event.get("end_date", event["date"]))

        pre_start = start - pd.Timedelta(days=pre_days)
        pre_end = start - pd.Timedelta(days=1)
        post_start = start
        post_end = end + pd.Timedelta(days=post_days)

        # The pre-window must be complete; the post-window may be clipped by
        # the end of the data, down to min_post_days.
        if pre_start < data_start or start > data_end:
            continue
        available_post = (data_end - post_start).days + 1
        if available_post < min_post_days:
            continue
        partial = post_end > data_end
        if partial:
            post_end = data_end

        pre_seats = _window_mean(df, pre_start, pre_end, seat_col)
        post_seats = _window_mean(df, post_start, post_end, seat_col)
        pre_comp = _window_mean(df, pre_start, pre_end, composite_col)
        post_comp = _window_mean(df, post_start, post_end, composite_col)

        if np.isnan(pre_seats) or np.isnan(post_seats):
            continue

        impact_seats = post_seats - pre_seats
        impact_comp = post_comp - pre_comp

        # Other events whose full window overlaps this one.
        confounders = []
        for other in events:
            if other["id"] == event["id"]:
                continue
            o_start = pd.to_datetime(other["date"]) - pd.Timedelta(days=pre_days)
            o_end = pd.to_datetime(other.get("end_date", other["date"])) + pd.Timedelta(days=post_days)
            if o_start <= post_end and o_end >= pre_start:
                confounders.append(other["label"])

        results.append({
            "id": event["id"],
            "label": event["label"],
            "category": event["category"],
            "date": event["date"],
            "end_date": event.get("end_date"),
            "prior_expectation": event["impact"],
            "description": event["description"],
            "pre_seats": round(pre_seats, 1),
            "post_seats": round(post_seats, 1),
            "impact_seats": round(impact_seats, 1),
            "impact_composite": round(impact_comp, 2) if not np.isnan(impact_comp) else None,
            "z": round(impact_seats / drift_sd, 2) if drift_sd and drift_sd > 0 else None,
            "partial": bool(partial),
            "post_days_used": int(min(available_post, post_days)),
            "direction": "helped NDA" if impact_seats > 0 else ("hurt NDA" if impact_seats < 0 else "no move"),
            "matches_prior": _matches_prior(event["impact"], impact_seats),
            "confounded_by": confounders,
            "window": {
                "pre": f"{pre_start.date()} .. {pre_end.date()}",
                "post": f"{post_start.date()} .. {post_end.date()}"
                        + (" (truncated by end of data)" if partial else ""),
            },
        })

    results.sort(key=lambda r: r["impact_seats"], reverse=True)
    return results


def _matches_prior(prior, impact_seats):
    """Whether the measured move agrees with the direction we expected."""
    if prior == "mixed" or abs(impact_seats) < 0.5:
        return None
    if prior == "positive":
        return impact_seats > 0
    if prior == "negative":
        return impact_seats < 0
    return None


def top_impacts(projections, n=5, min_z=MIN_REPORTABLE_Z, noise_z=NOISE_Z, **kwargs):
    """
    The n most credible positive and negative events for the incumbent.

    A raw ranking is misleading here, because a series that wanders by a seat or
    two will always produce a "top 5" in each direction whether or not anything
    happened. Three filters decide what is reportable:

      1. Elections are dropped. A general election is not an incident acting on
         the projection, it is the thing the projection is trying to predict, so
         scoring it produces the campaign swing dressed up as an event effect.

      2. Events whose measured move contradicts their own nature are dropped.
         The Agnipath protests and the Manipur violence both scored positive for
         the incumbent, which is not a finding -- it is two sub-noise wobbles
         that happen to point the wrong way. Listing them as things that lifted
         the seat count would be actively misleading.

      3. Moves smaller than `min_z` are dropped, and moves smaller than
         `noise_z` are kept but flagged `within_noise`, because they are not
         distinguishable from the series' ordinary 30-day drift.

    Everything filtered out is counted and reported in `excluded`, so the tables
    never silently hide events.
    """
    ranked = compute_event_impacts(projections, **kwargs)

    excluded = {"elections": 0, "contradicts_nature": 0, "below_noise_floor": 0}
    eligible = []

    for row in ranked:
        if row["category"] == "election":
            excluded["elections"] += 1
            continue
        if row["matches_prior"] is False:
            excluded["contradicts_nature"] += 1
            continue
        if row["z"] is None or abs(row["z"]) < min_z:
            excluded["below_noise_floor"] += 1
            continue
        row["within_noise"] = abs(row["z"]) < noise_z
        eligible.append(row)

    positive = [r for r in eligible if r["impact_seats"] > 0][:n]
    negative = [r for r in eligible if r["impact_seats"] < 0][-n:][::-1]

    return {
        "positive": positive,
        "negative": negative,
        "evaluated": len(ranked),
        "reported": len(positive) + len(negative),
        "excluded": excluded,
        "method": {
            "pre_days": kwargs.get("pre_days", DEFAULT_PRE_DAYS),
            "post_days": kwargs.get("post_days", DEFAULT_POST_DAYS),
            "min_z": min_z,
            "noise_z": noise_z,
            "measure": "mean NDA projected seats after minus before",
            "caveat": "Association, not causation. Windows overlap and the model has no event variable.",
        },
    }


def executive_summary(projections, overview, contributions=None, backtest=None):
    """
    Builds the narrative summary block from the numbers already computed
    elsewhere, so nothing here can drift from the rest of the dashboard.
    """
    df = projections.copy()
    nda = summarize(df, value_col="NDA_proj_seats")
    india = summarize(df, value_col="INDIA_proj_seats")
    comp = summarize(df, value_col="composite_sentiment")

    forecast = overview.get("latest_forecast", {})
    seats = forecast.get("point_estimate", {}).get("predicted_seats", {})
    ci = forecast.get("confidence_intervals", {})
    prob = forecast.get("majority_probability", {})

    last_election_nda = overview.get("actual_2024_nda", 293)
    vs_le = nda["current_estimate"] - last_election_nda
    ci_nda = ci.get("NDA", {})
    half_width = int(round((ci_nda.get("p95", 0) - ci_nda.get("p5", 0)) / 2)) if ci_nda else None

    # Longest sustained stretch on the current side of the majority line.
    above = df["NDA_proj_seats"] >= MAJORITY
    streak = 0
    for value in reversed(above.tolist()):
        if value == above.iloc[-1]:
            streak += 1
        else:
            break

    headlines = []

    headlines.append(
        f"NDA projects to {nda['current_estimate']} seats"
        + (f" (±{half_width} at 90% confidence)" if half_width else "")
        + f", {abs(vs_le)} {'above' if vs_le > 0 else 'below'} its 2024 result of {last_election_nda}."
    )

    outcome = max(
        [("an NDA majority", prob.get("NDA", 0)),
         ("a hung parliament", prob.get("HUNG", 0)),
         ("an INDIA majority", prob.get("INDIA", 0))],
        key=lambda x: x[1],
    )
    headlines.append(
        f"The most likely outcome is {outcome[0]} at {outcome[1]:.0%}, "
        f"with a hung parliament at {prob.get('HUNG', 0):.0%}. "
        f"The projection has sat {'above' if above.iloc[-1] else 'below'} the 272 line "
        f"for {streak} consecutive days."
    )

    if nda["trend_direction"] == "flat":
        headlines.append(
            f"The 30-day trend is flat: the {nda['trend_slope_per_day']:+.3f} seats/day slope "
            f"is not statistically distinguishable from zero (t={nda['trend_slope_t_stat']:+.1f})."
        )
    else:
        headlines.append(
            f"The 30-day trend is {nda['trend_direction']} at {nda['trend_slope_per_day']:+.3f} "
            f"seats/day ({nda['trend_30d_total']:+.1f} seats over the window, "
            f"R² {nda['trend_slope_r2']:.2f}), with the 7-day average "
            f"{'above' if nda['momentum'] > 0 else 'below'} the 30-day by "
            f"{abs(nda['momentum']):.1f} seats."
        )

    headlines.append(
        f"The composite sentiment index reads {comp['current_estimate']:+d} on a ±100 scale, "
        f"against {comp['ma_30d']:+.1f} on the 30-day average. Daily volatility is "
        f"{nda['volatility']:.2f} seats, so moves under roughly "
        f"{2 * nda['volatility']:.1f} seats are inside the day-to-day noise."
    )

    drivers = {"negative": [], "positive": []}
    if contributions:
        for item in contributions:
            bucket = "positive" if item["contribution"] > 0 else "negative"
            if len(drivers[bucket]) < 3:
                drivers[bucket].append({
                    "metric": item["metric_name"],
                    "share": item["share"],
                    "contribution": item["contribution"],
                })
        if drivers["negative"]:
            worst = drivers["negative"][0]
            headlines.append(
                f"The single heaviest drag is \"{worst['metric']}\" at {worst['share']:.1f}% "
                f"of respondents, contributing {worst['contribution']:.1f} index points."
            )

    caveats = [
        "The vote-share fit rests on only two elections inside the data window, so its "
        "uncertainty is wider than the confidence interval alone suggests.",
        "Event impacts are associations measured across overlapping windows, not causal estimates.",
        "The model is national uniform swing. It has no seat-level or state-level contest data, "
        "so it cannot see alliance arithmetic or candidate effects.",
    ]
    if backtest:
        caveats.insert(0, (
            f"Backtest error against the two observed elections averages "
            f"{backtest.get('overall_mae', 0):.1f} seats, which is the honest floor on precision here."
        ))

    return {
        "as_of_date": nda["as_of_date"],
        "headlines": headlines,
        "drivers": drivers,
        "caveats": caveats,
        "figures": {
            "nda_seats": nda["current_estimate"],
            "india_seats": india["current_estimate"],
            "others_seats": seats.get("OTHERS"),
            "nda_vs_last_election": vs_le,
            "nda_ci": [ci_nda.get("p5"), ci_nda.get("p95")],
            "prob_nda_majority": prob.get("NDA"),
            "prob_hung": prob.get("HUNG"),
            "prob_india_majority": prob.get("INDIA"),
            "trend_slope_per_day": nda["trend_slope_per_day"],
            "trend_direction": nda["trend_direction"],
            "volatility": nda["volatility"],
            "momentum": nda["momentum"],
            "composite": comp["current_estimate"],
        },
    }


if __name__ == "__main__":
    import os

    proj = pd.read_csv(os.path.join(DATA_DIR, "ideal_model_daily_projections.csv"))
    top = top_impacts(proj, n=5)

    print(f"Scored {top['evaluated']} events "
          f"({top['method']['pre_days']}d before vs {top['method']['post_days']}d after)\n")

    for bucket, title in (("positive", "HELPED NDA"), ("negative", "HURT NDA")):
        print(f"{title}")
        print(f"  {'seats':>7}  {'index':>7}  {'z':>5}  event")
        for row in top[bucket]:
            print(f"  {row['impact_seats']:>+7.1f}  {row['impact_composite']:>+7.2f}  "
                  f"{row['z']:>+5.2f}  {row['label']} ({row['date']})")
        print()
