"""Generic composite-index engine.

Any weekly stress/crisis index (Hormuz, Geo Politics, ...) is built the same way:
a set of weighted components, each normalized to a stress score against a
baseline, capped at a realistic crisis maximum, then summed into a composite
that starts at 100 (baseline/calm) and rises with stress.

    composite = 100 + sum(weight * stress_score)

Directionality
--------------
By default the index is *one-sided*: stress scores are clamped to [0, 100], so
conditions calmer than baseline register as 0 rather than as negative stress,
and the composite has a hard floor of 100. That is a deliberate design choice
for a crisis index (it measures stress, not wellbeing), but it means the index
cannot express de-escalation below baseline.

A component can opt into two-sided scoring by setting `floor` below 0 (e.g.
`floor=-50`), which lets calmer-than-baseline readings subtract from the
composite. Changing this for an existing index restates its history, so it is
per-component and off by default.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class Component:
    key: str
    label: str
    weight: float  # 0-1, all components should sum to 1.0
    source: str  # human-readable data source, shown in the UI
    cap_pct: float  # % change from baseline that equals 100 stress
    invert: bool = False  # True when a DECREASE from baseline is the stress direction
    unit: str = ""  # display unit, e.g. "$/bbl", "%"
    floor: float = 0.0  # lowest stress score allowed; <0 enables two-sided scoring
    cap_rationale: str = ""  # why this cap was chosen, shown on the methodology page
    manual: bool = False  # True when there is no free API and the value is keyed by hand
    update_cadence: str = ""  # human-readable refresh cadence, shown in the UI


def stress_score(
    current: float,
    baseline: float,
    cap_pct: float,
    invert: bool = False,
    floor: float = 0.0,
) -> float:
    """Normalize a raw value to a stress score against its baseline.

    pct_change is signed; `invert` flips which direction counts as stress
    (e.g. ship traffic falling, not rising, is the crisis signal). The result
    is clamped to [floor, 100]; floor defaults to 0 (one-sided stress index).
    """
    if baseline == 0:
        score = (current / cap_pct) * 100 if cap_pct > 0 else 0.0
        return max(floor, min(100.0, score))
    pct_change = (current - baseline) / baseline * 100
    if invert:
        pct_change = -pct_change
    score = (pct_change / cap_pct) * 100
    return max(floor, min(100.0, score))


@dataclass
class ComponentResult:
    component: Component
    current_value: Optional[float]
    baseline_value: float
    stress: float
    contribution: float  # weight * stress
    stale: bool = False  # True if current_value could not be freshly fetched
    last_updated: str = ""  # ISO date the underlying value was last refreshed
    carried_forward: bool = False  # True if we reused a prior value instead of fetching


@dataclass
class CompositeResult:
    score: float
    level_label: str
    level_status: str  # "good" | "warning" | "serious" | "critical" — dataviz status palette role
    components: list[ComponentResult]
    week_start: str  # ISO date, Monday of the reporting week
    degraded: bool = False  # True when enough weight is stale that the score is unreliable
    stale_weight: float = 0.0  # fraction of index weight that is stale
    generated_at: str = ""  # ISO timestamp the snapshot was computed
    persisted: Optional[bool] = None  # None = not attempted; False = write did not survive

    @property
    def last_updated(self) -> str:
        """Most recent date any component's underlying value was refreshed.

        Distinct from week_start, which is the reporting period and moves only
        on Mondays — on every other day it reads as a stalled page even when a
        component refreshed that morning. Distinct from generated_at too: that
        is merely when this object was built, so it says "now" even for a
        snapshot whose every value was carried forward.

        Falls back to week_start when no component carries a date, which is the
        case before the first successful fetch.
        """
        dates = [c.last_updated[:10] for c in self.components if c.last_updated]
        return max(dates) if dates else self.week_start


# If this fraction of index weight or more is stale, the composite is flagged
# as degraded so the UI can say so instead of presenting a confident number.
DEGRADED_STALE_WEIGHT = 0.20


def compute_composite(
    components: list[Component],
    current_values: dict[str, Optional[float]],
    baseline_values: dict[str, float],
    stale_keys: Optional[set[str]] = None,
    level_fn: Optional[Callable[[float], tuple[str, str]]] = None,
    week_start: str = "",
    last_updated: Optional[dict[str, str]] = None,
    carried_forward: Optional[set[str]] = None,
    generated_at: str = "",
) -> CompositeResult:
    stale_keys = stale_keys or set()
    last_updated = last_updated or {}
    carried_forward = carried_forward or set()
    results: list[ComponentResult] = []
    total = 0.0
    stale_weight = 0.0

    for comp in components:
        current = current_values.get(comp.key)
        baseline = baseline_values.get(comp.key, 0.0)
        is_stale = comp.key in stale_keys or current is None
        # Fall back to baseline only as a last resort. Callers should carry the
        # last known value forward instead — a value we could not fetch is not
        # the same as a value that is at baseline.
        value_for_score = current if current is not None else baseline
        stress = stress_score(value_for_score, baseline, comp.cap_pct, comp.invert, comp.floor)
        contribution = comp.weight * stress
        total += contribution
        if is_stale:
            stale_weight += comp.weight
        results.append(
            ComponentResult(
                component=comp,
                current_value=current,
                baseline_value=baseline,
                stress=stress,
                contribution=contribution,
                stale=is_stale,
                last_updated=last_updated.get(comp.key, ""),
                carried_forward=comp.key in carried_forward,
            )
        )

    score = 100 + total
    label, status = (level_fn(score) if level_fn else default_level(score))
    return CompositeResult(
        score=round(score, 1),
        level_label=label,
        level_status=status,
        components=results,
        week_start=week_start,
        degraded=stale_weight >= DEGRADED_STALE_WEIGHT,
        stale_weight=round(stale_weight, 4),
        generated_at=generated_at,
    )


# Band thresholds are the single source of truth for both the level label and
# the gauge tick positions in the UI. (lower_bound, label, status).
LEVEL_BANDS: list[tuple[float, str, str]] = [
    (0.0, "Calm", "good"),
    (110.0, "Elevated", "good"),
    (125.0, "Acute", "warning"),
    (150.0, "Severe", "serious"),
    (180.0, "Extreme", "critical"),
]

# The composite is presented on a 100 (baseline) .. 200 (theoretical maximum
# stress on every component) scale. Both ends are labelled in the UI so a
# partially-filled gauge is not read as "% of maximum" by accident.
SCALE_MIN = 100.0
SCALE_MAX = 200.0


def default_level(score: float) -> tuple[str, str]:
    label, status = LEVEL_BANDS[0][1], LEVEL_BANDS[0][2]
    for lower, lbl, st in LEVEL_BANDS:
        if score >= lower:
            label, status = lbl, st
    return label, status


def band_positions() -> list[dict]:
    """Gauge tick positions derived from LEVEL_BANDS, as % of the 100..200 scale.

    Returned so the template never hardcodes a parallel list of positions that
    can silently drift out of sync with the thresholds.
    """
    span = SCALE_MAX - SCALE_MIN
    return [
        {"label": lbl, "lower": lower, "pct": round((lower - SCALE_MIN) / span * 100, 2)}
        for lower, lbl, _ in LEVEL_BANDS
        if lower > SCALE_MIN
    ]


def scale_pct(score: float) -> float:
    """Where a score sits on the 100..200 presentation scale, as a percentage."""
    span = SCALE_MAX - SCALE_MIN
    return max(0.0, min(100.0, (score - SCALE_MIN) / span * 100))
