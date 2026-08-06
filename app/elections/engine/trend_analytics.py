"""
trend_analytics.py
------------------
Trend, volatility and momentum statistics for the daily seat projection series.

Everything the dashboard header reports is computed here, so the numbers on the
chart and the numbers in the API can never drift apart:

    current estimate      latest projected seat count
    30-day trend          OLS slope over the last 30 days, in seats/day
    7-day moving average  short-run level, smooths daily survey noise
    30-day moving average long-run level
    trend slope           the same 30-day regression, with R^2 and a t-stat so
                          a flat-but-noisy series is not read as a real trend
    volatility            rolling standard deviation of daily seat changes
    momentum              MA7 - MA30 (direction and strength of the short run
                          against the long run), plus a 14-day rate of change
                          and a volatility-normalised z-score

All rolling windows are calendar-day based on a daily series with no gaps, so
"30-day" and "30-row" coincide.
"""

import numpy as np
import pandas as pd

from app.elections.engine.paths import DATA_DIR

DEFAULT_SHORT_WINDOW = 7
DEFAULT_LONG_WINDOW = 30
DEFAULT_VOL_WINDOW = 30
DEFAULT_ROC_WINDOW = 14


def regression_slope(values, dates=None):
    """
    OLS slope of `values` against day index.

    Returns (slope_per_day, r_squared, t_stat). NaNs are dropped; fewer than
    three usable points yields NaNs rather than a meaningless fit.
    """
    y = pd.Series(values).astype(float).dropna()
    if len(y) < 3:
        return np.nan, np.nan, np.nan

    x = np.arange(len(y), dtype=float)
    y_arr = y.to_numpy()

    slope, intercept = np.polyfit(x, y_arr, 1)
    fitted = slope * x + intercept
    ss_res = float(np.sum((y_arr - fitted) ** 2))
    ss_tot = float(np.sum((y_arr - y_arr.mean()) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan

    n = len(y_arr)
    if n > 2 and ss_res > 0:
        se_slope = np.sqrt((ss_res / (n - 2)) / np.sum((x - x.mean()) ** 2))
        t_stat = float(slope / se_slope) if se_slope > 0 else np.nan
    else:
        t_stat = np.nan

    return float(slope), r_squared, t_stat


def add_rolling_columns(
    df,
    value_col="NDA_proj_seats",
    short_window=DEFAULT_SHORT_WINDOW,
    long_window=DEFAULT_LONG_WINDOW,
    vol_window=DEFAULT_VOL_WINDOW,
    roc_window=DEFAULT_ROC_WINDOW,
    prefix=None,
):
    """
    Appends moving averages, rolling volatility, rolling slope and momentum
    columns for `value_col`. Column names are prefixed with `prefix` (defaults
    to `value_col`) so several series can be enriched in one frame.
    """
    out = df.copy()
    p = prefix if prefix is not None else value_col
    series = out[value_col].astype(float)

    out[f"{p}_ma{short_window}"] = series.rolling(short_window, min_periods=2).mean().round(2)
    out[f"{p}_ma{long_window}"] = series.rolling(long_window, min_periods=3).mean().round(2)

    # Volatility: std of daily changes, i.e. how jumpy the projection is,
    # not how wide the level has wandered.
    daily_change = series.diff()
    out[f"{p}_volatility{vol_window}"] = (
        daily_change.rolling(vol_window, min_periods=5).std().round(3)
    )

    # Rolling 30-day regression slope, in seats/day.
    def _slope(window_values):
        slope, _, _ = regression_slope(window_values)
        return slope

    out[f"{p}_slope{long_window}"] = (
        series.rolling(long_window, min_periods=5).apply(_slope, raw=False).round(4)
    )

    # Momentum: short-run level against long-run level.
    out[f"{p}_momentum"] = (
        out[f"{p}_ma{short_window}"] - out[f"{p}_ma{long_window}"]
    ).round(2)

    # Rate of change over `roc_window` days, in seats.
    out[f"{p}_roc{roc_window}"] = (series - series.shift(roc_window)).round(2)

    # Volatility-normalised momentum. Divides by the rolling std of the level
    # (not of the daily change) so the score answers "is the short-run gap big
    # relative to how much this series normally wanders?".
    level_std = series.rolling(long_window, min_periods=5).std()
    out[f"{p}_momentum_z"] = (
        out[f"{p}_momentum"] / level_std.replace(0.0, np.nan)
    ).round(3)

    return out


def summarize(
    df,
    value_col="NDA_proj_seats",
    short_window=DEFAULT_SHORT_WINDOW,
    long_window=DEFAULT_LONG_WINDOW,
    vol_window=DEFAULT_VOL_WINDOW,
    roc_window=DEFAULT_ROC_WINDOW,
):
    """
    Computes the headline statistics block for the latest day of `df`.

    Returned keys map one-to-one onto the dashboard header tiles.
    """
    series = df[value_col].astype(float).dropna()
    if series.empty:
        return {}

    tail_long = series.tail(long_window)
    tail_short = series.tail(short_window)

    slope, r_squared, t_stat = regression_slope(tail_long)
    daily_change = series.diff().dropna()
    volatility = float(daily_change.tail(vol_window).std()) if len(daily_change) >= 2 else np.nan

    ma_short = float(tail_short.mean())
    ma_long = float(tail_long.mean())
    momentum = ma_short - ma_long
    level_std = float(tail_long.std()) if len(tail_long) > 1 else np.nan
    momentum_z = momentum / level_std if level_std and level_std > 0 else np.nan

    roc = (
        float(series.iloc[-1] - series.iloc[-1 - roc_window])
        if len(series) > roc_window else np.nan
    )

    # A trend is only called when the regression is both non-trivial in size
    # and statistically distinguishable from flat.
    if np.isnan(slope) or np.isnan(t_stat):
        direction = "insufficient data"
    elif abs(t_stat) < 2.0 or abs(slope) < 0.01:
        direction = "flat"
    elif slope > 0:
        direction = "rising"
    else:
        direction = "falling"

    def clean(x):
        return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 4)

    return {
        "series": value_col,
        "as_of_date": str(df["date"].iloc[-1]) if "date" in df.columns else None,
        "current_estimate": int(round(series.iloc[-1])),
        "previous_estimate": int(round(series.iloc[-2])) if len(series) > 1 else None,
        "day_change": clean(series.iloc[-1] - series.iloc[-2]) if len(series) > 1 else None,
        f"ma_{short_window}d": clean(ma_short),
        f"ma_{long_window}d": clean(ma_long),
        "trend_slope_per_day": clean(slope),
        "trend_slope_r2": clean(r_squared),
        "trend_slope_t_stat": clean(t_stat),
        "trend_direction": direction,
        f"trend_{long_window}d_total": clean(slope * long_window) if not np.isnan(slope) else None,
        "volatility": clean(volatility),
        "momentum": clean(momentum),
        "momentum_z": clean(momentum_z),
        f"roc_{roc_window}d": clean(roc),
        "window_high": int(round(tail_long.max())),
        "window_low": int(round(tail_long.min())),
        "history_days": int(len(series)),
    }


def build_analytics(df, series_cols=("NDA_proj_seats", "INDIA_proj_seats"), **kwargs):
    """
    Enriches `df` with rolling columns for each series and returns
    (enriched_df, {series_col: summary_dict}).
    """
    enriched = df.copy()
    summaries = {}
    for col in series_cols:
        if col not in enriched.columns:
            continue
        enriched = add_rolling_columns(enriched, value_col=col, **kwargs)
        summaries[col] = summarize(enriched, value_col=col, **kwargs)
    return enriched, summaries


if __name__ == "__main__":
    import os

    projections = pd.read_csv(os.path.join(DATA_DIR, "ideal_model_daily_projections.csv"))
    _, summaries = build_analytics(projections)
    for col, summary in summaries.items():
        print(f"\n{col}")
        for key, value in summary.items():
            print(f"  {key:<24} {value}")
