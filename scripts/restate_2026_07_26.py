#!/usr/bin/env python
"""Methodology revision 2026-07-26 — units and cap correction, two components.

Run-once audit artifact. It reproduces the whole revision from the pre-revision
history file, so the published series can be independently rebuilt and checked.

    python scripts/restate_2026_07_26.py [path/to/pre_revision_history.json]


1. SHIP TRAFFIC
---------------
Published baseline was 34 "transits/wk". No measure of Hormuz traffic is near
that. IMF PortWatch puts peacetime throughput at ~88 commercial vessels per DAY
(~616/wk); tanker-only counts run ~21/day (~147/wk). The 34 was a daily tanker
figure mislabelled as a weekly all-vessel one — wrong by ~18x.

Scale alone would have cancelled out: stress is a percentage change from
baseline, so consistently wrong units are harmless. The ratio was also wrong.
The old series showed a 26.5% decline; PortWatch's published day 2026-07-19
recorded 15 vessels against the 88/day baseline — an 83% decline.

    baseline  34 -> 616 transits/wk   (88/day x 7, PortWatch reference window
                                       2025-02-28 to 2026-02-27)
    latest    25 -> 105 transits/wk   (15/day, PortWatch published 2026-07-19)
    cap      -50% -> -90%


2. WAR-RISK INSURANCE
---------------------
Published baseline was 0.10% of hull value and the latest reading 0.45%, i.e.
4.5x baseline. Reported rates are an order of magnitude higher: pre-war premiums
ran ~0.25% of hull value, and by 22 July 2026 Marsh put Hormuz additional war
risk at 7.5-10% of hull — 30-40x baseline, not 4.5x.

    baseline  0.10% -> 0.25% hull     (pre-war rate, The National 2026-07-17)
    latest    0.45% -> 7.50% hull     (Marsh, low end of 7.5-10%, 2026-07-22)
    cap      +400% -> +3900%          (40x baseline = 10% hull, the observed
                                       conflict peak)

The +400% cap was the same defect as ship traffic's -50%: a 5x reading and a
40x reading both scored 100, so the component saturated long before the crisis
peaked and could not rank severity within the crisis at all.


HOW THE HISTORY IS RESTATED
---------------------------
Neither weekly series was ever observed. Rather than discard trajectories the
event log and ceasefire annotations both reference, each week is re-expressed as
a fraction (or multiple) of baseline and mapped through a monotone power
transform pinned to real observations:

    new_ratio = old_ratio ** k        k chosen so one known point maps exactly

  - Ship traffic is anchored on its LATEST value (both endpoints then observed).
  - War risk is anchored on its PEAK (old 6.2x -> 40x = 10% hull, the reported
    conflict peak). The current week then falls out at ~5.2% hull, which
    independently reproduces the "around 5 percent" reported by Xinhua on
    2026-07-10 — a useful check that was not fitted for. The final week is then
    set to the directly observed Marsh figure.

Ordering and relative shape are preserved; intermediate weeks remain a
RECONSTRUCTION, flagged in the data file and the API. Replacing them with real
weekly series needs new values, not new code.

Every weekly composite is recomputed from its raw values afterwards.
"""
from __future__ import annotations

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.indices import hormuz  # noqa: E402
from app.scoring import compute_composite  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_PATH = os.path.join(ROOT, "app", "data", "hormuz_history.json")

# --- Anchors, all sourced ---------------------------------------------------

SHIP = {
    "key": "ship_traffic",
    "old_baseline": 34.0,
    "new_baseline": 616.0,
    "anchor": "latest",
    "anchor_new": 105.0,
    "observed_latest": 105.0,
    "latest_observed_on": "2026-07-19",
    "decimals": 0,
}

WAR = {
    "key": "war_risk",
    "old_baseline": 0.10,
    "new_baseline": 0.25,
    "anchor": "peak",
    "anchor_new": 10.0,        # 40x baseline — reported conflict peak
    "observed_latest": 7.50,   # Marsh, low end of 7.5-10% on 2026-07-22
    "latest_observed_on": "2026-07-22",
    "decimals": 2,
}

SOURCE_NOTES = {
    "ship_traffic": (
        "Baseline 616 transits/wk = 88 commercial vessels/day (IMF PortWatch chokepoint "
        "dataset, fixed reference window 2025-02-28 to 2026-02-27). Latest observation "
        "105 transits/wk = 15 vessels/day (PortWatch published day 2026-07-19, 17% of "
        "baseline). Intermediate weeks are reconstructed, not observed."
    ),
    "war_risk": (
        "Baseline 0.25% of hull value = pre-war Hormuz rate (The National, 2026-07-17). "
        "Latest observation 7.5% of hull, the low end of the 7.5-10% range quoted by "
        "Marcus Baker, global head of marine at Marsh, for 2026-07-22. Series anchored on "
        "the reported conflict peak of 10% of hull. Intermediate weeks are reconstructed, "
        "not observed."
    ),
}


def restate(weeks: list[dict], spec: dict) -> float:
    """Re-anchor one component's series in place. Returns the exponent used."""
    key = spec["key"]
    old_base, new_base = spec["old_baseline"], spec["new_baseline"]
    values = [float(w["raw_values"][key]) for w in weeks]

    if spec["anchor"] == "latest":
        old_ratio = values[-1] / old_base
    else:  # peak — the largest deviation from baseline in the published series
        old_ratio = max(values, key=lambda v: abs(math.log(v / old_base) or 0.0)) / old_base

    new_ratio = spec["anchor_new"] / new_base
    k = math.log(new_ratio) / math.log(old_ratio)

    for week, old_value in zip(weeks, values):
        ratio = (old_value / old_base) ** k
        week["raw_values"][key] = round(new_base * ratio, spec["decimals"]) if spec["decimals"] \
            else round(new_base * ratio)

    # The final week is a directly observed reading, not a reconstruction.
    week_last = weeks[-1]["raw_values"]
    week_last[key] = round(spec["observed_latest"], spec["decimals"]) if spec["decimals"] \
        else round(spec["observed_latest"])
    return k


def main() -> int:
    source = sys.argv[1] if len(sys.argv) > 1 else HISTORY_PATH
    with open(source, "r", encoding="utf-8") as f:
        history = json.load(f)
    weeks = history["weeks"]

    print(f"Reading pre-revision history from {source}\n")

    before = [(w["week_start"], w["score"], w["level_label"]) for w in weeks]

    for spec in (SHIP, WAR):
        k = restate(weeks, spec)
        print(f"{spec['key']:<14} baseline {spec['old_baseline']:>8} -> {spec['new_baseline']:<8}"
              f" anchor={spec['anchor']:<6} k={k:.4f}")

    print(f"\n{'week':<12} {'transits':>9} {'war risk':>9} {'before':>8} {'after':>8}  level")
    for week, (_, old_score, old_level) in zip(weeks, before):
        raw = week["raw_values"]
        result = compute_composite(
            components=hormuz.COMPONENTS,
            current_values=raw,
            baseline_values=hormuz.BASELINE_VALUES,
            week_start=week["week_start"],
        )
        week["score"] = result.score
        week["level_label"] = result.level_label
        week["level_status"] = result.level_status
        flag = "" if old_level == result.level_label else f"  <- was {old_level}"
        print(f"{week['week_start']:<12} {raw['ship_traffic']:>9} {raw['war_risk']:>9.2f}"
              f" {old_score:>8.1f} {result.score:>8.1f}  {result.level_label}{flag}")

    history["manual_overrides"]["ship_traffic"] = int(SHIP["observed_latest"])
    history["manual_overrides"]["war_risk"] = WAR["observed_latest"]
    history["manual_updated"]["ship_traffic"] = SHIP["latest_observed_on"]
    history["manual_updated"]["war_risk"] = WAR["latest_observed_on"]
    history["reconstructed_series"] = ["ship_traffic", "war_risk"]
    history["series_source_notes"] = SOURCE_NOTES
    history.pop("ship_traffic_reconstructed", None)
    history.pop("ship_traffic_source_note", None)

    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

    changed = sum(1 for w, (_, s, _) in zip(weeks, before) if w["score"] != s)
    relabelled = sum(1 for w, (_, _, lv) in zip(weeks, before) if w["level_label"] != lv)
    print(f"\n{changed}/{len(weeks)} scores changed, {relabelled} reclassified")
    print(f"Written to {HISTORY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
