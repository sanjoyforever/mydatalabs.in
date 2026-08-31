"""U.S. Sovereign Solvency Index (USS-INDEX): components, scoring, projection.

Baseline: a sustainable peacetime fiscal equilibrium (composite = 100.0),
calibrated on the 1960-2000 United States rather than on the sample mean.

Blocks and weights follow the conventional 50/30/20 split between what the
budget does, what the economy earns, and what the money costs:

    Fiscal & Solvency    50%   debt/GDP, interest burden, primary deficit
    Growth & Capacity    30%   labour productivity, real GDP per capita
    Monetary & Cost      20%   CPI inflation, r - g

Why fixed baselines rather than z-scores
----------------------------------------
The obvious alternative is to normalise each indicator against its own
1945-2025 mean and standard deviation and push it through a normal CDF. That
has two defects this index deliberately avoids.

First, it is computed in-sample: every historical value silently restates when
a new year arrives, and the index is centred on ~50 by construction, so it can
only ever say "worse than the post-war average" and never "bad in absolute
terms". Second, a CDF saturates. Once an indicator sits two standard deviations
out, the transform is flat — the index becomes least sensitive exactly where
risk is accelerating, which for a solvency measure is backwards.

Scoring each indicator linearly between a fixed baseline and a fixed, argued
crisis threshold keeps the scale absolute, keeps history immutable, and keeps
the response linear right up to the cap. It is also what every other index on
this site already does (see app/scoring.py).

Data
----
Every input is derived from published FRED series by scripts/build_solvency_
history.py, which writes app/data/solvency_history.json. Nothing in this module
estimates, interpolates or hand-keys a figure. A year whose indicator is
missing scores on the remaining weight, renormalised, and is marked partial.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, timezone
from typing import Optional

from app.scoring import Component, ComponentResult, CompositeResult

INDEX_KEY = "solvency"
DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "solvency_history.json"
)

# --- Blocks ----------------------------------------------------------------

BLOCKS = [
    {"key": "fiscal", "label": "Fiscal & Solvency", "weight": 0.50, "color": "#EF4444"},
    {"key": "growth", "label": "Growth & Capacity", "weight": 0.30, "color": "#10B981"},
    {"key": "monetary", "label": "Monetary & Cost", "weight": 0.20, "color": "#A855F7"},
]

COMPONENT_BLOCK = {
    "debt_gdp": "fiscal",
    "interest_burden": "fiscal",
    "primary_deficit": "fiscal",
    "productivity": "growth",
    "real_gdp_pc": "growth",
    "inflation": "monetary",
    "r_minus_g": "monetary",
}

# --- Component definitions -------------------------------------------------

COMPONENTS: list[Component] = [
    Component(
        key="debt_gdp",
        label="Federal Debt Held by the Public",
        weight=0.18,
        source="OMB / FRED FYPUGDA188S",
        cap_pct=328.6,  # 35% baseline -> 150% crisis
        unit="% GDP",
        cap_rationale=(
            "150% of GDP is the level at which every advanced-economy sovereign that has reached it "
            "outside a world war has required either sustained financial repression, an inflation "
            "surprise, or a restructuring. It is a threshold of policy options exhausted, not of default."
        ),
        update_cadence="Annual (automatic, FY close)",
    ),
    Component(
        key="interest_burden",
        label="Net Interest / Federal Receipts",
        weight=0.17,
        source="U.S. Treasury MTS / FRED FYOINT, FYFR",
        cap_pct=275.0,  # 8% baseline -> 30% crisis
        unit="% receipts",
        cap_rationale=(
            "30% of receipts consumed by debt service is the empirical distress zone for rated "
            "sovereigns: past it, interest crowds out the discretionary budget faster than any "
            "plausible growth rate refills it. This is the ratio the agencies downgrade on."
        ),
        update_cadence="Annual (automatic, FY close)",
    ),
    Component(
        key="primary_deficit",
        label="Primary Deficit (ex-Interest)",
        weight=0.15,
        source="OMB / FRED FYFSD, FYOINT, GDPA",
        cap_pct=8.0,  # 0% baseline (primary balance) -> 8% crisis
        unit="% GDP",
        cap_rationale=(
            "An 8%-of-GDP primary deficit is the sustained wartime/emergency maximum (1945, 2009, "
            "2020). Excluding interest isolates the gap current policy is choosing to run from the "
            "gap inherited from past borrowing."
        ),
        update_cadence="Annual (automatic, FY close)",
    ),
    Component(
        key="productivity",
        label="Labour Productivity Growth (10y)",
        weight=0.15,
        source="BLS / FRED OPHNFB",
        cap_pct=100.0,  # 2.1% baseline -> 0.0% crisis
        invert=True,
        unit="% CAGR",
        cap_rationale=(
            "Zero productivity growth removes the only mechanism that retires debt without either "
            "austerity or inflation. The 2.1% baseline is the measured 1960-2000 mean; the "
            "10-year window keeps any single cycle trough out of a structural measure."
        ),
        update_cadence="Annual (automatic)",
    ),
    Component(
        key="real_gdp_pc",
        label="Real GDP per Capita Growth (10y)",
        weight=0.15,
        source="BEA / FRED A939RX0Q048SBEA",
        cap_pct=100.0,  # 2.2% baseline -> 0.0% crisis
        invert=True,
        unit="% CAGR",
        cap_rationale=(
            "Per-capita real growth is the denominator of every debt ratio and the tax base behind "
            "every projection. Stagnation at 0% is the demographic-drag scenario in which the debt "
            "path stops being self-correcting."
        ),
        update_cadence="Annual (automatic)",
    ),
    Component(
        key="inflation",
        label="CPI-U Inflation",
        weight=0.10,
        source="BLS / FRED CPIAUCNS",
        cap_pct=400.0,  # 2.0% baseline -> 10.0% crisis
        unit="% YoY",
        cap_rationale=(
            "10% inflation is the threshold at which the nominal-erosion channel stops being a "
            "quiet subsidy to the borrower and starts repricing the entire debt stock upward through "
            "the term premium — the 1979-81 mechanism."
        ),
        update_cadence="Annual (automatic)",
    ),
    Component(
        key="r_minus_g",
        label="Borrowing Cost less Growth (r − g)",
        weight=0.10,
        source="Derived: FRED FYOINT / FYGFDPUB vs GDPA",
        cap_pct=3.0,  # -1.0pp baseline -> +3.0pp crisis
        unit="pp",
        cap_rationale=(
            "r − g is the sign of the debt-dynamics equation: below zero debt ratios fall on their "
            "own, above zero they compound. +3pp sustained is the Eurozone-periphery crisis range. "
            "r is the effective rate actually paid on the stock, not a market quote."
        ),
        update_cadence="Annual (automatic)",
    ),
]

COMPONENTS_BY_KEY = {c.key: c for c in COMPONENTS}

# Each indicator is scored linearly from `baseline` (0 stress) to `crisis`
# (100 stress) and clamped to that range. Where crisis < baseline the indicator
# is inverted — falling productivity is the stress direction — and the same
# formula handles it without a special case.
BANDS: dict[str, tuple[float, float]] = {
    "debt_gdp": (35.0, 150.0),
    "interest_burden": (8.0, 30.0),
    "primary_deficit": (0.0, 8.0),
    "productivity": (2.1, 0.0),
    "real_gdp_pc": (2.2, 0.0),
    "inflation": (2.0, 10.0),
    "r_minus_g": (-1.0, 3.0),
}

BASELINES: dict[str, float] = {k: v[0] for k, v in BANDS.items()}
CRISIS_VALUES: dict[str, float] = {k: v[1] for k, v in BANDS.items()}

# What each baseline is anchored to. Published on the methodology tab so a
# reader can check the calibration instead of taking it on trust. The measured
# figures are the 1960-2000 means of the same derived series this index scores.
BASELINE_ANCHORS: dict[str, str] = {
    "debt_gdp": "Measured 1960–2000 mean, 34.5% — also the FY2007 pre-crisis level.",
    "interest_burden": "Measured 1950–1979 mean, 7.7%. The 1960–2000 mean (11.7%) is inflated by the Volcker era.",
    "primary_deficit": "Primary balance by definition. The measured 1960–2000 mean is −0.02% of GDP, i.e. balance.",
    "productivity": "Measured 1960–2000 mean of the 10-year CAGR, 2.06%.",
    "real_gdp_pc": "Measured 1960–2000 mean of the 10-year CAGR, 2.20%.",
    "inflation": "Normative: the FOMC's stated 2% target. The 1960–2000 mean of 4.47% embeds the Great Inflation.",
    "r_minus_g": "Measured 1960–2000 mean, −1.18pp.",
}

SOURCE_SERIES = [
    {"id": "FYPUGDA188S", "desc": "Federal Debt Held by the Public as % of GDP (annual, FY)", "used": "Debt/GDP component; projection starting stock"},
    {"id": "FYGFDPUB", "desc": "Federal Debt Held by the Public ($bn, annual, FY)", "used": "Denominator of the effective interest rate"},
    {"id": "FYGFD", "desc": "Gross Federal Debt ($m, annual, FY)", "used": "Context figure only — not scored"},
    {"id": "FYOINT", "desc": "Federal Outlays: Interest ($m, annual, FY)", "used": "Interest burden; primary deficit; effective rate"},
    {"id": "FYFR", "desc": "Federal Receipts ($m, annual, FY)", "used": "Interest burden denominator; receipts/GDP"},
    {"id": "FYFSD", "desc": "Federal Surplus or Deficit ($m, annual, FY)", "used": "Primary deficit (interest added back)"},
    {"id": "GDPA", "desc": "Gross Domestic Product ($bn, annual)", "used": "All ratios; nominal growth g"},
    {"id": "CPIAUCNS", "desc": "CPI for All Urban Consumers, All Items (monthly, NSA)", "used": "Inflation component"},
    {"id": "OPHNFB", "desc": "Nonfarm Business Sector: Labor Productivity (quarterly)", "used": "Productivity component (10-year CAGR)"},
    {"id": "A939RX0Q048SBEA", "desc": "Real Gross Domestic Product per Capita (quarterly)", "used": "Per-capita growth component (10-year CAGR)"},
]

# The composite is presented on 100 (sustainable equilibrium) .. 200 (every
# component pinned at its crisis threshold simultaneously).
SCALE_MIN = 100.0
SCALE_MAX = 200.0

# Four bands, mapped onto the four status roles the stylesheet actually
# defines (good / warning / serious / critical). A fifth "neutral" role would
# render as an unstyled badge.
LEVEL_BANDS: list[tuple[float, str, str]] = [
    (0.0, "Sustainable", "good"),
    (115.0, "Watch", "warning"),
    (130.0, "Strained", "serious"),
    (145.0, "Severe", "critical"),
]


def level_for(score: float) -> tuple[str, str]:
    label, status = LEVEL_BANDS[0][1], LEVEL_BANDS[0][2]
    for lower, lbl, st in LEVEL_BANDS:
        if score >= lower:
            label, status = lbl, st
    return label, status


def band_positions() -> list[dict]:
    span = SCALE_MAX - SCALE_MIN
    return [
        {"label": lbl, "lower": lower, "pct": round((lower - SCALE_MIN) / span * 100, 2)}
        for lower, lbl, _ in LEVEL_BANDS
        if lower > SCALE_MIN
    ]


def scale_pct(score: float) -> float:
    span = SCALE_MAX - SCALE_MIN
    return max(0.0, min(100.0, (score - SCALE_MIN) / span * 100))


# --- Scoring ---------------------------------------------------------------

def stress_for(key: str, value: Optional[float]) -> Optional[float]:
    """Linear stress score, 0 at the baseline and 100 at the crisis threshold.

    Returns None for a missing value so the caller can renormalise rather than
    score a gap as if it were calm.
    """
    if value is None or key not in BANDS:
        return None
    baseline, crisis = BANDS[key]
    if crisis == baseline:
        return 0.0
    score = (value - baseline) / (crisis - baseline) * 100.0
    return max(0.0, min(100.0, score))


def score_row(
    raw_values: dict[str, Optional[float]],
    weights: Optional[dict[str, float]] = None,
) -> dict:
    """Score one year. Missing components are dropped and the rest renormalised.

    `weights` overrides the published component weights, which is what lets the
    presidential panel re-run the whole series under alternative weightings and
    report how far a ranking moves between them.

    Renormalising rather than zero-filling matters for 1945-1951, where the
    productivity and per-capita series do not yet exist: zero-filling would
    score those years as if the growth block were perfectly healthy, which
    would put an artificial trough at the start of the series.
    """
    stresses: dict[str, float] = {}
    contributions: dict[str, float] = {}
    available_weight = 0.0

    weight_of = (lambda key: weights[key]) if weights else (lambda key: COMPONENTS_BY_KEY[key].weight)

    for comp in COMPONENTS:
        stress = stress_for(comp.key, raw_values.get(comp.key))
        if stress is None:
            continue
        stresses[comp.key] = round(stress, 1)
        available_weight += weight_of(comp.key)

    if available_weight <= 0:
        return {"score": SCALE_MIN, "stresses": {}, "contributions": {}, "partial": True}

    total = 0.0
    for key, stress in stresses.items():
        weight = weight_of(key) / available_weight
        contribution = weight * stress
        contributions[key] = round(contribution, 2)
        total += contribution

    label, status = level_for(SCALE_MIN + total)
    return {
        "score": round(SCALE_MIN + total, 1),
        "level_label": label,
        "level_status": status,
        "stresses": stresses,
        "contributions": contributions,
        "block_contributions": _block_contributions(contributions),
        "partial": available_weight < 0.999,
        "covered_weight": round(available_weight, 4),
    }


def _block_contributions(contributions: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {b["key"]: 0.0 for b in BLOCKS}
    for key, value in contributions.items():
        out[COMPONENT_BLOCK[key]] = round(out[COMPONENT_BLOCK[key]] + value, 2)
    return out


def score_history(rows: list[dict]) -> list[dict]:
    """Attach scores to raw rows. Used by the build script and by tests."""
    scored = []
    for row in rows:
        result = score_row(row.get("raw_values") or {})
        entry = dict(row)
        entry.update(result)
        scored.append(entry)
    return scored


# --- History ---------------------------------------------------------------

_history_cache: list[dict] = []
_history_lock = threading.Lock()
_meta_cache: dict = {}


def _load_file() -> dict:
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def get_history() -> list[dict]:
    """The full annual series, scored, oldest first."""
    global _history_cache, _meta_cache
    with _history_lock:
        if _history_cache:
            return _history_cache
        data = _load_file()
        _meta_cache = {k: v for k, v in data.items() if k != "history"}
        _history_cache = data.get("history", [])
        return _history_cache


def get_meta() -> dict:
    get_history()
    return _meta_cache


def latest_row() -> dict:
    history = get_history()
    return history[-1] if history else {}


def compute_snapshot() -> CompositeResult:
    """The most recent fiscal year, as a CompositeResult for the shared UI."""
    row = latest_row()
    raw = row.get("raw_values") or {}
    stresses = row.get("stresses") or {}
    contributions = row.get("contributions") or {}
    year = row.get("year")

    results: list[ComponentResult] = []
    for comp in COMPONENTS:
        value = raw.get(comp.key)
        results.append(
            ComponentResult(
                component=comp,
                current_value=value,
                baseline_value=BASELINES[comp.key],
                stress=stresses.get(comp.key, 0.0),
                contribution=contributions.get(comp.key, 0.0),
                stale=value is None,
                last_updated=f"{year}-09-30" if year else "",
                carried_forward=False,
            )
        )

    score = row.get("score", SCALE_MIN)
    label, status = level_for(score)
    return CompositeResult(
        score=score,
        level_label=label,
        level_status=status,
        components=results,
        week_start=str(year) if year else "",
        degraded=bool(row.get("partial")),
        stale_weight=round(1.0 - float(row.get("covered_weight", 1.0)), 4),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def top_driver(snapshot: CompositeResult) -> Optional[ComponentResult]:
    if not snapshot.components:
        return None
    return max(snapshot.components, key=lambda c: c.contribution)


# --- Debt dynamics projection ----------------------------------------------
#
#     d_t = d_{t-1} * (1 + r_t) / (1 + g_t) + pb_t
#
# d is debt held by the public as a share of GDP, r the effective nominal rate
# paid on the stock, g nominal GDP growth, pb the primary deficit share.
#
# The point of running it as a scenario band rather than a single path is that
# the answer is almost entirely a function of r - g, which nobody knows. A
# single headline year ("insolvency in 2038") reports one guess about r - g as
# though it were a finding. The spread between these three is the honest result.

PROJECTION_YEARS = 30

SCENARIOS = [
    {
        "key": "favorable",
        "label": "Favourable",
        "color": "#10B981",
        "terminal_r": 3.4,
        "nominal_growth": 4.4,
        "terminal_pb": 1.5,
        "narrative": (
            "Rates stay near today's effective cost while nominal growth runs at the pre-2008 "
            "trend, and the primary deficit is halved to 1.5% of GDP. r − g stays negative, so "
            "the debt ratio erodes on its own."
        ),
    },
    {
        "key": "baseline",
        "label": "Baseline",
        "color": "#38BDF8",
        "terminal_r": 4.3,
        "nominal_growth": 4.0,
        "terminal_pb": 3.0,
        "narrative": (
            "The effective rate on the stock converges upward to 4.3% as low-coupon debt from the "
            "2010s rolls off, nominal growth settles at 4.0%, and the primary deficit holds near "
            "its current 3% of GDP. r − g turns mildly positive."
        ),
    },
    {
        "key": "adverse",
        "label": "Adverse",
        "color": "#EF4444",
        "terminal_r": 5.5,
        "nominal_growth": 3.5,
        "terminal_pb": 4.5,
        "narrative": (
            "Term premia rebuild, the effective rate reaches 5.5%, nominal growth slows to 3.5% on "
            "demographic drag, and the primary deficit widens to 4.5% as retirement and health "
            "outlays land. r − g sits at +2pp and the ratio compounds."
        ),
    },
]

# Net interest as a share of receipts. These are stress thresholds, not default
# thresholds: a government borrowing in its own currency does not become
# insolvent at a ratio. They mark where the budget stops having slack.
INTEREST_THRESHOLDS = [
    {"pct": 20.0, "label": "Crowding-out", "desc": "Debt service exceeds all non-defence discretionary spending."},
    {"pct": 25.0, "label": "Distress zone", "desc": "The band where rating agencies have historically downgraded sovereigns."},
    {"pct": 35.0, "label": "Fiscal dominance", "desc": "Debt service crowds out the discretionary budget entirely; monetary policy loses independence."},
]

# How fast the effective rate converges on the terminal rate. The average
# maturity of marketable Treasury debt is ~6 years, so roughly a sixth of the
# stock reprices annually.
REPRICING_SPEED = 1.0 / 6.0


def project(scenario: dict, years: int = PROJECTION_YEARS) -> dict:
    """Run the debt-dynamics recursion forward under one scenario."""
    row = latest_row()
    raw = row.get("raw_values") or {}
    ctx = row.get("context") or {}
    start_year = row.get("year") or date.today().year

    d = (raw.get("debt_gdp") or 0.0) / 100.0
    r = (ctx.get("effective_rate") or 3.4) / 100.0
    pb_now = (raw.get("primary_deficit") or 0.0) / 100.0
    receipts_gdp = (ctx.get("receipts_pct_gdp") or 17.1) / 100.0

    r_terminal = scenario["terminal_r"] / 100.0
    g = scenario["nominal_growth"] / 100.0
    pb_terminal = scenario["terminal_pb"] / 100.0

    path = []
    crossings: dict[float, Optional[int]] = {t["pct"]: None for t in INTEREST_THRESHOLDS}

    for step in range(1, years + 1):
        year = start_year + step
        # Effective rate converges geometrically on the terminal rate as the
        # stock rolls over; the primary deficit converges linearly over 10 years.
        r = r + (r_terminal - r) * REPRICING_SPEED
        blend = min(1.0, step / 10.0)
        pb = pb_now + (pb_terminal - pb_now) * blend

        interest_gdp = r * d          # interest accrues on last year's stock
        d = d * (1.0 + r) / (1.0 + g) + pb
        interest_receipts = interest_gdp / receipts_gdp * 100.0

        for threshold in crossings:
            if crossings[threshold] is None and interest_receipts >= threshold:
                crossings[threshold] = year

        path.append(
            {
                "year": year,
                "debt_gdp": round(d * 100.0, 1),
                "effective_rate": round(r * 100.0, 2),
                "primary_deficit": round(pb * 100.0, 2),
                "interest_pct_gdp": round(interest_gdp * 100.0, 2),
                "interest_pct_receipts": round(interest_receipts, 1),
            }
        )

    return {
        "key": scenario["key"],
        "label": scenario["label"],
        "color": scenario["color"],
        "narrative": scenario["narrative"],
        "terminal_r": scenario["terminal_r"],
        "nominal_growth": scenario["nominal_growth"],
        "terminal_pb": scenario["terminal_pb"],
        "r_minus_g": round(scenario["terminal_r"] - scenario["nominal_growth"], 2),
        "path": path,
        "end_debt_gdp": path[-1]["debt_gdp"] if path else None,
        "end_interest_receipts": path[-1]["interest_pct_receipts"] if path else None,
        "crossings": {str(int(k)): v for k, v in crossings.items()},
    }


def projections(years: int = PROJECTION_YEARS) -> list[dict]:
    return [project(s, years) for s in SCENARIOS]


def horizon_summary(projs: Optional[list[dict]] = None) -> dict:
    """The range of years in which interest/receipts crosses each threshold.

    Reported as a span across scenarios, never as a point estimate — the whole
    argument of this panel is that the spread is the result.
    """
    projs = projs or projections()
    start = latest_row().get("year") or date.today().year
    out = []
    for threshold in INTEREST_THRESHOLDS:
        key = str(int(threshold["pct"]))
        years = [p["crossings"].get(key) for p in projs]
        hit = sorted(y for y in years if y)
        out.append(
            {
                "pct": threshold["pct"],
                "label": threshold["label"],
                "desc": threshold["desc"],
                "earliest": hit[0] if hit else None,
                "latest": hit[-1] if hit else None,
                "never_count": sum(1 for y in years if y is None),
                "scenario_years": {p["key"]: p["crossings"].get(key) for p in projs},
                "years_away": (hit[0] - start) if hit else None,
            }
        )
    return {"start_year": start, "thresholds": out}


# --- Turning points --------------------------------------------------------
#
# Dated to the statute, and phrased as what the law did rather than who signed
# it. The index is a contemporaneous measure: it records what a year's fiscal
# and macro data looked like, not the present value of commitments enacted that
# year. Those are different accounting bases, so these annotate the series —
# they are not scored, ranked, or attributed to an administration.

TURNING_POINTS = [
    {
        "year": 1946,
        "label": "Demobilisation",
        "title": "Post-war demobilisation",
        "description": (
            "Defence outlays fell from 37% of GDP to under 5% in three years. Combined with "
            "1946-48 inflation, which cut the real value of the debt stock by roughly a third, "
            "the ratio fell faster than any deliberate repayment could have achieved."
        ),
    },
    {
        "year": 1965,
        "label": "Medicare/Medicaid",
        "title": "Social Security Act Amendments of 1965",
        "description": (
            "Created Medicare and Medicaid as open-ended fee-for-service entitlements with no "
            "dedicated actuarial pre-funding. The cost showed up decades later, which is exactly "
            "why a contemporaneous index registers almost nothing here."
        ),
    },
    {
        "year": 1971,
        "label": "Bretton Woods ends",
        "title": "Suspension of gold convertibility",
        "description": (
            "Ended the dollar's gold peg and removed the external constraint on monetary "
            "expansion. The 1972 Social Security amendments added automatic CPI indexing on a "
            "formula that over-corrected for inflation until it was repaired in 1977."
        ),
    },
    {
        "year": 1981,
        "label": "ERTA",
        "title": "Economic Recovery Tax Act of 1981",
        "description": (
            "Cut marginal rates 23% across the board while defence spending rose to 6.1% of GDP. "
            "Establishes the modern pattern of large structural deficits at full employment, "
            "visible here as the first sustained peacetime rise in the interest burden."
        ),
    },
    {
        "year": 1990,
        "label": "PAYGO",
        "title": "Budget Enforcement Act of 1990",
        "description": (
            "Introduced statutory PAYGO and discretionary caps. With the 1993 OBRA rate increases "
            "and the late-1990s productivity acceleration, this produced the only sustained "
            "surpluses in the post-war record."
        ),
    },
    {
        "year": 2001,
        "label": "PAYGO lapses",
        "title": "EGTRRA and the expiry of statutory PAYGO",
        "description": (
            "PAYGO was allowed to expire, the 2001 and 2003 tax cuts passed without offsets, and "
            "Medicare Part D was added in 2003 with no dedicated financing. The projected surplus "
            "reverted to structural deficit within two years."
        ),
    },
    {
        "year": 2008,
        "label": "GFC",
        "title": "Financial crisis and the zero-rate era",
        "description": (
            "The debt ratio roughly doubled, but near-zero policy rates held the effective cost of "
            "the stock down: r − g stayed firmly negative for a decade, which is why the interest "
            "burden fell while the debt rose."
        ),
    },
    {
        "year": 2021,
        "label": "Rate shock",
        "title": "Post-COVID inflation and the end of free debt",
        "description": (
            "525bp of tightening from 2022 repriced the stock as it rolled over. Net interest went "
            "from $352bn in FY2021 to over $1tn in FY2025, passing total defence outlays — the "
            "single largest change in the fiscal block in the series."
        ),
    },
]


def turning_points_with_scores() -> list[dict]:
    """Turning points joined to the index value in that year, for chart markers."""
    by_year = {row["year"]: row for row in get_history()}
    out = []
    for point in TURNING_POINTS:
        row = by_year.get(point["year"])
        if not row:
            continue
        entry = dict(point)
        entry["score"] = row.get("score")
        out.append(entry)
    return out


def block_series() -> list[dict]:
    """Per-block contribution for every year, for the stacked area chart."""
    history = get_history()
    return [
        {
            "key": block["key"],
            "label": block["label"],
            "color": block["color"],
            "values": [(row.get("block_contributions") or {}).get(block["key"]) for row in history],
        }
        for block in BLOCKS
    ]


def decade_averages() -> list[dict]:
    """Mean index level by decade — the trend claim, stated as a table."""
    buckets: dict[int, list[float]] = {}
    for row in get_history():
        decade = (row["year"] // 10) * 10
        buckets.setdefault(decade, []).append(row["score"])
    return [
        {
            "decade": f"{d}s",
            "start": d,
            "mean": round(sum(v) / len(v), 1),
            "years": len(v),
            "level": level_for(sum(v) / len(v))[0],
            "status": level_for(sum(v) / len(v))[1],
        }
        for d, v in sorted(buckets.items())
    ]


# --- Fiscal dynamics quadrant ----------------------------------------------
#
# The two terms of the debt-dynamics equation, plotted against each other:
# r - g on the x axis (does the existing stock compound or erode?) and the
# primary balance on the y axis (is current policy adding to it or paying it
# down?). Both axes are signed so that up and right are the adverse direction,
# which makes the top-right quadrant the unambiguous danger zone.
#
# This is the standard debt-sustainability quadrant used in IMF and ECB DSA
# work. It is deliberately *not* the quadrant the source material used, which
# plotted inherited index level against a presidential contribution score --
# two quantities whose correlation is largely mechanical (see the methodology
# tab), so that its quadrants sorted administrations mostly by where they
# happened to start. This one plots two independently measured quantities and
# sorts years by the mechanism actually driving the debt ratio.

QUADRANTS = [
    {
        "key": "compounding",
        "name": "Compounding",
        "x": "pos",
        "y": "pos",
        "color": "#EF4444",
        "desc": "r > g and a primary deficit. Both terms push the ratio up; it rises with no new policy at all.",
    },
    {
        "key": "outgrowing",
        "name": "Outgrowing the deficit",
        "x": "neg",
        "y": "pos",
        "color": "#F59E0B",
        "desc": "A primary deficit absorbed by favourable dynamics. Durable only while r stays below g.",
    },
    {
        "key": "consolidating",
        "name": "Consolidating",
        "x": "neg",
        "y": "neg",
        "color": "#10B981",
        "desc": "Primary surplus and r < g. Both terms cut the ratio — the post-war and late-1990s configuration.",
    },
    {
        "key": "running_to_stand_still",
        "name": "Running to stand still",
        "x": "pos",
        "y": "neg",
        "color": "#38BDF8",
        "desc": "A primary surplus spent offsetting adverse dynamics. Real austerity, little improvement in the ratio.",
    },
]

# Eras are presentational grouping only. Nothing is scored or ranked by them.
ERAS = [
    {"key": "postwar", "label": "1945–59 Post-war", "start": 1945, "end": 1959, "color": "#94A3B8"},
    {"key": "bw_inflation", "label": "1960–79 Bretton Woods → Great Inflation", "start": 1960, "end": 1979, "color": "#A855F7"},
    {"key": "disinflation", "label": "1980–99 Disinflation & consolidation", "start": 1980, "end": 1999, "color": "#F59E0B"},
    {"key": "precrisis", "label": "2000–07 Pre-crisis", "start": 2000, "end": 2007, "color": "#10B981"},
    {"key": "zirp", "label": "2008–19 Zero-rate era", "start": 2008, "end": 2019, "color": "#38BDF8"},
    {"key": "postcovid", "label": "2020– Post-COVID", "start": 2020, "end": 2100, "color": "#EF4444"},
]


def era_for(year: int) -> dict:
    for era in ERAS:
        if era["start"] <= year <= era["end"]:
            return era
    return ERAS[-1]


def quadrant_for(r_minus_g: float, primary_deficit: float) -> str:
    if r_minus_g >= 0:
        return "compounding" if primary_deficit >= 0 else "running_to_stand_still"
    return "outgrowing" if primary_deficit >= 0 else "consolidating"


def quadrant_points() -> list[dict]:
    """One point per year: (r − g, primary deficit), tagged with era and quadrant."""
    out = []
    for row in get_history():
        raw = row.get("raw_values") or {}
        x, y = raw.get("r_minus_g"), raw.get("primary_deficit")
        if x is None or y is None:
            continue
        era = era_for(row["year"])
        out.append(
            {
                "year": row["year"],
                "x": x,
                "y": y,
                "score": row.get("score"),
                "debt_gdp": raw.get("debt_gdp"),
                "era": era["key"],
                "era_label": era["label"],
                "color": era["color"],
                "quadrant": quadrant_for(x, y),
            }
        )
    return out


def quadrant_counts() -> list[dict]:
    """How many years the U.S. spent in each quadrant, for the summary tiles."""
    points = quadrant_points()
    total = len(points) or 1
    counts = []
    for quadrant in QUADRANTS:
        years = [p["year"] for p in points if p["quadrant"] == quadrant["key"]]
        entry = dict(quadrant)
        entry.update(
            {
                "years": len(years),
                "pct": round(len(years) / total * 100, 1),
                "latest": max(years) if years else None,
                "current": bool(years) and points[-1]["quadrant"] == quadrant["key"],
            }
        )
        counts.append(entry)
    return counts


# --- Debt-change decomposition ---------------------------------------------
#
# Rearranging the same recursion gives the standard IMF/ECB attribution of the
# annual change in the debt ratio to two mechanisms:
#
#     d_t − d_{t−1}  =  d_{t−1} · (r_t − g_t) / (1 + g_t)  +  pb_t  +  SFA_t
#                       \________ snowball ________/          \_ policy _/
#
# The snowball term is what the existing stock does on its own; the primary
# balance is what this year's policy adds. SFA is the stock-flow adjustment —
# borrowing that does not pass through the headline deficit (loan portfolios,
# valuation effects, and the ~3-month fiscal/calendar offset in these joins).
# It is reported rather than absorbed: a decomposition whose residual is
# quietly dropped is one that always appears to close.

def debt_decomposition() -> list[dict]:
    history = get_history()
    out = []
    for prev, cur in zip(history, history[1:]):
        d0 = (prev.get("raw_values") or {}).get("debt_gdp")
        d1 = (cur.get("raw_values") or {}).get("debt_gdp")
        ctx = cur.get("context") or {}
        r, g = ctx.get("effective_rate"), ctx.get("nominal_gdp_growth")
        pb = (cur.get("raw_values") or {}).get("primary_deficit")
        if None in (d0, d1, r, g, pb):
            continue
        snowball = d0 * ((r - g) / 100.0) / (1.0 + g / 100.0)
        change = d1 - d0
        out.append(
            {
                "year": cur["year"],
                "change": round(change, 2),
                "snowball": round(snowball, 2),
                "primary": round(pb, 2),
                "sfa": round(change - snowball - pb, 2),
            }
        )
    return out


# --- Reserve-currency displacement simulator -------------------------------
#
# What happens to the debt path if the dollar loses reserve-currency share?
#
# The channel modelled here is the one that is actually quantified in the
# literature: foreign official and private demand for dollar safe assets
# compresses U.S. Treasury yields, and losing that demand widens them. The
# size of that compression is the single assumption the whole simulation rests
# on, so it is exposed as a slider rather than buried as a constant.
#
# Anchors for the default:
#   Warnock & Warnock (2009)                  ~80bp from foreign official flows
#   Krishnamurthy & Vissing-Jorgensen (2012)  ~73bp Treasury convenience yield
#   Jiang, Krishnamurthy & Lustig (2021)      a persistent dollar safety premium
#
# Taking ~140bp as the cost of losing the privilege *entirely*, spread across
# the current 57.7pp of allocated reserves, gives ~2.4bp per percentage point
# of share. The true relationship is very unlikely to be linear — the marginal
# effect should grow as the buffer thins — but a linear rate is transparent,
# and the slider lets a reader impose their own.
#
# Not modelled, and stated as such in the UI: dollar depreciation feeding
# import prices and inflation, lost seigniorage, and any disorderly repricing.
# Every one of those would make the outcome worse, so this is a conservative
# reading of the scenario, not a neutral one.

# Horizon at which the simulated index is reported. See simulate_reserve_shift.
INDEX_HORIZON_YEARS = 10

USD_RESERVE_SHARE = 57.7      # % of allocated FX reserves, IMF COFER
CNY_RESERVE_SHARE = 2.2       # % of allocated FX reserves, IMF COFER
FULL_DISPLACEMENT_BP = 140.0  # bp added to the effective rate if the share went to zero
DEFAULT_PASSTHROUGH_BP = round(FULL_DISPLACEMENT_BP / USD_RESERVE_SHARE, 2)  # bp per pp


def simulator_defaults() -> dict:
    """Starting state and constants for the client-side simulator.

    The browser re-runs the same recursion as `project()`. These are the inputs
    it starts from plus the constants it needs to stay in step with the
    server-side numbers; a test asserts the two agree.
    """
    row = latest_row()
    raw = row.get("raw_values") or {}
    ctx = row.get("context") or {}
    baseline = next(s for s in SCENARIOS if s["key"] == "baseline")
    return {
        "start_year": row.get("year"),
        "debt_gdp": raw.get("debt_gdp"),
        "effective_rate": ctx.get("effective_rate"),
        "primary_deficit": raw.get("primary_deficit"),
        "receipts_pct_gdp": ctx.get("receipts_pct_gdp"),
        "productivity": raw.get("productivity"),
        "real_gdp_pc": raw.get("real_gdp_pc"),
        "inflation": raw.get("inflation"),
        "terminal_r": baseline["terminal_r"],
        "nominal_growth": baseline["nominal_growth"],
        "terminal_pb": baseline["terminal_pb"],
        "usd_reserve_share": USD_RESERVE_SHARE,
        "cny_reserve_share": CNY_RESERVE_SHARE,
        "passthrough_bp": DEFAULT_PASSTHROUGH_BP,
        "full_displacement_bp": FULL_DISPLACEMENT_BP,
        "repricing_speed": REPRICING_SPEED,
        "projection_years": PROJECTION_YEARS,
        "index_horizon_years": INDEX_HORIZON_YEARS,
        "bands": {k: list(v) for k, v in BANDS.items()},
        "weights": {c.key: c.weight for c in COMPONENTS},
        "thresholds": [t["pct"] for t in INTEREST_THRESHOLDS],
        "scale_min": SCALE_MIN,
        "level_bands": [[lower, label, status] for lower, label, status in LEVEL_BANDS],
    }


def simulate_reserve_shift(
    share_shift_pp: float = 0.0,
    passthrough_bp: Optional[float] = None,
    nominal_growth: Optional[float] = None,
    terminal_pb: Optional[float] = None,
    years: int = PROJECTION_YEARS,
) -> dict:
    """Server-side twin of the browser simulator.

    Exists so the scenario is testable and so the page has a correct default
    render before any JavaScript runs.
    """
    baseline = next(s for s in SCENARIOS if s["key"] == "baseline")
    passthrough_bp = DEFAULT_PASSTHROUGH_BP if passthrough_bp is None else passthrough_bp
    nominal_growth = baseline["nominal_growth"] if nominal_growth is None else nominal_growth
    terminal_pb = baseline["terminal_pb"] if terminal_pb is None else terminal_pb

    premium_bp = share_shift_pp * passthrough_bp
    scenario = {
        "key": "simulated",
        "label": "Simulated",
        "color": "#A855F7",
        "narrative": "",
        "terminal_r": baseline["terminal_r"] + premium_bp / 100.0,
        "nominal_growth": nominal_growth,
        "terminal_pb": terminal_pb,
    }
    result = project(scenario, years)
    result["share_shift_pp"] = share_shift_pp
    result["passthrough_bp"] = passthrough_bp
    result["premium_bp"] = round(premium_bp, 1)
    result["usd_share_after"] = round(USD_RESERVE_SHARE - share_shift_pp, 1)
    result["cny_share_after"] = round(CNY_RESERVE_SHARE + share_shift_pp, 1)

    # The index at a ten-year horizon, with the four modelled components moved
    # and the two unmodelled ones (productivity, inflation) held at today's
    # values. Labelled as such in the UI: it is a partial simulation, not a
    # forecast of the index.
    #
    # Ten years rather than the terminal year because by the late 2040s every
    # scenario has pushed debt/GDP past the 150% cap on the debt component, so
    # the index saturates and stops discriminating between inputs — it would
    # read as an unresponsive control rather than as a capped one.
    mark = result["path"][min(INDEX_HORIZON_YEARS, len(result["path"])) - 1]
    raw = dict(latest_row().get("raw_values") or {})
    raw.update(
        {
            "debt_gdp": mark["debt_gdp"],
            "interest_burden": mark["interest_pct_receipts"],
            "primary_deficit": mark["primary_deficit"],
            "r_minus_g": scenario["terminal_r"] - nominal_growth,
        }
    )
    scored = score_row(raw)
    result["index_year"] = mark["year"]
    result["end_index"] = scored["score"]
    result["end_level"] = scored["level_label"]
    result["end_status"] = scored["level_status"]
    return result


# --- Presidential comparison -----------------------------------------------
#
# Differencing the index across administrations, corrected for the two effects
# that otherwise dominate it.
#
# The version of this analysis that circulates elsewhere computes
#
#     PCS = raw change − cyclical adj − exogenous adj − inherited baseline
#
# where the last two terms are per-president constants typed into an if/elif
# chain, and the first is a hand-chosen multiple of the output gap. Under that
# construction the ranking is not an output of the model, it is an input to it:
# whoever picks the eleven constants picks the ordering.
#
# Everything subtracted here is estimated from the series instead:
#
#   1. Cyclical.       OLS of the index's annual change on the annual change in
#                      the CBO output gap, over all 76 usable years. The slope
#                      is reported with its standard error and t-statistic, so
#                      a reader can see how well determined it is.
#   2. Mean reversion. OLS of each term's cyclically adjusted change on the
#                      index level it inherited, across the 14 terms. This is
#                      the correction the uncorrected version most needs: raw
#                      change and inherited level are strongly negatively
#                      correlated, so roughly half of an unadjusted "structural
#                      contribution" score is just regression to the mean.
#
# What is left — the residual — is the part of a term's index change that is
# neither the business cycle nor the arithmetic of where it started. That is
# the most defensible available estimate of a structural contribution. It is
# still not causal, and it is still n=14, which is why every figure is
# published with an error band and a rank range rather than a bare ordering.
#
# No exogenous-shock term is subtracted at all. There is no estimator for it:
# whether a given emergency package is "exogenous" or "structural" is a
# judgement, and in the source construction that judgement moves the ranking by
# more than the ranking's own spread. Rather than encode a preference, the
# panel reports the share of each term spent in NBER-dated recession and lets
# the reader weigh it.

# Weighting schemes. The index published everywhere else on the site is
# "balanced"; the others exist so the ranking can be re-run under defensible
# alternative weightings and the *instability* of a president's rank can be
# reported alongside the rank.
WEIGHTING_SCHEMES = {
    "balanced": {
        "label": "Balanced (published index)",
        "desc": "50% fiscal / 30% growth / 20% monetary — the weighting used everywhere else on this page.",
        "weights": {
            "debt_gdp": 0.18, "interest_burden": 0.17, "primary_deficit": 0.15,
            "productivity": 0.15, "real_gdp_pc": 0.15,
            "inflation": 0.10, "r_minus_g": 0.10,
        },
    },
    "fiscal_heavy": {
        "label": "Fiscal-heavy",
        "desc": "65% fiscal / 20% growth / 15% monetary — a pure solvency reading.",
        "weights": {
            "debt_gdp": 0.24, "interest_burden": 0.23, "primary_deficit": 0.18,
            "productivity": 0.10, "real_gdp_pc": 0.10,
            "inflation": 0.08, "r_minus_g": 0.07,
        },
    },
    "growth_heavy": {
        "label": "Growth-heavy",
        "desc": "35% fiscal / 45% growth / 20% monetary — treats productive capacity as the binding constraint.",
        "weights": {
            "debt_gdp": 0.13, "interest_burden": 0.12, "primary_deficit": 0.10,
            "productivity": 0.225, "real_gdp_pc": 0.225,
            "inflation": 0.10, "r_minus_g": 0.10,
        },
    },
    "equal": {
        "label": "Equal weights",
        "desc": "One seventh each — the naive benchmark, included because it embeds no judgement at all.",
        "weights": {key: 1.0 / 7.0 for key in BANDS},
    },
}

# Terms run on the budget-responsibility convention: a president owns the
# fiscal years whose budgets they submitted, not the ones they were sworn in
# during. FY2009 (October 2008 onward, TARP included) is therefore Bush 43's,
# and Obama's first year is FY2010. This choice is consequential and is stated
# on the page, because the alternative convention moves several rankings.
PRESIDENTS = [
    {"id": "truman", "name": "Harry S. Truman", "party": "D", "first": 1946, "last": 1953},
    {"id": "eisenhower", "name": "Dwight D. Eisenhower", "party": "R", "first": 1954, "last": 1961},
    {"id": "kennedy", "name": "John F. Kennedy", "party": "D", "first": 1962, "last": 1963},
    {"id": "johnson", "name": "Lyndon B. Johnson", "party": "D", "first": 1964, "last": 1969},
    {"id": "nixon", "name": "Richard Nixon", "party": "R", "first": 1970, "last": 1974},
    {"id": "ford", "name": "Gerald Ford", "party": "R", "first": 1975, "last": 1977},
    {"id": "carter", "name": "Jimmy Carter", "party": "D", "first": 1978, "last": 1981},
    {"id": "reagan", "name": "Ronald Reagan", "party": "R", "first": 1982, "last": 1989},
    {"id": "bush41", "name": "George H. W. Bush", "party": "R", "first": 1990, "last": 1993},
    {"id": "clinton", "name": "Bill Clinton", "party": "D", "first": 1994, "last": 2001},
    {"id": "bush43", "name": "George W. Bush", "party": "R", "first": 2002, "last": 2009},
    {"id": "obama", "name": "Barack Obama", "party": "D", "first": 2010, "last": 2017},
    {"id": "trump", "name": "Donald Trump", "party": "R", "first": 2018, "last": 2021},
    {"id": "biden", "name": "Joe Biden", "party": "D", "first": 2022, "last": 2025},
]

PARTY_LABEL = {"D": "Democrat", "R": "Republican"}


def _ols(xs: list[float], ys: list[float]) -> dict:
    """Simple least squares. Pure Python: the deployed site carries no numpy."""
    n = len(xs)
    if n < 3:
        return {"alpha": 0.0, "beta": 0.0, "r2": 0.0, "se_beta": 0.0, "t": 0.0, "n": n, "resid_sd": 0.0}
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0:
        return {"alpha": my, "beta": 0.0, "r2": 0.0, "se_beta": 0.0, "t": 0.0, "n": n, "resid_sd": 0.0}
    beta = sxy / sxx
    alpha = my - beta * mx
    resid = [y - (alpha + beta * x) for x, y in zip(xs, ys)]
    ssr = sum(e * e for e in resid)
    dof = max(1, n - 2)
    resid_var = ssr / dof
    se_beta = (resid_var / sxx) ** 0.5 if sxx > 0 else 0.0
    return {
        "alpha": alpha,
        "beta": beta,
        "r2": (sxy * sxy) / (sxx * syy) if syy > 0 else 0.0,
        "se_beta": se_beta,
        "t": beta / se_beta if se_beta else 0.0,
        "n": n,
        "resid_sd": resid_var ** 0.5,
    }


_scored_cache: dict[str, list[dict]] = {}


def history_under(scheme: str = "balanced") -> list[dict]:
    """The full annual series rescored under one weighting scheme."""
    if scheme in _scored_cache:
        return _scored_cache[scheme]
    weights = WEIGHTING_SCHEMES[scheme]["weights"]
    out = []
    for row in get_history():
        scored = score_row(row.get("raw_values") or {}, weights=weights)
        out.append({"year": row["year"], "score": scored["score"], "context": row.get("context") or {}})
    _scored_cache[scheme] = out
    return out


def cyclical_model(scheme: str = "balanced") -> dict:
    """OLS of the index's annual change on the annual change in the output gap.

    This replaces a hand-picked coefficient with an estimated one, and carries
    its own standard error so the page can show how well determined it is.
    """
    rows = [r for r in history_under(scheme) if r["context"].get("output_gap") is not None]
    xs, ys = [], []
    for a, b in zip(rows, rows[1:]):
        if b["year"] - a["year"] != 1:
            continue
        xs.append(b["context"]["output_gap"] - a["context"]["output_gap"])
        ys.append(b["score"] - a["score"])
    model = _ols(xs, ys)
    model["scheme"] = scheme
    return model


def _term_rows(scheme: str) -> list[dict]:
    """Raw and cyclically adjusted change for each term, before mean reversion."""
    by_year = {r["year"]: r for r in history_under(scheme)}
    cyc = cyclical_model(scheme)
    out = []
    for pres in PRESIDENTS:
        start = by_year.get(pres["first"] - 1)
        end = by_year.get(pres["last"])
        if not start or not end:
            continue
        raw = end["score"] - start["score"]
        gap0 = start["context"].get("output_gap")
        gap1 = end["context"].get("output_gap")
        # Truman's inherited year (1945) predates the CBO potential series, so
        # his cyclical term is undefined rather than assumed zero.
        cyclical = cyc["beta"] * (gap1 - gap0) if (gap0 is not None and gap1 is not None) else None
        out.append(
            {
                **pres,
                "inherited": round(start["score"], 1),
                "ending": round(end["score"], 1),
                "raw_change": round(raw, 1),
                "cyclical": round(cyclical, 1) if cyclical is not None else None,
                "adjusted": round(raw - (cyclical or 0.0), 1),
                "years": pres["last"] - pres["first"] + 1,
            }
        )
    return out


def presidential_scores(scheme: str = "balanced") -> dict:
    """Full decomposition for every term under one weighting scheme."""
    rows = _term_rows(scheme)
    cyc = cyclical_model(scheme)

    # Mean-reversion model: how much of a term's adjusted change is predicted by
    # nothing but the level it inherited?
    xs = [r["inherited"] for r in rows]
    ys = [r["adjusted"] for r in rows]
    rev = _ols(xs, ys)

    for row in rows:
        expected = rev["alpha"] + rev["beta"] * row["inherited"]
        row["expected"] = round(expected, 1)
        row["residual"] = round(row["adjusted"] - expected, 1)
        row["residual_per_year"] = round(row["residual"] / row["years"], 2)
        recessions = [
            r["context"].get("recession_share")
            for r in history_under(scheme)
            if row["first"] <= r["year"] <= row["last"]
        ]
        present = [v for v in recessions if v is not None]
        row["recession_share"] = round(sum(present) / len(present), 2) if present else None

    return {
        "scheme": scheme,
        "scheme_label": WEIGHTING_SCHEMES[scheme]["label"],
        "rows": rows,
        "cyclical_model": cyc,
        "reversion_model": rev,
        # ±1 residual standard deviation, the honest error bar on any single
        # president's score.
        "residual_sd": round(rev["resid_sd"], 1),
    }


def presidential_comparison() -> dict:
    """The panel: scores under every scheme, plus each president's rank range.

    The rank range is the point of the exercise. If a president's position
    swings six places across four defensible weightings, the ordering is not a
    finding, and the page should say so rather than print a league table.
    """
    per_scheme = {key: presidential_scores(key) for key in WEIGHTING_SCHEMES}
    base = per_scheme["balanced"]

    # Rank 1 = largest positive residual (most risk added).
    ranks: dict[str, dict[str, int]] = {}
    for key, result in per_scheme.items():
        order = sorted(result["rows"], key=lambda r: -r["residual"])
        for i, row in enumerate(order):
            ranks.setdefault(row["id"], {})[key] = i + 1

    raw_order = sorted(base["rows"], key=lambda r: -r["raw_change"])
    raw_rank = {row["id"]: i + 1 for i, row in enumerate(raw_order)}

    rows = []
    for row in sorted(base["rows"], key=lambda r: -r["residual"]):
        by_scheme = ranks[row["id"]]
        values = list(by_scheme.values())
        entry = dict(row)
        entry.update(
            {
                "party_label": PARTY_LABEL[row["party"]],
                "rank": by_scheme["balanced"],
                "rank_min": min(values),
                "rank_max": max(values),
                "rank_spread": max(values) - min(values),
                "ranks_by_scheme": by_scheme,
                "residual_by_scheme": {
                    key: next(r["residual"] for r in res["rows"] if r["id"] == row["id"])
                    for key, res in per_scheme.items()
                },
                "raw_rank": raw_rank[row["id"]],
                "rank_shift_vs_raw": raw_rank[row["id"]] - by_scheme["balanced"],
            }
        )
        rows.append(entry)

    correlations = {
        "raw_vs_inherited": round(
            _ols([r["inherited"] for r in base["rows"]], [r["raw_change"] for r in base["rows"]])["r2"], 3
        ),
        "adjusted_vs_inherited": round(base["reversion_model"]["r2"], 3),
    }

    # How many terms are actually distinguishable from "did nothing"? With
    # n=14 the residual standard deviation is large relative to the spread of
    # the scores, and saying so is the single most important thing this panel
    # can do. A league table that hides it is the thing being corrected here.
    sd = base["residual_sd"]
    indistinct = [r["name"] for r in rows if abs(r["residual"]) <= sd]
    party_means = {}
    for party in ("D", "R"):
        vals = [r["residual"] for r in rows if r["party"] == party]
        party_means[party] = round(sum(vals) / len(vals), 2) if vals else 0.0

    return {
        "rows": rows,
        "indistinguishable": indistinct,
        "indistinguishable_count": len(indistinct),
        "distinguishable": [
            {"name": r["name"], "residual": r["residual"], "party": r["party"]}
            for r in rows if abs(r["residual"]) > sd
        ],
        "party_means": party_means,
        "party_gap": round(abs(party_means["D"] - party_means["R"]), 2),
        "schemes": [{"key": k, **v} for k, v in
                    ((k, {"label": s["label"], "desc": s["desc"]}) for k, s in WEIGHTING_SCHEMES.items())],
        "cyclical_model": base["cyclical_model"],
        "reversion_model": base["reversion_model"],
        "residual_sd": base["residual_sd"],
        "correlations": correlations,
        "max_rank_spread": max(r["rank_spread"] for r in rows),
        "unstable_count": sum(1 for r in rows if r["rank_spread"] >= 4),
    }


# --- Executive summary -----------------------------------------------------
#
# Every figure the summary card quotes is derived here rather than written into
# the template. The card makes definite claims ("the highest in the series",
# "no party signal"), and a claim hard-coded next to a number that rebuilds
# annually is a claim that will eventually be false without anyone noticing.
# If the data stops supporting a sentence, the number feeding it changes and
# the tests below fail.

def executive_summary() -> dict:
    history = get_history()
    latest = history[-1]
    raw = latest.get("raw_values") or {}

    peak = max(history, key=lambda r: r["score"])
    trough = min(history, key=lambda r: r["score"])
    decades = decade_averages()
    best_decade = min(decades, key=lambda d: d["mean"])
    current_decade = decades[-1]
    prior_worst = max(decades[:-1], key=lambda d: d["mean"])

    # Is today's interest burden actually unprecedented, or merely high? The
    # card says which, so it has to check rather than assume.
    burdens = [
        (r["year"], (r.get("raw_values") or {}).get("interest_burden"))
        for r in history
        if (r.get("raw_values") or {}).get("interest_burden") is not None
    ]
    worst_burden_year, worst_burden = max(burdens, key=lambda t: t[1])

    quadrants = quadrant_counts()
    current_quadrant = next((q for q in quadrants if q["current"]), None)

    horizon = horizon_summary()
    fiscal_dominance = next(t for t in horizon["thresholds"] if t["pct"] == 35.0)

    pres = presidential_comparison()
    reducers = sorted(
        [d for d in pres["distinguishable"] if d["residual"] < 0], key=lambda d: d["residual"]
    )
    adders = sorted(
        [d for d in pres["distinguishable"] if d["residual"] > 0], key=lambda d: -d["residual"]
    )

    # Recent debt arithmetic: how much did inflation quietly retire, and how
    # much did policy add, over the last five years?
    recent = debt_decomposition()[-5:]
    snowball_5y = round(sum(r["snowball"] for r in recent), 1)
    primary_5y = round(sum(r["primary"] for r in recent), 1)

    return {
        "year": latest["year"],
        "score": latest["score"],
        "level": latest.get("level_label"),
        "status": latest.get("level_status"),
        "points_above_baseline": round(latest["score"] - SCALE_MIN, 1),
        "peak": {"year": peak["year"], "score": peak["score"]},
        "trough": {"year": trough["year"], "score": trough["score"]},
        "best_decade": best_decade,
        "current_decade": current_decade,
        "prior_worst_decade": prior_worst,
        "decade_is_worst_since": prior_worst["decade"],
        "interest_burden": raw.get("interest_burden"),
        "interest_burden_is_series_high": worst_burden_year == latest["year"],
        "worst_burden_year": worst_burden_year,
        "worst_burden": worst_burden,
        "debt_gdp": raw.get("debt_gdp"),
        "r_minus_g": raw.get("r_minus_g"),
        "primary_deficit": raw.get("primary_deficit"),
        "quadrant": current_quadrant,
        "fiscal_dominance": fiscal_dominance,
        "reducers": reducers,
        "adders": adders,
        "indistinguishable_count": pres["indistinguishable_count"],
        "term_count": len(pres["rows"]),
        "residual_sd": pres["residual_sd"],
        "party_means": pres["party_means"],
        "party_gap": pres["party_gap"],
        "party_gap_ratio": round(pres["party_gap"] / pres["residual_sd"], 2) if pres["residual_sd"] else 0.0,
        "snowball_5y": snowball_5y,
        "primary_5y": primary_5y,
        "usd_reserve_share": USD_RESERVE_SHARE,
        "sim_full_shift": simulate_reserve_shift(30.0)["crossings"]["35"],
        "sim_loose_pb": simulate_reserve_shift(0.0, terminal_pb=6.0)["crossings"]["35"],
        "sim_tight_pb": simulate_reserve_shift(0.0, terminal_pb=1.5)["crossings"]["35"],
    }


# --- Wars and the defence burden -------------------------------------------
#
# Wars enter this index the same way everything else does: through the deficit
# and the debt they leave behind. There is no separate "war" component, and no
# attempt to back out a counterfactual "cost of the war" from aggregate
# outlays — that is the same unidentified-counterfactual problem the
# presidential panel refuses to pretend it has solved.
#
# Trying it anyway is instructive, which is why the failure is documented here
# rather than hidden. Scoring each conflict as defence spending above its own
# three-years-prior baseline (the CRS method) gives sensible answers for Korea
# and the post-9/11 wars, and nonsense for two others:
#
#   Vietnam    0.2pp of GDP "excess" — because 1962-64 defence was already
#              10.9% of GDP. Vietnam was largely absorbed inside a standing
#              Cold War establishment rather than added on top of it.
#   Gulf War   0.0pp — it was fought during the post-Cold-War drawdown, so
#              defence fell as a share of GDP throughout.
#
# Both readings are arithmetically correct and analytically useless. So this
# panel reports two things that are actually measured — the defence burden as a
# share of GDP, and the change in debt/GDP across each period — and cites CRS
# for constant-dollar operation costs rather than deriving a rival estimate.
#
# The two measures genuinely disagree, and the disagreement is the point.
# Vietnam cost $738bn in FY2011 dollars but barely moved the burden, because
# nominal GDP was compounding at roughly 8% a year underneath it. Cost and
# burden are different questions.

# Congressional Research Service, "Costs of Major U.S. Wars" (RS22926,
# 29 June 2010), Table 1. Constant dollars are FY2011. Military operations
# only: excludes veterans' benefits, interest on war borrowing, and aid to
# allies — which is why the post-9/11 figure here is a fraction of the Brown
# University estimate quoted alongside it.
CRS_WAR_COSTS = [
    {
        "war": "World War II", "years": "1941–1945", "peak_year": 1945,
        "current_bn": 296, "constant2011_bn": 4104,
        "war_pct_gdp_peak": 35.8, "defence_pct_gdp_peak": 37.5,
    },
    {
        "war": "Korea", "years": "1950–1953", "peak_year": 1952,
        "current_bn": 30, "constant2011_bn": 341,
        "war_pct_gdp_peak": 4.2, "defence_pct_gdp_peak": 13.2,
    },
    {
        "war": "Vietnam", "years": "1965–1975", "peak_year": 1968,
        "current_bn": 111, "constant2011_bn": 738,
        "war_pct_gdp_peak": 2.3, "defence_pct_gdp_peak": 9.5,
    },
    {
        "war": "Persian Gulf", "years": "1990–1991", "peak_year": 1991,
        "current_bn": 61, "constant2011_bn": 102,
        "war_pct_gdp_peak": 0.3, "defence_pct_gdp_peak": 4.6,
    },
    {
        "war": "Iraq", "years": "2003–2010", "peak_year": 2008,
        "current_bn": 715, "constant2011_bn": 784,
        "war_pct_gdp_peak": 1.0, "defence_pct_gdp_peak": 4.3,
    },
    {
        "war": "Afghanistan / other", "years": "2001–2010", "peak_year": 2010,
        "current_bn": 297, "constant2011_bn": 321,
        "war_pct_gdp_peak": 0.7, "defence_pct_gdp_peak": 4.9,
    },
]

# Periods shaded on the defence-burden chart. `measured` marks the spans this
# dataset actually covers; WWII is included for context but the series begins
# in its final year, so only 1945 is observed here.
WAR_PERIODS = [
    {"key": "wwii", "label": "WWII", "short": "WWII", "start": 1945, "end": 1945, "color": "#EF4444", "partial": True},
    {"key": "korea", "label": "Korea", "short": "Korea", "start": 1950, "end": 1953, "color": "#F59E0B", "partial": False},
    {"key": "vietnam", "label": "Vietnam", "short": "Vietnam", "start": 1965, "end": 1975, "color": "#A855F7", "partial": False},
    {"key": "reagan", "label": "Cold War buildup", "short": "Cold War", "start": 1981, "end": 1989, "color": "#64748B", "partial": False},
    {"key": "gulf", "label": "Gulf War", "short": "Gulf", "start": 1990, "end": 1991, "color": "#38BDF8", "partial": False},
    {"key": "post911", "label": "Post-9/11 wars", "short": "Post-9/11", "start": 2001, "end": 2021, "color": "#10B981", "partial": False},
]


def defence_series() -> list[dict]:
    """National defence outlays as a share of GDP, per year."""
    return [
        {"year": r["year"], "defence": (r.get("context") or {}).get("defense_pct_gdp")}
        for r in get_history()
    ]


def war_periods_measured() -> list[dict]:
    """Each shaded period with what the data actually shows across it."""
    by_year = {r["year"]: r for r in get_history()}
    out = []
    for period in WAR_PERIODS:
        years = [y for y in range(period["start"], period["end"] + 1) if y in by_year]
        if not years:
            continue
        defence = [
            (by_year[y].get("context") or {}).get("defense_pct_gdp")
            for y in years
        ]
        defence = [d for d in defence if d is not None]
        start_row = by_year.get(period["start"] - 1) or by_year[years[0]]
        end_row = by_year[years[-1]]
        entry = dict(period)
        entry.update(
            {
                "peak_defence": max(defence) if defence else None,
                "mean_defence": round(sum(defence) / len(defence), 2) if defence else None,
                "debt_gdp_change": round(
                    end_row["raw_values"]["debt_gdp"] - start_row["raw_values"]["debt_gdp"], 1
                ),
                "index_change": round(end_row["score"] - start_row["score"], 1),
            }
        )
        out.append(entry)
    return out


def defence_burden_summary() -> dict:
    """Today's defence burden against the whole post-war record."""
    series = [d for d in defence_series() if d["defence"] is not None]
    latest = series[-1]
    lowest = min(series, key=lambda d: d["defence"])
    highest = max(series, key=lambda d: d["defence"])
    ranked = sorted(series, key=lambda d: d["defence"])
    rank = next(i for i, d in enumerate(ranked) if d["year"] == latest["year"]) + 1
    return {
        "year": latest["year"],
        "defence": latest["defence"],
        "lowest": lowest,
        "highest": highest,
        "rank_from_bottom": rank,
        "total": len(series),
        "is_near_record_low": rank <= 5,
    }


# --- Debt added, by administration -----------------------------------------

def debt_by_administration() -> dict:
    """How much debt each administration's budget years actually added.

    Three measures, because the naive one is badly misleading. Nominal dollars
    make every recent president look historically profligate purely because the
    economy is larger and prices are ~18x their 1945 level. Constant dollars fix
    the price half of that. Only the change in debt as a share of GDP is
    comparable across eighty years, and it is the one the index uses.
    """
    by_year = {r["year"]: r for r in get_history()}
    base_cpi = (by_year[max(by_year)].get("context") or {}).get("cpi_index")

    rows = []
    for pres in PRESIDENTS:
        start = by_year.get(pres["first"] - 1)
        end = by_year.get(pres["last"])
        if not start or not end:
            continue
        sc, ec = start.get("context") or {}, end.get("context") or {}
        d0, d1 = sc.get("debt_public_bn"), ec.get("debt_public_bn")
        if d0 is None or d1 is None:
            continue
        nominal = d1 - d0
        # Deflate each end of the span to today's prices, then difference, so
        # the figure is "debt added, in today's purchasing power".
        real = None
        if sc.get("cpi_index") and ec.get("cpi_index") and base_cpi:
            real = (d1 * base_cpi / ec["cpi_index"]) - (d0 * base_cpi / sc["cpi_index"])
        years = pres["last"] - pres["first"] + 1
        rows.append(
            {
                **pres,
                "party_label": PARTY_LABEL[pres["party"]],
                "years": years,
                "debt_start_bn": round(d0, 1),
                "debt_end_bn": round(d1, 1),
                "nominal_added_bn": round(nominal, 1),
                "nominal_per_year_bn": round(nominal / years, 1),
                "real_added_bn": round(real, 1) if real is not None else None,
                "real_per_year_bn": round(real / years, 1) if real is not None else None,
                "debt_gdp_start": start["raw_values"]["debt_gdp"],
                "debt_gdp_end": end["raw_values"]["debt_gdp"],
                "debt_gdp_change": round(
                    end["raw_values"]["debt_gdp"] - start["raw_values"]["debt_gdp"], 1
                ),
                "multiple": round(d1 / d0, 2) if d0 else None,
            }
        )

    by_nominal = sorted(rows, key=lambda r: -r["nominal_added_bn"])
    by_real = sorted([r for r in rows if r["real_added_bn"] is not None], key=lambda r: -r["real_added_bn"])
    by_share = sorted(rows, key=lambda r: -r["debt_gdp_change"])

    party_totals = {}
    for party in ("D", "R"):
        subset = [r for r in rows if r["party"] == party]
        party_totals[party] = {
            "nominal_bn": round(sum(r["nominal_added_bn"] for r in subset), 1),
            "debt_gdp_change": round(sum(r["debt_gdp_change"] for r in subset), 1),
            "years": sum(r["years"] for r in subset),
            "terms": len(subset),
        }

    return {
        "rows": by_share,
        "top_nominal": by_nominal[0],
        "top_real": by_real[0] if by_real else None,
        "top_share": by_share[0],
        "bottom_share": by_share[-1],
        "party_totals": party_totals,
        "base_year": max(by_year),
    }


# --- Enacted and pending items not yet in the series -----------------------
#
# The index runs through the last closed fiscal year. Anything legislated since
# is real, scored, and absent from every chart above. Listing it separately is
# the only honest way to show it: folding a projection into a measured series
# would make the series no longer measured.

FISCAL_ITEMS = [
    {
        "key": "obbba",
        "name": "One Big Beautiful Bill Act (H.R. 1)",
        "enacted": "July 2025",
        "window": "FY2025–2034",
        "primary_tn": 3.4,
        "with_interest_tn": 4.1,
        "if_extended_tn": 5.5,
        "kind": "legislation",
        "source": "CBO final score; extension estimate from CRFB",
        "source_url": "https://www.crfb.org/press-releases/final-obbba-score-confirms-long-road-fiscal-recovery",
        "note": (
            "The single largest fiscal action in the series' recent history. CBO's $3.4tn is the "
            "primary-deficit effect; $4.1tn includes the debt service it generates. Neither figure "
            "includes macroeconomic feedback, which CRFB expects would add to borrowing rather than "
            "offset it."
        ),
    },
    {
        "key": "iran",
        "name": "Iran conflict (Operation Epic Fury)",
        "enacted": "2026, ongoing",
        "window": "FY2026",
        "cost_low_bn": 30.0,
        "cost_high_bn": 40.0,
        "requested_bn": 87.6,
        "kind": "conflict",
        "source": "OMB testimony (30 June 2026) and CSIS analysis (July 2026)",
        "source_url": "https://www.csis.org/analysis/war-costs-make-third-876-billion-supplemental-request",
        "note": (
            "OMB puts direct war costs near $30bn; CSIS estimates ~$40bn including base repair. The "
            "$87.6bn supplemental request is broader than the war — roughly a third is war-related, "
            "the rest is other defence priorities and unrelated agency funding."
        ),
    },
    {
        "key": "defence26",
        "name": "FY2026 national defence budget",
        "enacted": "FY2026",
        "window": "annual",
        "level_tn": 1.0,
        "requested_next_tn": 1.5,
        "kind": "budget",
        "source": "CRFB, defence funding in context",
        "source_url": "https://www.crfb.org/blogs/defense-funding-put-context",
        "note": (
            "National defence passed $1tn for the first time in FY2026, up more than 13% on FY2025, "
            "with $1.5tn requested for FY2027. In share-of-GDP terms — the measure that matters for "
            "solvency — this is still near the lowest of the whole post-war record."
        ),
    },
]


def fiscal_items_with_impact() -> dict:
    """Translate the pending items into the units the projection actually uses.

    A ten-year dollar total means nothing to a debt-dynamics recursion until it
    is expressed as a share of GDP per year, which is also the only way the
    legislation and the war can be compared to each other honestly.
    """
    latest = latest_row()
    ctx = latest.get("context") or {}
    gdp = ctx.get("gdp_bn")
    growth = next(s for s in SCENARIOS if s["key"] == "baseline")["nominal_growth"] / 100.0

    # Cumulative nominal GDP over a ten-year window at the baseline growth rate.
    ten_year_gdp = sum(gdp * ((1 + growth) ** n) for n in range(1, 11)) if gdp else None

    entries = []
    for item in FISCAL_ITEMS:
        entry = dict(item)
        if item["kind"] == "legislation" and ten_year_gdp:
            entry["pct_gdp_per_year"] = round(item["primary_tn"] * 1000 / ten_year_gdp * 100, 2)
            entry["pct_gdp_per_year_extended"] = round(
                item["if_extended_tn"] * 1000 / ten_year_gdp * 100, 2
            )
        elif item["kind"] == "conflict" and gdp:
            entry["pct_gdp_one_off"] = round(item["cost_high_bn"] / gdp * 100, 3)
        entries.append(entry)

    obbba = next(i for i in entries if i["key"] == "obbba")
    iran = next(i for i in entries if i["key"] == "iran")

    baseline_pb = next(s for s in SCENARIOS if s["key"] == "baseline")["terminal_pb"]
    with_obbba = simulate_reserve_shift(
        0.0, terminal_pb=baseline_pb + obbba["pct_gdp_per_year"]
    )
    without = simulate_reserve_shift(0.0)

    # Cumulative against cumulative. Comparing the bill's annual share to the
    # war's one-off share would flatter the war by a factor of ten, since the
    # bill recurs across the whole budget window and the war does not.
    ratio = None
    if iran.get("cost_high_bn"):
        ratio = round(obbba["primary_tn"] * 1000 / iran["cost_high_bn"])

    return {
        # Deliberately not "items": Jinja resolves `.items` on a dict to the
        # bound method, not the key, and fails at render time.
        "entries": entries,
        "ten_year_gdp_tn": round(ten_year_gdp / 1000, 1) if ten_year_gdp else None,
        "obbba_vs_iran_ratio": ratio,
        "obbba_cumulative_pct_gdp": round(obbba["pct_gdp_per_year"] * 10, 1),
        "iran_pct_gdp": iran.get("pct_gdp_one_off"),
        "baseline_crossing": without["crossings"]["35"],
        "obbba_crossing": with_obbba["crossings"]["35"],
        "baseline_end_debt": without["end_debt_gdp"],
        "obbba_end_debt": with_obbba["end_debt_gdp"],
        "years_lost": (
            without["crossings"]["35"] - with_obbba["crossings"]["35"]
            if without["crossings"]["35"] and with_obbba["crossings"]["35"] else None
        ),
    }
