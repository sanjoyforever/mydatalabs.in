"""Run locally each week to fetch live values, merge manual entries, and
append this week's snapshot to app/data/hormuz_history.json.

Usage:
    python scripts/update_hormuz.py

Before running, edit the "manual_overrides" block in
app/data/hormuz_history.json with this week's ship traffic, war-risk
insurance, tanker freight, and reroute figures (see README for sourcing).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.indices import hormuz

if __name__ == "__main__":
    result = hormuz.compute_snapshot(persist=True)
    print(f"Week of {result.week_start}: score={result.score} ({result.level_label})")
    for cr in result.components:
        flag = " [manual]" if cr.stale else ""
        print(f"  {cr.component.label:<28} current={cr.current_value!s:<10} stress={cr.stress:5.1f}{flag}")
