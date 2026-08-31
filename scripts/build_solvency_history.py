#!/usr/bin/env python3
"""Rebuild the U.S. Sovereign Solvency Index annual history from primary sources.

Every number in app/data/solvency_history.json is fetched here from FRED's
public CSV endpoint (no API key required) and derived by explicit arithmetic.
Nothing is hand-keyed and nothing is estimated: if a series does not cover a
year, that year's component is null and the composite is computed on the
remaining weight rather than on a filled-in guess.

    python scripts/build_solvency_history.py            # fetch, derive, write
    python scripts/build_solvency_history.py --dry-run  # print, write nothing

Source series (all FRED IDs, all free):

    GDPPOT        Real Potential GDP (CBO)             $B ch., Q,  1949-
    GDPC1         Real GDP                             $B ch., Q,  1947-
    USREC         NBER Recession Indicator              0/1,  M,  1854-
    A824RE1A156NBEA  National Defense Consumption, % of GDP  %, A,  1929-
    FYGFDPUB      Federal Debt Held by the Public          $B, FY, 1939-
    FYGFD         Gross Federal Debt                       $M, FY, 1939-
    FYPUGDA188S   Federal Debt Held by Public, % of GDP     %, FY, 1939-
    FYFR          Federal Receipts                         $M, FY, 1901-
    FYOINT        Federal Outlays: Interest                $M, FY, 1940-
    FYFSD         Federal Surplus or Deficit               $M, FY, 1901-
    GDPA          Gross Domestic Product                   $B, CY, 1929-
    CPIAUCNS      CPI-U, All Items, NSA                 index, M,  1913-
    OPHNFB        Nonfarm Business Labor Productivity   index, Q,  1947-
    A939RX0Q048SBEA  Real GDP per capita                    $, Q,  1947-

Fiscal-year series are keyed by the year in their observation date. Monthly and
quarterly series are averaged to the calendar year. The two are then joined on
the year, which is the standard convention for annual fiscal ratios and is
accurate to the ~3-month FY/CY offset.
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import os
import sys
import urllib.request
from datetime import date, timezone, datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

OUT_PATH = os.path.join(ROOT_DIR, "app", "data", "solvency_history.json")

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"

# The first year every fiscal series is populated. 1945 is also where the
# narrative starts, so the series needs no truncation.
START_YEAR = 1945

SERIES = [
    "FYGFDPUB",
    "FYGFD",
    "FYPUGDA188S",
    "FYFR",
    "FYOINT",
    "FYFSD",
    "GDPA",
    "CPIAUCNS",
    "OPHNFB",
    "A939RX0Q048SBEA",
    # Cycle context. Not scored — the index is deliberately a level measure, not
    # a cyclically adjusted one — but the presidential panel needs a *computed*
    # output gap to estimate the cyclical component of a term's index change,
    # rather than assigning one by hand.
    "GDPPOT",
    "GDPC1",
    "USREC",
    # National defense outlays as a share of GDP. Not scored either: wars enter
    # the index through the deficit and debt they produce, not as a separate
    # term. This series is what lets the war panel show that burden directly.
    "A824RE1A156NBEA",
]


def fetch_series(series_id: str, timeout: int = 60) -> dict[str, float]:
    """Pull one FRED series as {observation_date: value}, skipping '.' gaps."""
    url = FRED_CSV.format(series_id)
    raw = urllib.request.urlopen(url, timeout=timeout).read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(raw))
    out: dict[str, float] = {}
    for row in reader:
        obs = row.get("observation_date")
        # FRED names the value column after the series, but has changed the
        # header casing before; fall back to "the other column".
        value = row.get(series_id)
        if value is None:
            others = [k for k in row if k != "observation_date"]
            value = row[others[0]] if others else None
        if not obs or value in (".", "", None):
            continue
        out[obs] = float(value)
    return out


def fetch_all() -> dict[str, dict[str, float]]:
    import concurrent.futures as cf

    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        return dict(zip(SERIES, pool.map(fetch_series, SERIES)))


def by_fiscal_year(obs: dict[str, float]) -> dict[int, float]:
    """Fiscal-year series: key on the year of the observation date."""
    return {int(k[:4]): v for k, v in obs.items()}


def by_calendar_mean(obs: dict[str, float]) -> dict[int, float]:
    """Monthly/quarterly series: mean of every observation in the year."""
    buckets: dict[int, list[float]] = collections.defaultdict(list)
    for k, v in obs.items():
        buckets[int(k[:4])].append(v)
    return {y: sum(vals) / len(vals) for y, vals in buckets.items()}


def cagr(series: dict[int, float], year: int, span: int) -> float | None:
    """Compound annual growth rate over `span` years ending at `year`, in %."""
    a, b = series.get(year - span), series.get(year)
    if a is None or b is None or a <= 0 or b <= 0:
        return None
    return ((b / a) ** (1.0 / span) - 1.0) * 100.0


def build_rows(S: dict[str, dict[str, float]]) -> list[dict]:
    debt_pub_bn = by_fiscal_year(S["FYGFDPUB"])          # $ billions
    gross_debt_mn = by_fiscal_year(S["FYGFD"])           # $ millions
    debt_pct_gdp = by_fiscal_year(S["FYPUGDA188S"])      # already %
    receipts_mn = by_fiscal_year(S["FYFR"])              # $ millions
    interest_mn = by_fiscal_year(S["FYOINT"])            # $ millions
    surplus_mn = by_fiscal_year(S["FYFSD"])              # $ millions, deficit < 0
    gdp_mn = {y: v * 1000.0 for y, v in by_fiscal_year(S["GDPA"]).items()}  # $B -> $M

    cpi = by_calendar_mean(S["CPIAUCNS"])
    potential = by_calendar_mean(S["GDPPOT"])
    real_gdp = by_calendar_mean(S["GDPC1"])
    recession = by_calendar_mean(S["USREC"])  # fraction of months in recession
    defense = by_calendar_mean(S["A824RE1A156NBEA"])
    prod = by_calendar_mean(S["OPHNFB"])
    rgdp_pc = by_calendar_mean(S["A939RX0Q048SBEA"])

    last_year = max(y for y in debt_pct_gdp if y in receipts_mn and y in interest_mn)

    rows: list[dict] = []
    for year in range(START_YEAR, last_year + 1):
        gdp = gdp_mn.get(year)
        receipts = receipts_mn.get(year)
        interest = interest_mn.get(year)
        surplus = surplus_mn.get(year)

        # 1. Debt held by the public as % of GDP — published directly by OMB.
        debt_gdp = debt_pct_gdp.get(year)

        # 2. Net interest as % of federal receipts. This is the ratio rating
        #    agencies actually watch, and the one the insolvency tripwire uses.
        interest_burden = (interest / receipts * 100.0) if receipts and interest is not None else None

        # 3. Primary deficit as % of GDP: the deficit excluding interest, i.e.
        #    the part of the gap that policy sets rather than inherits. Sign is
        #    flipped so positive = deficit.
        primary_deficit = None
        if gdp and surplus is not None and interest is not None:
            primary_deficit = -(surplus + interest) / gdp * 100.0

        # 4/5. Growth block: 10-year CAGRs. A 5-year window ending in 2025 starts
        #      at the 2020 trough and reports a per-capita rate of 2.7% against a
        #      true trend of 1.8%; ten years is long enough that no single cycle
        #      trough sets the reading. Cost: both series start in 1957, so
        #      1945-1956 scores on the fiscal and monetary blocks renormalised.
        productivity = cagr(prod, year, 10)
        real_gdp_pc = cagr(rgdp_pc, year, 10)

        # 6. CPI-U inflation, year over year.
        inflation = None
        if year in cpi and year - 1 in cpi:
            inflation = (cpi[year] / cpi[year - 1] - 1.0) * 100.0

        # 7. r - g, the term that decides whether debt compounds or erodes.
        #    r is the *effective* nominal rate actually paid — interest outlays
        #    over last year's debt stock — not a market quote, so it needs no
        #    splicing across the 1953 start of the 10-year series.
        r_eff = None
        prev_debt_bn = debt_pub_bn.get(year - 1)
        if interest is not None and prev_debt_bn:
            r_eff = interest / (prev_debt_bn * 1000.0) * 100.0  # $M / ($B -> $M)
        g_nom = None
        if year in gdp_mn and year - 1 in gdp_mn and gdp_mn[year - 1]:
            g_nom = (gdp_mn[year] / gdp_mn[year - 1] - 1.0) * 100.0
        r_minus_g = (r_eff - g_nom) if (r_eff is not None and g_nom is not None) else None

        rows.append(
            {
                "year": year,
                "raw_values": {
                    "debt_gdp": _r(debt_gdp, 2),
                    "interest_burden": _r(interest_burden, 2),
                    "primary_deficit": _r(primary_deficit, 2),
                    "productivity": _r(productivity, 2),
                    "real_gdp_pc": _r(real_gdp_pc, 2),
                    "inflation": _r(inflation, 2),
                    "r_minus_g": _r(r_minus_g, 2),
                },
                "context": {
                    # Output gap: actual real GDP against CBO potential. Used only
                    # by the presidential panel's cyclical estimator.
                    "output_gap": _r(
                        (real_gdp[year] - potential[year]) / potential[year] * 100.0, 2
                    ) if year in real_gdp and potential.get(year) else None,
                    "recession_share": _r(recession.get(year), 3),
                    "defense_pct_gdp": _r(defense.get(year), 2),
                    # Carried so downstream panels can express debt in dollars
                    # and in constant purchasing power without re-deriving GDP
                    # from a ratio.
                    "gdp_bn": _r(gdp / 1000.0, 1) if gdp else None,
                    "cpi_index": _r(cpi.get(year), 3),
                    "gross_debt_pct_gdp": _r(gross_debt_mn[year] / gdp * 100.0, 2)
                    if gdp and year in gross_debt_mn
                    else None,
                    "receipts_pct_gdp": _r(receipts / gdp * 100.0, 2) if gdp and receipts else None,
                    "effective_rate": _r(r_eff, 2),
                    "nominal_gdp_growth": _r(g_nom, 2),
                    "interest_outlays_bn": _r(interest / 1000.0, 1) if interest is not None else None,
                    "receipts_bn": _r(receipts / 1000.0, 1) if receipts else None,
                    "debt_public_bn": _r(debt_pub_bn.get(year), 1),
                },
            }
        )
    return rows


def _r(v, places):
    return round(v, places) if v is not None else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print a summary, write nothing")
    args = ap.parse_args()

    print("Fetching %d series from FRED..." % len(SERIES))
    S = fetch_all()
    for sid in SERIES:
        print("  %-18s %d observations" % (sid, len(S[sid])))

    rows = build_rows(S)
    print("\nDerived %d annual rows: %d-%d" % (len(rows), rows[0]["year"], rows[-1]["year"]))

    from app.indices import solvency

    scored = solvency.score_history(rows)

    print("\n%-6s %8s %8s %8s %8s %8s %8s %8s   %s" % (
        "year", "debt%", "int/rec", "primdef", "prod5y", "gdppc5y", "cpi%", "r-g", "INDEX"))
    for row in scored:
        if row["year"] % 5 == 0 or row["year"] >= scored[-1]["year"] - 4:
            rv = row["raw_values"]
            fmt = lambda k: ("%8.2f" % rv[k]) if rv[k] is not None else "       ."
            print("%-6d %s %s %s %s %s %s %s   %6.1f  %s" % (
                row["year"], fmt("debt_gdp"), fmt("interest_burden"), fmt("primary_deficit"),
                fmt("productivity"), fmt("real_gdp_pc"), fmt("inflation"), fmt("r_minus_g"),
                row["score"], row["level_label"]))

    payload = {
        "index": "USS-INDEX",
        "name": "U.S. Sovereign Solvency Index",
        "baseline": 100.0,
        "frequency": "annual",
        "source": "Federal Reserve Economic Data (FRED), St. Louis Fed",
        "source_series": SERIES,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "history": scored,
    }

    if args.dry_run:
        print("\n--dry-run: not writing %s" % OUT_PATH)
        return 0

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print("\nWrote %s (%d rows, %.0f KB)" % (
        OUT_PATH, len(scored), os.path.getsize(OUT_PATH) / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
