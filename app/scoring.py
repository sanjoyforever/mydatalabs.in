"""Generic composite-index engine.

Any weekly stress/crisis index (Hormuz, Geo Politics, ...) is built the same way:
a set of weighted components, each normalized to a 0-100 "stress score" against
a baseline, capped at a realistic crisis maximum, then summed into a composite
that starts at 100 (baseline/calm) and rises with stress.

    composite = 100 + sum(weight * stress_score)
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


def stress_score(current: float, baseline: float, cap_pct: float, invert: bool = False) -> float:
    """Normalize a raw value to a 0-100 stress score against its baseline.

    pct_change is signed; `invert` flips which direction counts as stress
    (e.g. ship traffic falling, not rising, is the crisis signal).
    """
    if baseline == 0:
        score = (current / cap_pct) * 100 if cap_pct > 0 else 0.0
        return max(0.0, min(100.0, score))
    pct_change = (current - baseline) / baseline * 100
    if invert:
        pct_change = -pct_change
    score = (pct_change / cap_pct) * 100
    return max(0.0, min(100.0, score))


@dataclass
class ComponentResult:
    component: Component
    current_value: Optional[float]
    baseline_value: float
    stress: float
    contribution: float  # weight * stress
    stale: bool = False  # True if current_value could not be freshly fetched


@dataclass
class CompositeResult:
    score: float
    level_label: str
    level_status: str  # "good" | "warning" | "serious" | "critical" — dataviz status palette role
    components: list[ComponentResult]
    week_start: str  # ISO date, Monday of the reporting week


def compute_composite(
    components: list[Component],
    current_values: dict[str, Optional[float]],
    baseline_values: dict[str, float],
    stale_keys: Optional[set[str]] = None,
    level_fn: Optional[Callable[[float], tuple[str, str]]] = None,
    week_start: str = "",
) -> CompositeResult:
    stale_keys = stale_keys or set()
    results: list[ComponentResult] = []
    total = 0.0

    for comp in components:
        current = current_values.get(comp.key)
        baseline = baseline_values.get(comp.key, 0.0)
        is_stale = comp.key in stale_keys or current is None
        value_for_score = current if current is not None else baseline
        stress = stress_score(value_for_score, baseline, comp.cap_pct, comp.invert)
        contribution = comp.weight * stress
        total += contribution
        results.append(
            ComponentResult(
                component=comp,
                current_value=current,
                baseline_value=baseline,
                stress=stress,
                contribution=contribution,
                stale=is_stale,
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
    )


def default_level(score: float) -> tuple[str, str]:
    if score < 110:
        return "Calm", "good"
    if score < 125:
        return "Elevated", "good"
    if score < 150:
        return "Acute", "warning"
    if score < 180:
        return "Severe", "serious"
    return "Extreme", "critical"
