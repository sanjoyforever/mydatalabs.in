"""Hard-Metric Democracy Index (HMDI): thirty economies, 2000-2024.

What this measures, and what it refuses to
------------------------------------------
Every widely-cited democracy index — V-Dem, Freedom House, EIU — is built from
expert questionnaires. Country experts score ordinal judgements ("is the
judiciary independent?") and those judgements are aggregated. That approach can
see things no counter can, and it pays for the privilege with an irreducible
coder-subjectivity term that no amount of inter-rater statistics removes.

This index takes the opposite trade. Every input is a count, a rate or a ratio
that someone published: votes divided by voting-age population, seat shares put
through Gallagher's formula, women's seats over total seats, detainees over
prisoners, prisoners over population, imprisoned journalists over population.
Nothing here is an opinion about a country. The cost of that discipline is
severe and worth stating plainly at the top: **the things hardest to count are
often the things that matter most.** Judicial independence, press pluralism,
whether an election was actually free — none of them appear below, because none
of them are a number anyone publishes. A high score here means "the countable
things look healthy", not "this is a good democracy".

Scale-invariance
----------------
Every indicator is a rate, a ratio or a per-capita quantity, so India and
Norway are compared on the same axis and population size drops out.

Aggregation: why the geometric mean
-----------------------------------
Twelve indicators roll into five pillars (arithmetic mean within a pillar), and
the five pillars roll into a composite. The obvious choice for the second step
is another arithmetic mean, and it is wrong here, because an arithmetic mean
makes pillars perfectly substitutable: a country can buy back a pillar score of
0 with a 100 somewhere else.

That is not a hypothetical defect. Under the arithmetic mean the United Arab
Emirates — an absolute federal monarchy with no elected national legislature —
scored 61.7 for 2024, four points below the United States, because a legislative
concentration score of 0 was averaged against an appointed 50% female chamber
scoring 100, and the resulting "50" was then averaged with an economic-equity
score that inequality data alone happens to place high. Democracy does not work
that way. A country with no contested elections is not a middling democracy that
compensated elsewhere; the pillars are complements, not substitutes.

The geometric mean across pillars is the standard fix — it is why the HDI
switched in 2010 — and it does exactly the intended work here without
rewriting the league table: the top twenty move by at most one place, while the
UAE falls to 52.4, Saudi Arabia to 31.6 and China to 28.4, which is the first
time any of the three lands in the bottom tier at all.

Scores are floored at 1.0 before the log so that a single genuine zero darkens
the composite hard without collapsing it to zero and discarding every other
measurement in the row.

Collinear indicators are scored once
------------------------------------
The source dataset carried twelve scored indicators, two pairs of which are the
same statistic twice:

  * Effective Number of Parties and the legislative HHI are algebraically
    identical — ENP = 10000 / HHI, exactly, for seat shares. They were keyed
    independently and disagree with each other by a median of 6.6% (up to 24%
    for Brazil), which is a self-inconsistency in the data rather than two
    readings. Scoring both put party fragmentation into the composite at 15%
    weight through two different pillars.
  * Gini and the Palma ratio are both summaries of one Lorenz curve and
    correlate at rho = +0.99 across the panel.

So HHI and Gini are scored; ENP and Palma are computed, published and charted
as context. ENP is derived from HHI here (10000 / HHI) rather than read from the
source column, which is what removes the inconsistency. Ten indicators are
scored; the pillar weights are unchanged.

V-Dem is shown, and never scored
--------------------------------
An index that opens by picking a fight with expert coding owes the reader the
other side of the argument. V-Dem's Liberal Democracy Index (v2x_libdem) is
carried beside every row as a comparator: rank within these same thirty, in the
selected year, in grey. It is not an input, no expert judgement touches the
composite, and the grey column does not move when a reader drags the weight
sliders. The two rankings agree at Spearman rho = +0.82 in 2024, which is the
useful result in both directions -- counting recovers most of what country
experts see, and the fifth of the variance it does not recover is where the
United States (24th here, 10th on V-Dem, dragged by incarceration) and Poland
(7th here, 18th on V-Dem) sit. See scripts/build_vdem_reference.py.

Provenance
----------
The panel is not twelve annually-published series. It is 1,663 hand-keyed
anchor points — a value attached to a year with a real source behind it — out
of 9,000 country-year-indicator cells, with linear interpolation between
anchors and flat-carry outside them. That is 18.5% measured. It is a reasonable
way to carry sources that do not publish annually (an election result exists in
election years; World Prison Brief reports when it reports), and it is not
measurement. `anchor_share` is computed per country and per year and reported
on the page, and the trajectory chart shades interpolated spans, so nobody
reads a straight line between two anchors as evidence of a stable decade.

See scripts/build_democracy_history.py, which turns app/data/democracy_anchors.
json — the input of record — into app/data/democracy_history.json.
"""

from __future__ import annotations

import json
import math
import os
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from app.scoring import CompositeResult

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
HISTORY_JSON = os.path.join(DATA_DIR, "democracy_history.json")
VDEM_JSON = os.path.join(DATA_DIR, "vdem_libdem.json")


# --- Pillars ---------------------------------------------------------------
# Five equal weights. Equal because there is no defensible empirical basis for
# saying that, say, due process is 1.4x electoral health; any other split would
# be a preference dressed as a finding. The dashboard lets a reader reweight
# them and watch the table move, which is the honest way to present a choice
# that arbitrary.

PILLARS: list[dict[str, str]] = [
    {"key": "electoral", "label": "Electoral Health & Representation",
     "short": "Electoral", "color": "#38BDF8",
     "question": "Do people vote, and do the votes turn into seats?"},
    {"key": "power_dispersion", "label": "Power Dispersion & Checks",
     "short": "Power Dispersion", "color": "#A78BFA",
     "question": "Is legislative power concentrated, and who holds it?"},
    {"key": "economic_equity", "label": "Economic Equity & Parity",
     "short": "Economic Equity", "color": "#34D399",
     "question": "How unequally is national income distributed?"},
    {"key": "information_telemetry", "label": "Information & Telemetry Freedom",
     "short": "Information", "color": "#FBBF24",
     "question": "Does the state switch off the network or jail reporters?"},
    {"key": "justice_rule_of_law", "label": "Due Process & Rule of Law",
     "short": "Due Process", "color": "#F87171",
     "question": "How many are held, and how many are held without trial?"},
]

PILLAR_KEYS = [p["key"] for p in PILLARS]
PILLAR_LABELS = {p["key"]: p["label"] for p in PILLARS}
PILLAR_COLORS = {p["key"]: p["color"] for p in PILLARS}
DEFAULT_WEIGHTS = {key: 1.0 / len(PILLAR_KEYS) for key in PILLAR_KEYS}


# --- Scored indicators -----------------------------------------------------
# `lo`/`hi` are fixed scoring bounds, not sample extremes: normalising against
# the sample would restate every historical score the moment a country is added
# and would make the index incapable of saying "bad in absolute terms" rather
# than only "bad relative to these thirty". Values outside the bounds clamp.

METRICS: list[dict[str, Any]] = [
    {
        "key": "turnout_vap_pct",
        "pillar": "electoral",
        "label": "Voter turnout (% of voting-age population)",
        "short": "Turnout",
        "unit": "%",
        "better": "high",
        "lo": 20.0,
        "hi": 95.0,
        "source": "International IDEA Voter Turnout Database",
        "formula": "votes cast / voting-age population",
        "note": (
            "Against VAP rather than registered voters, so a country cannot raise its "
            "turnout by shrinking its electoral roll. Compulsory-voting states (Belgium, "
            "Australia, Brazil) score high here for a legal reason rather than a civic one; "
            "this index does not adjust for that, and the turnout column should be read with "
            "it in mind."
        ),
    },
    {
        "key": "gallagher_index",
        "pillar": "electoral",
        "label": "Gallagher disproportionality index",
        "short": "Disproportionality",
        "unit": "index",
        "better": "low",
        "lo": 1.0,
        "hi": 35.0,
        "source": "Michael Gallagher, Election Indices",
        "formula": "sqrt( 0.5 * sum (v_i - s_i)^2 )",
        "note": (
            "How far the seat allocation departs from the vote. Near 0 under proportional "
            "systems, high under first-past-the-post — it measures the electoral system as "
            "much as the conduct of the election."
        ),
    },
    {
        "key": "constitutional_transfer_integrity",
        "pillar": "electoral",
        "label": "Constitutional transfer integrity",
        "short": "Transfer integrity",
        "unit": "%",
        "better": "high",
        "lo": 0.0,
        "hi": 100.0,
        "source": "Comparative Constitutions Project; succession records",
        "formula": "share of executive transfers made under constitutional rule",
        "note": (
            "Coups, annulled results and irregular successions pull this down; it is the one "
            "indicator here that is a coded judgement about events rather than a published "
            "count, and 24 of 30 countries sit at 100, so it discriminates only at the bottom."
        ),
    },
    {
        "key": "legislative_hhi",
        "pillar": "power_dispersion",
        "label": "Legislative concentration (HHI)",
        "short": "Concentration",
        "unit": "HHI",
        "better": "low",
        "lo": 1200.0,
        "hi": 10000.0,
        "source": "National electoral registries; IPU Parline",
        "formula": "sum of squared seat-share percentages (0-10,000)",
        "note": (
            "10,000 is a single party holding every seat. The Effective Number of Parties is "
            "the same statistic inverted (10000 / HHI) and is published as context rather "
            "than scored a second time."
        ),
    },
    {
        "key": "female_parliament_pct",
        "pillar": "power_dispersion",
        "label": "Women in the national legislature",
        "short": "Gender parity",
        "unit": "%",
        "better": "high",
        "lo": 0.0,
        "hi": 50.0,
        "source": "IPU Parline, Women in National Parliaments",
        "formula": "seats held by women / total seats",
        "note": (
            "Scored against 50% as parity rather than as a maximum. This indicator cannot "
            "tell an elected chamber from an appointed one: the UAE Federal National Council "
            "is half women by appointment and scores 100 here. That is a real limitation, and "
            "the geometric aggregation is what stops it from carrying a country's composite."
        ),
    },
    {
        "key": "gini_coefficient",
        "pillar": "economic_equity",
        "label": "Income Gini coefficient",
        "short": "Gini",
        "unit": "index",
        "better": "low",
        "lo": 22.0,
        "hi": 60.0,
        "source": "World Bank Poverty & Inequality Platform; WID",
        "formula": "standard Lorenz-curve inequality index (0-100)",
        "note": (
            "The single scored indicator in its pillar. The Palma ratio is the same Lorenz "
            "curve summarised differently (rho = +0.99 here) and is published as context "
            "rather than scored, which would have double-weighted income inequality."
        ),
    },
    {
        "key": "internet_shutdown_hours_pc",
        "pillar": "information_telemetry",
        "label": "Internet disruption (person-hours per capita)",
        "short": "Shutdowns",
        "unit": "hrs/cap",
        "better": "low",
        "lo": 0.0,
        "hi": 120.0,
        "source": "OONI; NetBlocks; SFLC; Cloudflare Radar",
        "formula": "sum(outage hours x affected population) / national population",
        "note": "State-ordered outages only. 21 of 30 countries sit at zero.",
    },
    {
        "key": "journalists_detained_per_10m",
        "pillar": "information_telemetry",
        "label": "Journalists imprisoned or killed, per 10M people",
        "short": "Journalists held",
        "unit": "per 10M",
        "better": "low",
        "lo": 0.0,
        "hi": 15.0,
        "source": "Committee to Protect Journalists, annual census",
        "formula": "documented cases / population, per 10 million",
        "note": (
            "A floor detector, not a discriminator: it separates states that jail reporters "
            "from states that do not, and says nothing about the 21 countries at zero."
        ),
    },
    {
        "key": "pretrial_detention_pct",
        "pillar": "justice_rule_of_law",
        "label": "Pre-trial detention rate",
        "short": "Pre-trial",
        "unit": "%",
        "better": "low",
        "lo": 8.0,
        "hi": 80.0,
        "source": "World Prison Brief; UNODC; NCRB",
        "formula": "unconvicted detainees / total prison population",
        "note": "Detention before trial as a share of everyone detained — judicial backlog made countable.",
    },
    {
        "key": "incarceration_rate_per_100k",
        "pillar": "justice_rule_of_law",
        "label": "Incarceration rate",
        "short": "Incarceration",
        "unit": "per 100k",
        "better": "low",
        "lo": 30.0,
        "hi": 750.0,
        "source": "World Prison Brief",
        "formula": "prisoners / population, per 100,000",
        "note": (
            "Rewards states that publish low numbers, including those that detain outside the "
            "prison system or do not report at all. Reads as a carceral-burden measure for "
            "countries with credible statistics and as an artefact for those without."
        ),
    },
]

METRIC_KEYS = [m["key"] for m in METRICS]
METRIC_BY_KEY = {m["key"]: m for m in METRICS}
PILLAR_METRICS = {p: [m["key"] for m in METRICS if m["pillar"] == p] for p in PILLAR_KEYS}

# Published and charted, never scored. See the module docstring: each is
# collinear with a scored indicator to the point of being the same statistic.
CONTEXT_METRICS: list[dict[str, Any]] = [
    {
        "key": "effective_parties",
        "label": "Effective number of parties (ENP)",
        "short": "ENP",
        "unit": "parties",
        "derived_from": "legislative_hhi",
        "note": "Laakso-Taagepera. Derived here as 10000 / HHI, so it cannot disagree with the concentration it inverts.",
    },
    {
        "key": "palma_ratio",
        "label": "Palma ratio",
        "short": "Palma",
        "unit": "ratio",
        "derived_from": None,
        "note": "Income share of the top 10% over the bottom 40%. Correlates with Gini at +0.99 across this panel.",
    },
]


# --- Tiers -----------------------------------------------------------------
# Cut at 80 / 65 / 50 / 35 on the composite. The bottom tier was unreachable
# under the arithmetic mean — no country in the panel scored below 39 — which
# is a tier that exists only in the legend. Under geometric aggregation China
# (28.4) and Saudi Arabia (31.6) reach it, which is the calibration check that
# the boundary is doing work.

TIERS: list[dict[str, Any]] = [
    {"lower": 80.0, "label": "Robust High-Parity Democracy", "status": "good"},
    {"lower": 65.0, "label": "Established Democracy", "status": "good"},
    {"lower": 50.0, "label": "Moderate / Flawed System", "status": "warning"},
    {"lower": 35.0, "label": "Hybrid / Constrained Regime", "status": "serious"},
    {"lower": 0.0, "label": "Closed / Authoritarian Regime", "status": "critical"},
]

SCALE_MIN = 0.0
SCALE_MAX = 100.0

# Floor applied to a pillar score before the log. A pillar of 0 would otherwise
# annihilate the composite and throw away every other measurement in the row;
# 1.0 keeps a true zero devastating without making it total.
PILLAR_FLOOR = 1.0


def tier_for(score: float) -> dict[str, Any]:
    for tier in TIERS:
        if score >= tier["lower"]:
            return tier
    return TIERS[-1]


def level_for(score: float) -> tuple[str, str]:
    tier = tier_for(score)
    return tier["label"], tier["status"]


def band_positions() -> list[dict]:
    """Tier boundaries as percentages along the 0-100 gauge track."""
    return [
        {"label": t["label"], "lower": t["lower"], "status": t["status"],
         "pct": round(t["lower"], 2)}
        for t in reversed(TIERS)
        if t["lower"] > SCALE_MIN
    ]


def scale_pct(score: float) -> float:
    return max(0.0, min(100.0, score))


# --- Data ------------------------------------------------------------------

_history_cache: Optional[dict] = None
_history_lock = threading.Lock()


def _load() -> dict:
    global _history_cache
    with _history_lock:
        if _history_cache is not None:
            return _history_cache
    try:
        with open(HISTORY_JSON, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        payload = {"years": [], "records": [], "provenance": {}, "generated_at": ""}
    with _history_lock:
        _history_cache = payload
    return payload


def get_meta() -> dict:
    payload = _load()
    return {
        "generated_at": payload.get("generated_at", ""),
        "provenance": payload.get("provenance", {}),
        "years": payload.get("years", []),
    }


def available_years() -> list[int]:
    return list(_load().get("years") or [])


def latest_year() -> int:
    years = available_years()
    return years[-1] if years else 0


def _records() -> list[dict]:
    return _load().get("records") or []


# --- Countries -------------------------------------------------------------
# GDP rank is the panel's selection rule (top 30 economies) and is carried so
# the page can say what the sample is. `regime_type` is descriptive text shown
# beside a country, never an input to the score — the whole point of this index
# is that nothing about a country's classification feeds its number.

COUNTRIES: list[dict[str, Any]] = [
    {"code": "USA", "name": "United States", "region": "North America", "gdp_rank": 1, "regime_type": "Presidential constitutional republic"},
    {"code": "CHN", "name": "China", "region": "Asia", "gdp_rank": 2, "regime_type": "One-party socialist republic"},
    {"code": "DEU", "name": "Germany", "region": "Europe", "gdp_rank": 3, "regime_type": "Federal parliamentary republic"},
    {"code": "JPN", "name": "Japan", "region": "Asia", "gdp_rank": 4, "regime_type": "Parliamentary constitutional monarchy"},
    {"code": "IND", "name": "India", "region": "Asia", "gdp_rank": 5, "regime_type": "Federal parliamentary republic"},
    {"code": "GBR", "name": "United Kingdom", "region": "Europe", "gdp_rank": 6, "regime_type": "Parliamentary constitutional monarchy"},
    {"code": "FRA", "name": "France", "region": "Europe", "gdp_rank": 7, "regime_type": "Semi-presidential republic"},
    {"code": "ITA", "name": "Italy", "region": "Europe", "gdp_rank": 8, "regime_type": "Parliamentary republic"},
    {"code": "BRA", "name": "Brazil", "region": "South America", "gdp_rank": 9, "regime_type": "Federal presidential republic"},
    {"code": "CAN", "name": "Canada", "region": "North America", "gdp_rank": 10, "regime_type": "Federal parliamentary constitutional monarchy"},
    {"code": "RUS", "name": "Russia", "region": "Europe / Asia", "gdp_rank": 11, "regime_type": "Semi-presidential federation"},
    {"code": "MEX", "name": "Mexico", "region": "North America", "gdp_rank": 12, "regime_type": "Federal presidential republic"},
    {"code": "AUS", "name": "Australia", "region": "Oceania", "gdp_rank": 13, "regime_type": "Federal parliamentary constitutional monarchy"},
    {"code": "KOR", "name": "South Korea", "region": "Asia", "gdp_rank": 14, "regime_type": "Presidential republic"},
    {"code": "ESP", "name": "Spain", "region": "Europe", "gdp_rank": 15, "regime_type": "Parliamentary constitutional monarchy"},
    {"code": "IDN", "name": "Indonesia", "region": "Asia", "gdp_rank": 16, "regime_type": "Presidential republic"},
    {"code": "NLD", "name": "Netherlands", "region": "Europe", "gdp_rank": 17, "regime_type": "Parliamentary constitutional monarchy"},
    {"code": "TUR", "name": "Turkey", "region": "Europe / Asia", "gdp_rank": 18, "regime_type": "Presidential republic"},
    {"code": "SAU", "name": "Saudi Arabia", "region": "Middle East", "gdp_rank": 19, "regime_type": "Absolute monarchy"},
    {"code": "CHE", "name": "Switzerland", "region": "Europe", "gdp_rank": 20, "regime_type": "Federal directorial republic"},
    {"code": "POL", "name": "Poland", "region": "Europe", "gdp_rank": 21, "regime_type": "Semi-presidential republic"},
    {"code": "ARG", "name": "Argentina", "region": "South America", "gdp_rank": 22, "regime_type": "Federal presidential republic"},
    {"code": "SWE", "name": "Sweden", "region": "Europe", "gdp_rank": 23, "regime_type": "Parliamentary constitutional monarchy"},
    {"code": "BEL", "name": "Belgium", "region": "Europe", "gdp_rank": 24, "regime_type": "Federal parliamentary constitutional monarchy"},
    {"code": "NOR", "name": "Norway", "region": "Europe", "gdp_rank": 25, "regime_type": "Parliamentary constitutional monarchy"},
    {"code": "THA", "name": "Thailand", "region": "Asia", "gdp_rank": 26, "regime_type": "Parliamentary constitutional monarchy"},
    {"code": "ISR", "name": "Israel", "region": "Middle East", "gdp_rank": 27, "regime_type": "Parliamentary republic"},
    {"code": "IRL", "name": "Ireland", "region": "Europe", "gdp_rank": 28, "regime_type": "Parliamentary republic"},
    {"code": "SGP", "name": "Singapore", "region": "Asia", "gdp_rank": 29, "regime_type": "Dominant-party parliamentary republic"},
    {"code": "ARE", "name": "United Arab Emirates", "region": "Middle East", "gdp_rank": 30, "regime_type": "Federal absolute monarchy"},
]

COUNTRY_BY_CODE = {c["code"]: c for c in COUNTRIES}
REGIONS = sorted({c["region"] for c in COUNTRIES})


# --- Scoring ---------------------------------------------------------------


def normalise(metric_key: str, value: Optional[float]) -> Optional[float]:
    """One raw indicator to a 0-100 score, clamped to its fixed bounds."""
    if value is None:
        return None
    spec = METRIC_BY_KEY[metric_key]
    lo, hi = spec["lo"], spec["hi"]
    if hi == lo:
        return 100.0
    clamped = max(lo, min(hi, float(value)))
    if spec["better"] == "high":
        score = (clamped - lo) / (hi - lo) * 100.0
    else:
        score = (hi - clamped) / (hi - lo) * 100.0
    return round(score, 2)


def normalise_weights(weights: Optional[dict[str, float]]) -> dict[str, float]:
    """Non-negative pillar weights summing to 1, over all five pillars.

    Every pillar is always present. The engine this replaces defaulted an
    unmentioned pillar to 0.20 *after* normalising the mentioned ones, so
    `?w_electoral=100` produced weights totalling 1.8 and a composite of 166.9
    on a scale documented as 0-100. A weight set is a complete set here, and a
    missing pillar means zero, not "the old default".
    """
    if not weights:
        return dict(DEFAULT_WEIGHTS)
    cleaned = {key: max(0.0, float(weights.get(key, 0.0) or 0.0)) for key in PILLAR_KEYS}
    total = sum(cleaned.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {key: value / total for key, value in cleaned.items()}


def composite_from_pillars(pillar_scores: dict[str, float],
                           weights: Optional[dict[str, float]] = None) -> float:
    """Weighted geometric mean of the five pillar scores.

    exp( sum w_p * ln(max(score_p, floor)) ). A pillar carrying zero weight is
    dropped from the product rather than contributing ln(x) * 0, which is the
    same thing but avoids a spurious term when a reader zeroes a pillar out.
    """
    w = normalise_weights(weights)
    total = 0.0
    used = 0.0
    for key in PILLAR_KEYS:
        weight = w.get(key, 0.0)
        if weight <= 0:
            continue
        total += weight * math.log(max(pillar_scores.get(key, 0.0), PILLAR_FLOOR))
        used += weight
    if used <= 0:
        return 0.0
    return round(math.exp(total / used), 2)


def arithmetic_composite(pillar_scores: dict[str, float],
                         weights: Optional[dict[str, float]] = None) -> float:
    """The rejected aggregation, kept so the page can show the difference.

    Published beside the headline score on the methodology tab: the gap between
    the two is the compensability an arithmetic mean would have granted, and it
    is the clearest available evidence for why this index does not use one.
    """
    w = normalise_weights(weights)
    return round(sum(pillar_scores.get(k, 0.0) * w.get(k, 0.0) for k in PILLAR_KEYS), 2)


def score_record(record: dict, weights: Optional[dict[str, float]] = None) -> dict:
    """Normalised metrics, pillar means and the composite for one country-year."""
    anchored = set(record.get("anchored") or [])

    metrics: dict[str, dict] = {}
    for spec in METRICS:
        key = spec["key"]
        raw = record.get(key)
        metrics[key] = {
            "raw": raw,
            "score": normalise(key, raw),
            "anchor": key in anchored,
        }

    # Context columns. ENP is recomputed from HHI rather than read from the
    # source column so the two cannot contradict each other; see the docstring.
    hhi = record.get("legislative_hhi") or 0.0
    context = {
        "effective_parties": {
            "raw": round(10000.0 / hhi, 2) if hhi > 0 else None,
            "reported": record.get("effective_parties"),
            "anchor": "legislative_hhi" in anchored,
        },
        "palma_ratio": {
            "raw": record.get("palma_ratio"),
            "reported": record.get("palma_ratio"),
            "anchor": "palma_ratio" in anchored,
        },
    }

    pillar_scores: dict[str, float] = {}
    for pillar, keys in PILLAR_METRICS.items():
        vals = [metrics[k]["score"] for k in keys if metrics[k]["score"] is not None]
        pillar_scores[pillar] = round(sum(vals) / len(vals), 2) if vals else 0.0

    composite = composite_from_pillars(pillar_scores, weights)
    tier = tier_for(composite)
    meta = COUNTRY_BY_CODE.get(record["country_code"], {})

    # How much of this row rests on a source rather than on interpolation. Two
    # countries can hold the same score on very different evidence, and the row
    # should say so.
    scored_cells = len(METRIC_KEYS)
    anchor_hits = sum(1 for k in METRIC_KEYS if k in anchored)

    return {
        "country_code": record["country_code"],
        "country_name": meta.get("name", record["country_code"]),
        "region": meta.get("region", ""),
        "gdp_rank": meta.get("gdp_rank", 99),
        "regime_type": meta.get("regime_type", ""),
        "year": record["year"],
        "composite": composite,
        "composite_arithmetic": arithmetic_composite(pillar_scores, weights),
        "tier": tier["label"],
        "status": tier["status"],
        "pillars": pillar_scores,
        "metrics": metrics,
        "context": context,
        "anchor_share": round(anchor_hits / scored_cells, 3) if scored_cells else 0.0,
        # External comparator, never an input. See the V-Dem section below.
        "vdem_score": vdem_score(record["country_code"], record["year"]),
        "vdem_rank": vdem_rank(record["country_code"], record["year"]),
    }


def index_for_year(year: int, weights: Optional[dict[str, float]] = None) -> list[dict]:
    """Every country ranked for one year, rank 1 = highest composite."""
    rows = [score_record(r, weights) for r in _records() if r["year"] == int(year)]
    rows.sort(key=lambda r: (-r["composite"], r["country_name"]))
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    return rows


def country_history(code: str, weights: Optional[dict[str, float]] = None) -> list[dict]:
    """One country's full 2000-2024 trajectory, oldest first."""
    code = code.upper()
    rows = [score_record(r, weights) for r in _records() if r["country_code"] == code]
    rows.sort(key=lambda r: r["year"])
    return rows


def rank_history(weights: Optional[dict[str, float]] = None) -> dict[str, list[Optional[int]]]:
    """Each country's rank in every year, aligned to available_years().

    Built by ranking each year once rather than by ranking each country's row
    against the year it sits in, which would be 30x the work for the same answer.
    """
    ranks: dict[str, list[Optional[int]]] = {c["code"]: [] for c in COUNTRIES}
    for year in available_years():
        by_code = {r["country_code"]: r["rank"] for r in index_for_year(year, weights)}
        for code in ranks:
            ranks[code].append(by_code.get(code))
    return ranks


def score_history(weights: Optional[dict[str, float]] = None) -> dict[str, list[Optional[float]]]:
    """Each country's composite in every year, aligned to available_years()."""
    series: dict[str, list[Optional[float]]] = {c["code"]: [] for c in COUNTRIES}
    for year in available_years():
        by_code = {r["country_code"]: r["composite"] for r in index_for_year(year, weights)}
        for code in series:
            series[code].append(by_code.get(code))
    return series


def panel_average(weights: Optional[dict[str, float]] = None) -> list[dict]:
    """The unweighted mean composite and mean pillar scores per year.

    Unweighted across countries on purpose: GDP-weighting it would let the two
    largest economies set the global trend line, and the question the line
    answers is "how are these thirty states doing", not "how is world GDP
    governed".
    """
    out = []
    for year in available_years():
        rows = index_for_year(year, weights)
        if not rows:
            continue
        out.append({
            "year": year,
            "mean": round(sum(r["composite"] for r in rows) / len(rows), 2),
            "median": round(sorted(r["composite"] for r in rows)[len(rows) // 2], 2),
            "pillars": {
                p: round(sum(r["pillars"][p] for r in rows) / len(rows), 2)
                for p in PILLAR_KEYS
            },
            # The spread is the part a mean hides. A flat global average with a
            # widening spread is divergence, not stability.
            "spread": round(
                max(r["composite"] for r in rows) - min(r["composite"] for r in rows), 2
            ),
        })
    return out


def movers(first_year: Optional[int] = None, last_year: Optional[int] = None,
           weights: Optional[dict[str, float]] = None) -> list[dict]:
    """Change in composite and rank between two years, biggest fall first."""
    years = available_years()
    if not years:
        return []
    first = first_year or years[0]
    last = last_year or years[-1]

    start = {r["country_code"]: r for r in index_for_year(first, weights)}
    end = {r["country_code"]: r for r in index_for_year(last, weights)}

    out = []
    for code, row in end.items():
        base = start.get(code)
        if not base:
            continue
        out.append({
            "country_code": code,
            "country_name": row["country_name"],
            "region": row["region"],
            "from_year": first,
            "to_year": last,
            "from_score": base["composite"],
            "to_score": row["composite"],
            "delta": round(row["composite"] - base["composite"], 2),
            "from_rank": base["rank"],
            "to_rank": row["rank"],
            # Rank improves as the number falls, so this is signed to read the
            # same direction as the score delta: positive = moved up.
            "rank_delta": base["rank"] - row["rank"],
        })
    out.sort(key=lambda r: r["delta"])
    return out


def pillar_correlations(year: Optional[int] = None) -> list[dict]:
    """Spearman correlation between every pair of scored indicators.

    Published because two of the source dataset's twelve indicators turned out
    to be restatements of two others, and the only reason anyone knows that is
    that somebody computed this. Leaving it on the page keeps the next
    redundancy visible rather than buried in a commit message.
    """
    rows = [r for r in _records() if r["year"] == int(year or latest_year())]
    if len(rows) < 3:
        return []

    def ranked(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0  # average rank over the tied block
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    series = {k: ranked([float(r[k]) for r in rows]) for k in METRIC_KEYS}
    n = len(rows)

    out = []
    for i, a in enumerate(METRIC_KEYS):
        for b in METRIC_KEYS[i + 1:]:
            xa, xb = series[a], series[b]
            ma = sum(xa) / n
            mb = sum(xb) / n
            cov = sum((xa[k] - ma) * (xb[k] - mb) for k in range(n))
            va = math.sqrt(sum((xa[k] - ma) ** 2 for k in range(n)))
            vb = math.sqrt(sum((xb[k] - mb) ** 2 for k in range(n)))
            rho = cov / (va * vb) if va and vb else 0.0
            out.append({
                "a": a, "b": b,
                "a_label": METRIC_BY_KEY[a]["short"],
                "b_label": METRIC_BY_KEY[b]["short"],
                "rho": round(rho, 3),
            })
    out.sort(key=lambda r: -abs(r["rho"]))
    return out


def metric_dispersion(year: Optional[int] = None) -> list[dict]:
    """Per-indicator spread of the normalised scores, plus saturation counts.

    An indicator on which 21 of 30 countries score exactly 100 is not measuring
    those 21; it is a floor detector. That is a fair thing for an indicator to
    be, and a reader is entitled to know which ones are.
    """
    rows = [r for r in _records() if r["year"] == int(year or latest_year())]
    if not rows:
        return []

    out = []
    for spec in METRICS:
        key = spec["key"]
        scores = [normalise(key, r[key]) for r in rows]
        scores = [s for s in scores if s is not None]
        if not scores:
            continue
        mean = sum(scores) / len(scores)
        sd = math.sqrt(sum((s - mean) ** 2 for s in scores) / len(scores))
        raws = [float(r[key]) for r in rows]
        out.append({
            "key": key,
            "label": spec["label"],
            "short": spec["short"],
            "pillar": spec["pillar"],
            "unit": spec["unit"],
            "mean": round(mean, 1),
            "sd": round(sd, 1),
            "at_ceiling": sum(1 for s in scores if s >= 99.99),
            "at_floor": sum(1 for s in scores if s <= 0.01),
            "n": len(scores),
            "raw_min": round(min(raws), 2),
            "raw_max": round(max(raws), 2),
            # Values pinned by the scoring bounds rather than by their own
            # magnitude. A non-zero count means the bounds, not the country,
            # decided part of the column.
            "clamped": sum(1 for v in raws if v < spec["lo"] or v > spec["hi"]),
        })
    out.sort(key=lambda r: r["sd"])
    return out


def anchor_coverage() -> list[dict]:
    """Per-country share of scored cells that sit on a source, across all years."""
    by_code: dict[str, list[int]] = {}
    for record in _records():
        anchored = set(record.get("anchored") or [])
        hits = by_code.setdefault(record["country_code"], [0, 0])
        hits[0] += sum(1 for k in METRIC_KEYS if k in anchored)
        hits[1] += len(METRIC_KEYS)

    out = []
    for code, (hits, total) in by_code.items():
        meta = COUNTRY_BY_CODE.get(code, {})
        out.append({
            "country_code": code,
            "country_name": meta.get("name", code),
            "anchor_cells": hits,
            "total_cells": total,
            "share": round(hits / total, 3) if total else 0.0,
        })
    out.sort(key=lambda r: r["share"])
    return out


def anchor_years_by_metric() -> dict[str, list[int]]:
    """Years in which *any* country has a source-backed value, per indicator.

    Drives the shading under the trajectory chart. Per-indicator rather than
    per-country because the chart plots a composite, and a composite is
    anchored in a year to the extent that anything under it is.
    """
    out: dict[str, set[int]] = {k: set() for k in METRIC_KEYS}
    for record in _records():
        for key in record.get("anchored") or []:
            if key in out:
                out[key].add(record["year"])
    return {k: sorted(v) for k, v in out.items()}


def anchor_density() -> list[dict]:
    """Share of the panel's scored cells that are source-backed, per year.

    The chart this feeds is the honest caption for every other chart on the
    page: election years spike, the years between them are inference.
    """
    per_year: dict[int, list[int]] = {}
    for record in _records():
        anchored = set(record.get("anchored") or [])
        slot = per_year.setdefault(record["year"], [0, 0])
        slot[0] += sum(1 for k in METRIC_KEYS if k in anchored)
        slot[1] += len(METRIC_KEYS)
    return [
        {"year": year, "share": round(hits / total, 4) if total else 0.0,
         "anchor_cells": hits, "total_cells": total}
        for year, (hits, total) in sorted(per_year.items())
    ]


# --- V-Dem, as an external comparator --------------------------------------
# Not an input. The module docstring picks a fight with expert-coded indices and
# then declines to show one, which leaves the reader no way to check the claim.
# V-Dem's Liberal Democracy Index (v2x_libdem, 0-1) is carried beside the HMDI
# rank so the disagreement is visible in the same row: where the two ranks part
# company is exactly where "the countable things" and "what country experts
# judge" are telling different stories, and that gap is the most informative
# thing this page can put in front of a reader.
#
# The rank shown is a rank within *these thirty*, recomputed from the raw
# scores, not V-Dem's global rank over 179 countries -- a global rank next to a
# 30-country rank would be two different numbers presented as comparable.
# Ties share the lower rank (standard competition ranking).
#
# See scripts/build_vdem_reference.py, which writes app/data/vdem_libdem.json.

_vdem_cache: Optional[dict] = None
_vdem_lock = threading.Lock()


def _vdem() -> dict:
    global _vdem_cache
    with _vdem_lock:
        if _vdem_cache is not None:
            return _vdem_cache
    try:
        with open(VDEM_JSON, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        payload = {"values": {}, "years": []}

    # Rank within the panel, per year, computed once at load.
    ranks: dict[int, dict[str, int]] = {}
    for year in payload.get("years") or []:
        scored = [
            (code, series.get(str(year)))
            for code, series in (payload.get("values") or {}).items()
        ]
        scored = [(c, v) for c, v in scored if v is not None]
        scored.sort(key=lambda cv: (-cv[1], cv[0]))
        by_code: dict[str, int] = {}
        for i, (code, value) in enumerate(scored):
            prev = scored[i - 1] if i else None
            by_code[code] = by_code[prev[0]] if prev and prev[1] == value else i + 1
        ranks[int(year)] = by_code
    payload["_ranks"] = ranks

    with _vdem_lock:
        _vdem_cache = payload
    return payload


def vdem_meta() -> dict:
    payload = _vdem()
    return {k: payload[k] for k in
            ("indicator", "label", "scale", "release", "source", "source_url")
            if k in payload}


def vdem_score(code: str, year: int) -> Optional[float]:
    return (_vdem().get("values") or {}).get(code.upper(), {}).get(str(int(year)))


def vdem_rank(code: str, year: int) -> Optional[int]:
    return _vdem()["_ranks"].get(int(year), {}).get(code.upper())


def vdem_table() -> dict:
    """Scores and in-panel ranks per country, aligned to available_years().

    Shipped to the browser in this shape because the page re-ranks the HMDI on
    every weight change and needs the comparator column to survive that without
    a round trip. V-Dem does not move when the sliders move -- that is the
    point of it being there.
    """
    years = available_years()
    values = _vdem().get("values") or {}
    ranks = _vdem()["_ranks"]
    return {
        "years": years,
        "meta": vdem_meta(),
        "scores": {c["code"]: [values.get(c["code"], {}).get(str(y)) for y in years]
                   for c in COUNTRIES},
        "ranks": {c["code"]: [ranks.get(y, {}).get(c["code"]) for y in years]
                  for c in COUNTRIES},
    }


def _rank_vector(values: list[float]) -> list[float]:
    """Ranks with tied blocks averaged, as Spearman requires."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def vdem_agreement(year: Optional[int] = None,
                   weights: Optional[dict[str, float]] = None) -> dict:
    """Spearman rho between the HMDI composite and V-Dem, over the panel.

    One number for "how much does counting agree with expert coding". It is
    reported rather than optimised against: a rho of 1.0 would mean this index
    had reproduced V-Dem by a longer route and added nothing, and a rho near 0
    would mean one of the two is measuring something other than democracy.
    """
    year = int(year or latest_year())
    pairs = []
    for row in index_for_year(year, weights):
        v = vdem_score(row["country_code"], year)
        if v is not None:
            pairs.append((row["composite"], v))
    n = len(pairs)
    if n < 3:
        return {"year": year, "n": n, "rho": None}

    xa = _rank_vector([p[0] for p in pairs])
    xb = _rank_vector([p[1] for p in pairs])
    ma = sum(xa) / n
    mb = sum(xb) / n
    cov = sum((xa[k] - ma) * (xb[k] - mb) for k in range(n))
    va = math.sqrt(sum((xa[k] - ma) ** 2 for k in range(n)))
    vb = math.sqrt(sum((xb[k] - mb) ** 2 for k in range(n)))
    return {"year": year, "n": n,
            "rho": round(cov / (va * vb), 3) if va and vb else None}


def vdem_divergence(year: Optional[int] = None,
                    weights: Optional[dict[str, float]] = None) -> list[dict]:
    """Where the two rankings disagree most, for one year.

    Positive `gap` means the country places better on hard counts than on
    expert coding; negative means the opposite. Sorted by absolute gap, so the
    rows that lead the table are the ones that need explaining.
    """
    year = int(year or latest_year())
    out = []
    for row in index_for_year(year, weights):
        vr = vdem_rank(row["country_code"], year)
        if vr is None:
            continue
        out.append({
            "country_code": row["country_code"],
            "country_name": row["country_name"],
            "hmdi_rank": row["rank"],
            "hmdi_score": row["composite"],
            "vdem_rank": vr,
            "vdem_score": vdem_score(row["country_code"], year),
            "gap": vr - row["rank"],
        })
    out.sort(key=lambda r: -abs(r["gap"]))
    return out


# --- Executive summary ------------------------------------------------------
#
# The page ends in prose, and the prose is generated from the same series the
# charts are drawn from so it cannot drift away from them. Nothing here is
# written down as a sentence in the template that a later data refresh could
# make false: every number, every country name and every direction word below
# comes out of this function.
#
# The decade change is decomposed rather than asserted. The composite is a
# weighted geometric mean, so ln C = sum(w_k ln p_k) is exactly additive across
# the five pillars, and converting the log change back into points with the
# log-mean factor L = (C1 - C0) / (ln C1 - ln C0) leaves the five contributions
# summing to the total change with no residual. That is the LMDI-I index
# decomposition; it is used here because the alternative -- quoting each
# pillar's own move and letting the reader assume they add up -- would be
# arithmetic the index cannot actually perform.

EXEC_WINDOW_YEARS = 10


def _format_raw(value: Optional[float], unit: Optional[str]) -> str:
    """One indicator value as prose. Precision follows magnitude; a unit of
    None prints the bare number, for the left half of a "from -> to" pair."""
    if value is None:
        return "n/a"
    magnitude = abs(value)
    if magnitude == 0:
        text = "0"
    elif magnitude >= 100:
        text = f"{value:,.0f}"
    elif magnitude >= 1:
        text = f"{value:.1f}"
    else:
        text = f"{value:.2f}"
    if unit == "%":
        return text + "%"
    if not unit or unit == "index":
        return text
    return f"{text} {unit}"


def _log_mean(a: float, b: float) -> float:
    """LMDI weight. Degenerate at a == b, where the limit is the value itself."""
    if a <= 0 or b <= 0:
        return 0.0
    if abs(a - b) < 1e-9:
        return a
    return (b - a) / (math.log(b) - math.log(a))


def _decompose(start_row: dict, end_row: dict,
               weights: dict[str, float]) -> dict[str, float]:
    """Points of one country's move attributable to each pillar."""
    c0 = start_row["composite"]
    c1 = end_row["composite"]
    lw = _log_mean(c0, c1)
    out = {}
    for key in PILLAR_KEYS:
        p0 = max(start_row["pillars"][key], PILLAR_FLOOR)
        p1 = max(end_row["pillars"][key], PILLAR_FLOOR)
        out[key] = lw * weights[key] * math.log(p1 / p0)
    return out


def executive_summary(weights: Optional[dict[str, float]] = None) -> dict:
    """Every figure the closing summary quotes, computed from the series.

    Read over the last EXEC_WINDOW_YEARS of the panel rather than the full
    record: the 2000-2024 change is dominated by the accession of source
    coverage in the middle of the series, and the decade is the window a reader
    can actually check against their own memory of events.
    """
    w = normalise_weights(weights)
    years = available_years()
    end = years[-1]
    start = max([y for y in years if y <= end - EXEC_WINDOW_YEARS] or [years[0]])

    start_rows = {r["country_code"]: r for r in index_for_year(start, weights)}
    end_rows = {r["country_code"]: r for r in index_for_year(end, weights)}
    codes = [c for c in end_rows if c in start_rows]
    n = len(codes)

    panel = panel_average(weights)
    first = next(r for r in panel if r["year"] == start)
    last = next(r for r in panel if r["year"] == end)

    # --- What moved, and how much of the move each pillar owns --------------
    contribs = {k: 0.0 for k in PILLAR_KEYS}
    for code in codes:
        for key, value in _decompose(start_rows[code], end_rows[code], w).items():
            contribs[key] += value / n

    # Indicator-level movement, panel-wide. A pillar is the plain mean of its
    # indicators, so an indicator's mean score change is a component of its
    # pillar's move rather than a correlate of it.
    metric_moves = []
    for spec in METRICS:
        key = spec["key"]
        deltas = []
        for code in codes:
            a = start_rows[code]["metrics"][key]["score"]
            b = end_rows[code]["metrics"][key]["score"]
            if a is not None and b is not None:
                deltas.append(b - a)
        if not deltas:
            continue
        worsened = sum(1 for d in deltas if d < -0.5)
        improved = sum(1 for d in deltas if d > 0.5)
        metric_moves.append({
            "key": key,
            "label": spec["label"],
            "short": spec["short"],
            "pillar": spec["pillar"],
            "pillar_label": PILLAR_LABELS[spec["pillar"]],
            "unit": spec["unit"],
            "delta": round(sum(deltas) / len(deltas), 2),
            "improved": improved,
            "worsened": worsened,
        })
    metric_moves.sort(key=lambda m: -abs(m["delta"]))

    drivers = []
    for key in PILLAR_KEYS:
        inside = [m for m in metric_moves if m["pillar"] == key]
        drivers.append({
            "key": key,
            "label": PILLAR_LABELS[key],
            "short": next(p["short"] for p in PILLARS if p["key"] == key),
            "contribution": round(contribs[key], 2),
            "from": first["pillars"][key],
            "to": last["pillars"][key],
            "delta": round(last["pillars"][key] - first["pillars"][key], 2),
            "weight": round(w[key], 3),
            "top_metric": inside[0] if inside else None,
        })
    drivers.sort(key=lambda d: -abs(d["contribution"]))

    # --- Who moved -----------------------------------------------------------
    moves = []
    for code in codes:
        a = start_rows[code]
        b = end_rows[code]
        per_pillar = _decompose(a, b, w)
        ordered = sorted(per_pillar.items(), key=lambda kv: -abs(kv[1]))
        reasons = []
        for key, value in ordered[:2]:
            if abs(value) < 0.05:
                continue
            # The loudest indicator inside that pillar, for this country.
            best = None
            for mk in PILLAR_METRICS[key]:
                s0 = a["metrics"][mk]["score"]
                s1 = b["metrics"][mk]["score"]
                if s0 is None or s1 is None:
                    continue
                if best is None or abs(s1 - s0) > abs(best["delta"]):
                    best = {
                        "key": mk,
                        "label": METRIC_BY_KEY[mk]["short"],
                        "unit": METRIC_BY_KEY[mk]["unit"],
                        "delta": round(s1 - s0, 2),
                        "raw_from": a["metrics"][mk]["raw"],
                        "raw_to": b["metrics"][mk]["raw"],
                        # Formatted here rather than in the template: the ten
                        # indicators run from ratios near 1 to counts in the
                        # thousands, and one Jinja format string cannot serve
                        # both without printing "8100.00" or "1".
                        # Only the second value carries the unit: "700 per
                        # 100k -> 528 per 100k" says it twice for no one.
                        "from_display": _format_raw(a["metrics"][mk]["raw"], None),
                        "to_display": _format_raw(b["metrics"][mk]["raw"], METRIC_BY_KEY[mk]["unit"]),
                    }
            reasons.append({
                "pillar": key,
                "label": PILLAR_LABELS[key],
                "short": next(p["short"] for p in PILLARS if p["key"] == key),
                "points": round(value, 2),
                "metric": best,
            })
        moves.append({
            "country_code": code,
            "country_name": b["country_name"],
            "from_score": a["composite"],
            "to_score": b["composite"],
            "delta": round(b["composite"] - a["composite"], 2),
            "from_rank": a["rank"],
            "to_rank": b["rank"],
            "rank_delta": a["rank"] - b["rank"],
            "from_tier": a["tier"],
            "to_tier": b["tier"],
            "tier_changed": a["tier"] != b["tier"],
            "reasons": reasons,
        })
    moves.sort(key=lambda m: -m["delta"])

    risers = [m for m in moves if m["delta"] > 0][:3]
    fallers = [m for m in moves if m["delta"] < 0]
    fallers = sorted(fallers, key=lambda m: m["delta"])[:3]
    improved_count = sum(1 for m in moves if m["delta"] > 0.5)
    declined_count = sum(1 for m in moves if m["delta"] < -0.5)
    flat_count = n - improved_count - declined_count

    # --- Is the panel converging or pulling apart? ---------------------------
    spread_delta = round(last["spread"] - first["spread"], 2)

    # --- Evidence base -------------------------------------------------------
    density = anchor_density()
    density_by_year = {d["year"]: d for d in density}
    total_cells = sum(d["total_cells"] for d in density)
    anchor_cells = sum(d["anchor_cells"] for d in density)
    thinnest = min(anchor_coverage(), key=lambda r: r["share"])

    agreement = vdem_agreement(end, weights)
    divergence = vdem_divergence(end, weights)
    over = [d for d in divergence if d["gap"] > 0][:2]     # better on counts
    under = [d for d in divergence if d["gap"] < 0][:2]    # better on experts

    return {
        "start_year": start,
        "end_year": end,
        "span": end - start,
        "n": n,
        "mean_from": first["mean"],
        "mean_to": last["mean"],
        "mean_delta": round(last["mean"] - first["mean"], 2),
        "direction": "risen" if last["mean"] - first["mean"] > 0.05
                     else "fallen" if last["mean"] - first["mean"] < -0.05
                     else "held flat",
        "spread_from": first["spread"],
        "spread_to": last["spread"],
        "spread_delta": spread_delta,
        "spread_direction": "wider" if spread_delta > 0 else "narrower",
        "drivers": drivers,
        "metric_moves": metric_moves,
        "top_metric_up": next((m for m in metric_moves if m["delta"] > 0), None),
        "top_metric_down": next((m for m in metric_moves if m["delta"] < 0), None),
        "risers": risers,
        "fallers": fallers,
        "improved_count": improved_count,
        "declined_count": declined_count,
        "flat_count": flat_count,
        "tier_changes": [m for m in moves if m["tier_changed"]],
        "anchor_share": round(anchor_cells / total_cells, 3) if total_cells else 0.0,
        "anchor_share_end": density_by_year[end]["share"] if end in density_by_year else 0.0,
        "thinnest_country": thinnest,
        "vdem_rho": agreement.get("rho"),
        "vdem_year": agreement.get("year"),
        "vdem_over": over,
        "vdem_under": under,
        "vdem_release": vdem_meta().get("release"),
    }


# --- Snapshot for the shared UI --------------------------------------------


def compute_snapshot(weights: Optional[dict[str, float]] = None) -> CompositeResult:
    """Panel mean for the most recent year, as the CompositeResult the shared
    header and home card expect.

    The headline figure for a multi-country index is the panel average rather
    than any one country's score: the index measures thirty states, and picking
    one of them for the top of the page would be an editorial claim the data
    does not make.
    """
    year = latest_year()
    rows = index_for_year(year, weights)
    mean = round(sum(r["composite"] for r in rows) / len(rows), 1) if rows else 0.0
    label, status = level_for(mean)
    return CompositeResult(
        score=mean,
        level_label=label,
        level_status=status,
        components=[],
        week_start=str(year),
        degraded=False,
        stale_weight=0.0,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def headline() -> dict:
    """Home-page report card figure."""
    year = latest_year()
    rows = index_for_year(year)
    if not rows:
        return {"value": None, "unit": None, "as_of": ""}
    mean = sum(r["composite"] for r in rows) / len(rows)
    return {"value": f"{mean:.1f}", "unit": "panel mean", "as_of": str(year)}
