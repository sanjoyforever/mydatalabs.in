#!/usr/bin/env python3
"""Rebuild app/data/democracy_history.json from app/data/democracy_anchors.json.

What the anchors file is
------------------------
Twelve indicators for thirty economies over 2000-2024 is 9,000 cells. Nobody
keyed 9,000 cells. What was actually keyed is 1,574 anchor points — a value
attached to a year for which a real source exists (an election result, an IPU
Parline snapshot, a World Prison Brief report, a World Bank PIP release, a CPJ
census) — plus 89 series asserted flat across the whole period. Everything
between two anchors is straight-line interpolation, and everything outside the
outermost anchors is held flat.

That is a legitimate way to carry an annual panel built from sources that do
not publish annually. It is not the same thing as measurement, and the
difference has to survive into the published artifact rather than being
flattened into a table of numbers that all look equally solid. So this script
writes an `anchor` flag alongside every value, and app/indices/democracy.py
carries the per-country, per-year anchor share through to the page, where the
methodology tab reports it.

Anchors are the input of record. Editing a figure means editing the anchors
file and re-running this; the history file is generated and should never be
hand-edited.

    python scripts/build_democracy_history.py

Run locally and commit the result. Nothing here is needed to serve a request.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DATA_DIR = os.path.join(ROOT, "app", "data")
ANCHORS_JSON = os.path.join(DATA_DIR, "democracy_anchors.json")
HISTORY_JSON = os.path.join(DATA_DIR, "democracy_history.json")

YEARS = list(range(2000, 2025))


def interpolate(points: dict[str, float]) -> tuple[list[float], set[int]]:
    """Linear interpolation across YEARS, flat-held outside the anchor range.

    Returns the series and the set of years that are anchors rather than
    fill. Implemented here rather than with numpy.interp so the only thing
    standing between the anchors file and the published series is arithmetic
    anyone can check by hand.
    """
    anchor_years = sorted(int(y) for y in points)
    vals = [float(points[str(y)]) for y in anchor_years]

    series = []
    for year in YEARS:
        if year <= anchor_years[0]:
            series.append(vals[0])
            continue
        if year >= anchor_years[-1]:
            series.append(vals[-1])
            continue
        # Bracket the year between the two anchors either side of it.
        hi = next(i for i, ay in enumerate(anchor_years) if ay >= year)
        lo = hi - 1
        y0, y1 = anchor_years[lo], anchor_years[hi]
        v0, v1 = vals[lo], vals[hi]
        span = y1 - y0
        series.append(v0 if span == 0 else v0 + (v1 - v0) * (year - y0) / span)

    return series, set(anchor_years)


def build() -> dict:
    with open(ANCHORS_JSON, encoding="utf-8") as fh:
        anchors = json.load(fh)

    records = []
    anchor_cells = 0
    total_cells = 0

    for code, metrics in anchors.items():
        series_by_metric: dict[str, list[float]] = {}
        anchor_years_by_metric: dict[str, set[int]] = {}

        for metric, spec in metrics.items():
            kind = spec["kind"]
            if kind == "anchors":
                series, anchor_years = interpolate(spec["points"])
            elif kind == "constant":
                # A series asserted unchanged for 25 years. The assertion is
                # itself a claim about one value, so exactly one year counts as
                # anchored: pretending all 25 are measured would be the
                # opposite of what the flag is for.
                series = [float(spec["value"])] * len(YEARS)
                anchor_years = {YEARS[0]}
            else:
                series = [float(v) for v in spec["values"]]
                anchor_years = set(YEARS)

            series_by_metric[metric] = series
            anchor_years_by_metric[metric] = anchor_years

        for i, year in enumerate(YEARS):
            row = {"country_code": code, "year": year}
            anchored = []
            for metric, series in series_by_metric.items():
                row[metric] = round(series[i], 2)
                total_cells += 1
                if year in anchor_years_by_metric[metric]:
                    anchored.append(metric)
                    anchor_cells += 1
            # Which of this row's figures sit on a source rather than between
            # two of them. The dashboard shades interpolated spans from this.
            row["anchored"] = sorted(anchored)
            records.append(row)

    return {
        "generated_at": date.today().isoformat(),
        "years": YEARS,
        "provenance": {
            "anchor_cells": anchor_cells,
            "total_cells": total_cells,
            "anchor_share": round(anchor_cells / total_cells, 4) if total_cells else 0.0,
        },
        "records": records,
    }


def main() -> int:
    payload = build()
    with open(HISTORY_JSON, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)

    prov = payload["provenance"]
    print(f"wrote {HISTORY_JSON}")
    print(f"  {len(payload['records'])} country-years, {payload['years'][0]}-{payload['years'][-1]}")
    print(
        f"  {prov['anchor_cells']} of {prov['total_cells']} cells sit on a source "
        f"({prov['anchor_share'] * 100:.1f}%); the rest is interpolated or held flat"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
