#!/usr/bin/env python3
"""Fetch the V-Dem Liberal Democracy Index for the HMDI panel, 2000-2024.

The Hard-Metric Democracy Index scores nothing but published counts, so V-Dem
is not an input to it and never will be. It is carried as an *external
comparator*: the reader is entitled to see where a hard-count ranking parts
company with the expert-coded ranking everyone else cites, and that is only
visible if both sit in the same table.

Source: V-Dem v15 `v2x_libdem` (liberal democracy index, best estimate, 0-1),
served as a country-year CSV by Our World in Data, which republishes the V-Dem
release unmodified.

    python scripts/build_vdem_reference.py             # fetch and write
    python scripts/build_vdem_reference.py --dry-run   # print, write nothing

Only the thirty panel countries and the panel's year span are kept. The rank
column the page shows is a rank *within these thirty*, computed at read time in
app/indices/democracy.py -- V-Dem's own global rank over 179 countries would
not be comparable to a 30-country HMDI rank.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "app", "data", "vdem_libdem.json")

SOURCE_URL = (
    "https://ourworldindata.org/grapher/liberal-democracy-index.csv"
    "?csvType=full&useColumnShortNames=true"
)
VALUE_COLUMN = "libdem_vdem__estimate_best"

YEAR_MIN, YEAR_MAX = 2000, 2024


def panel_codes() -> list[str]:
    import sys
    sys.path.insert(0, ROOT)
    from app.indices import democracy
    return [c["code"] for c in democracy.COUNTRIES]


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "mydatalabs/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read().decode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    codes = set(panel_codes())
    values: dict[str, dict[str, float]] = {}
    for row in csv.DictReader(io.StringIO(fetch(SOURCE_URL))):
        code = row.get("code")
        if code not in codes:
            continue
        year = int(row["year"])
        if not (YEAR_MIN <= year <= YEAR_MAX):
            continue
        raw = row.get(VALUE_COLUMN)
        if raw in (None, ""):
            continue
        values.setdefault(code, {})[str(year)] = round(float(raw), 3)

    missing = sorted(codes - set(values))
    if missing:
        raise SystemExit(f"no V-Dem series for: {', '.join(missing)}")
    thin = {c: len(v) for c, v in values.items() if len(v) != YEAR_MAX - YEAR_MIN + 1}
    if thin:
        raise SystemExit(f"incomplete year coverage: {thin}")

    payload = {
        "indicator": "v2x_libdem",
        "label": "V-Dem Liberal Democracy Index",
        "scale": "0-1, higher is more liberal-democratic",
        "release": "V-Dem v15 (data through 2024)",
        "source": "Varieties of Democracy project, via Our World in Data",
        "source_url": SOURCE_URL,
        "years": list(range(YEAR_MIN, YEAR_MAX + 1)),
        "values": {c: values[c] for c in sorted(values)},
    }

    text = json.dumps(payload, indent=1, sort_keys=False) + "\n"
    if args.dry_run:
        print(text[:2000])
        return 0
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote {OUT}: {len(values)} countries x {len(payload['years'])} years")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
