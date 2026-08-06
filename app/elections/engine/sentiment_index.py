"""
sentiment_index.py
------------------
Weighted composite sentiment index built from the option-level CVoter series.

The old model reduced each tracker to a single number (in fact the *first*
answer option, mislabelled "Index Value") and combined those with hand-picked
coefficients. That threw away the part of the data that actually carries the
political signal: which answer respondents chose.

Here every answer option contributes with an explicit polarity (does this
answer imply support for or against the incumbent?) and an explicit salience
weight (how strongly does a point of this answer move vote intention?). Both
live in tracker_schema.py and can be tuned in one place.

Per tracker t on day d:

    shares are renormalized across the options actually observed that day
    raw_t   = sum_i  polarity_i * weight_i * share_i
    net_t   = 100 * raw_t / (100 * max_i(weight_i * |polarity_i|))
            = raw_t / max_i(weight_i * |polarity_i|)          -> bounded [-100, +100]

Composite across trackers, weighted by TRACKER_WEIGHTS (Self/Nation heaviest):

    composite = sum_t TW_t * net_t / sum_t TW_t

`composite` is the single scalar the seat model consumes. It is negative when
the electorate reports distress and positive when it reports improvement.
"""

import numpy as np
import pandas as pd

from app.elections.engine.paths import DATA_DIR

from app.elections.engine.tracker_schema import TRACKER_SCHEMA, TRACKER_WEIGHTS, column_name


def tracker_option_columns(tracker_id, available_columns=None):
    """Returns [(column, polarity, weight), ...] for one tracker."""
    out = []
    for label, polarity, weight in TRACKER_SCHEMA[tracker_id]["options"]:
        col = column_name(tracker_id, label)
        if available_columns is None or col in available_columns:
            out.append((col, polarity, weight))
    return out


def _tracker_scale(specs):
    """Max achievable |raw| per share point -- used to normalize net_t to +/-100."""
    scale = max((w * abs(p) for _, p, w in specs), default=0.0)
    return scale if scale > 0 else None


def compute_tracker_nets(df):
    """
    Computes the per-tracker net sentiment score for every row of a wide frame.

    Returns a DataFrame indexed like `df` with one column per tracker,
    named "net_t<id>", each bounded to roughly [-100, +100]. Trackers with no
    polarised options (Media Usage) are skipped.
    """
    cols = set(df.columns)
    result = pd.DataFrame(index=df.index)

    for tracker_id in TRACKER_SCHEMA:
        specs = tracker_option_columns(tracker_id, cols)
        scale = _tracker_scale(specs)
        if scale is None or not specs:
            continue

        shares = df[[c for c, _, _ in specs]].astype(float)
        # Renormalize to 100 across the options present that day. Guards against
        # trackers whose series start later, and against multi-select items
        # whose raw shares do not sum to exactly 100.
        totals = shares.sum(axis=1, skipna=True)
        totals = totals.where(totals > 0)
        norm = shares.div(totals, axis=0) * 100.0

        raw = sum(norm[c] * p * w for c, p, w in specs)
        result[f"net_t{tracker_id}"] = raw / scale

    return result


def compute_composite(df, tracker_weights=None):
    """
    Computes the weighted composite index for a wide frame.

    Returns a Series aligned to `df`. Rows where a tracker is missing simply
    drop that tracker from both numerator and denominator, so the composite
    stays on the same scale across the whole history.
    """
    weights = dict(TRACKER_WEIGHTS if tracker_weights is None else tracker_weights)
    nets = compute_tracker_nets(df)

    num = pd.Series(0.0, index=df.index)
    den = pd.Series(0.0, index=df.index)

    for tracker_id, tw in weights.items():
        col = f"net_t{tracker_id}"
        if tw <= 0 or col not in nets.columns:
            continue
        present = nets[col].notna()
        num = num.add((nets[col].fillna(0.0) * tw).where(present, 0.0), fill_value=0.0)
        den = den.add(pd.Series(tw, index=df.index).where(present, 0.0), fill_value=0.0)

    composite = num / den.replace(0.0, np.nan)
    composite.name = "composite_sentiment"
    return composite


def enrich_with_sentiment(df):
    """
    Returns a copy of the wide tracker frame with per-tracker nets and the
    composite index appended. This is the canonical feature frame for the
    seat model.
    """
    out = df.copy()
    nets = compute_tracker_nets(out)
    for col in nets.columns:
        out[col] = nets[col]
    out["composite_sentiment"] = compute_composite(out)
    return out


def option_contributions(row):
    """
    Breaks a single day down into per-option contributions to the composite.

    Returns a list of dicts sorted by absolute contribution, which is what the
    dashboard shows to explain *why* the index sits where it does.
    """
    weights = TRACKER_WEIGHTS
    total_tw = sum(
        tw for tid, tw in weights.items()
        if tw > 0 and _tracker_scale(tracker_option_columns(tid, set(row.index))) is not None
    )
    if total_tw <= 0:
        return []

    contributions = []
    for tracker_id, tw in weights.items():
        if tw <= 0:
            continue
        specs = tracker_option_columns(tracker_id, set(row.index))
        scale = _tracker_scale(specs)
        if scale is None:
            continue

        raw_shares = {c: float(row[c]) for c, _, _ in specs if pd.notna(row.get(c))}
        total = sum(raw_shares.values())
        if total <= 0:
            continue

        for col, polarity, weight in specs:
            if col not in raw_shares:
                continue
            share = raw_shares[col] / total * 100.0
            contrib = (share * polarity * weight / scale) * (tw / total_tw)
            contributions.append({
                "tracker_id": tracker_id,
                "tracker_name": TRACKER_SCHEMA[tracker_id]["name"],
                "metric_name": col.split(" - ", 1)[-1],
                "share": round(share, 2),
                "polarity": polarity,
                "weight": weight,
                "contribution": round(float(contrib), 3),
            })

    contributions.sort(key=lambda c: abs(c["contribution"]), reverse=True)
    return contributions


def composite_for_row(row, tracker_weights=None):
    """Composite index for a single row (Series or dict-like)."""
    frame = pd.DataFrame([dict(row)])
    value = compute_composite(frame, tracker_weights=tracker_weights).iloc[0]
    return float(value) if pd.notna(value) else np.nan


if __name__ == "__main__":
    import os

    path = os.path.join(DATA_DIR, "cvoter_daily_trackers.csv")
    df = pd.read_csv(path)
    enriched = enrich_with_sentiment(df)

    print("Composite sentiment index")
    print(enriched[["date", "composite_sentiment"]].describe(include="all"))
    print()
    print(enriched[["date", "composite_sentiment"]].tail(5).to_string(index=False))
    print("\nTop contributions on latest day:")
    for c in option_contributions(df.iloc[-1])[:8]:
        print(f"  {c['contribution']:+7.3f}  {c['share']:5.2f}%  {c['metric_name']}")
