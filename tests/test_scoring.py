"""Tests for the composite scoring engine.

stress_score() is the mathematical heart of every index on the site, so its
edge cases are pinned here: zero baselines, inversion, clamping at both ends,
two-sided scoring, and how missing components affect the composite.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.scoring import (  # noqa: E402
    DEGRADED_STALE_WEIGHT,
    LEVEL_BANDS,
    SCALE_MAX,
    SCALE_MIN,
    Component,
    band_positions,
    compute_composite,
    default_level,
    scale_pct,
    stress_score,
)


def comp(key="x", weight=1.0, cap_pct=50, invert=False, floor=0.0):
    return Component(
        key=key, label=key.title(), weight=weight, source="test",
        cap_pct=cap_pct, invert=invert, floor=floor,
    )


# --- stress_score ---------------------------------------------------------


def test_at_baseline_is_zero_stress():
    assert stress_score(100, 100, 50) == 0.0


def test_at_cap_is_full_stress():
    # +50% from baseline with a 50% cap == 100 stress
    assert stress_score(150, 100, 50) == 100.0


def test_halfway_to_cap_is_half_stress():
    assert stress_score(125, 100, 50) == pytest.approx(50.0)


def test_beyond_cap_clamps_at_100():
    assert stress_score(1000, 100, 50) == 100.0


def test_below_baseline_clamps_at_zero_by_default():
    """The index is one-sided: calmer than baseline is 0, never negative."""
    assert stress_score(50, 100, 50) == 0.0


def test_floor_enables_two_sided_scoring():
    """With a negative floor, calmer-than-baseline readings subtract."""
    assert stress_score(75, 100, 50, floor=-50) == pytest.approx(-50.0)
    # still clamped at the floor
    assert stress_score(10, 100, 50, floor=-50) == -50.0


def test_invert_flips_the_stress_direction():
    """For ship traffic a fall below baseline is the crisis signal."""
    # 34 -> 17 transits is a 50% decline; with a 50% cap that is full stress.
    assert stress_score(17, 34, 50, invert=True) == 100.0
    # A rise in transits is not stress.
    assert stress_score(51, 34, 50, invert=True) == 0.0


def test_zero_baseline_uses_cap_as_the_scale():
    assert stress_score(25, 0, 50) == pytest.approx(50.0)
    assert stress_score(100, 0, 50) == 100.0


def test_zero_baseline_and_zero_cap_is_zero_not_a_crash():
    assert stress_score(10, 0, 0) == 0.0


# --- compute_composite ----------------------------------------------------


def test_all_components_at_baseline_scores_100():
    components = [comp("a", 0.5), comp("b", 0.5)]
    result = compute_composite(
        components,
        current_values={"a": 100, "b": 100},
        baseline_values={"a": 100, "b": 100},
    )
    assert result.score == 100.0
    assert result.level_label == "Calm"


def test_all_components_at_cap_scores_scale_max():
    components = [comp("a", 0.5), comp("b", 0.5)]
    result = compute_composite(
        components,
        current_values={"a": 150, "b": 150},
        baseline_values={"a": 100, "b": 100},
    )
    assert result.score == SCALE_MAX


def test_contribution_is_weight_times_stress():
    components = [comp("a", 0.3), comp("b", 0.7)]
    result = compute_composite(
        components,
        current_values={"a": 150, "b": 100},
        baseline_values={"a": 100, "b": 100},
    )
    a, b = result.components
    assert a.contribution == pytest.approx(30.0)
    assert b.contribution == pytest.approx(0.0)
    assert result.score == pytest.approx(130.0)


def test_missing_value_is_flagged_stale():
    components = [comp("a", 1.0)]
    result = compute_composite(
        components,
        current_values={"a": None},
        baseline_values={"a": 100},
    )
    assert result.components[0].stale is True
    assert result.components[0].current_value is None


def test_stale_weight_over_threshold_marks_snapshot_degraded():
    components = [comp("a", 0.3), comp("b", 0.7)]
    result = compute_composite(
        components,
        current_values={"a": 100, "b": 100},
        baseline_values={"a": 100, "b": 100},
        stale_keys={"a"},
    )
    assert result.stale_weight == pytest.approx(0.3)
    assert result.degraded is True


def test_small_stale_weight_is_not_degraded():
    components = [comp("a", 0.05), comp("b", 0.95)]
    result = compute_composite(
        components,
        current_values={"a": 100, "b": 100},
        baseline_values={"a": 100, "b": 100},
        stale_keys={"a"},
    )
    assert result.stale_weight < DEGRADED_STALE_WEIGHT
    assert result.degraded is False


def test_carried_forward_keys_are_marked():
    components = [comp("a", 1.0)]
    result = compute_composite(
        components,
        current_values={"a": 120},
        baseline_values={"a": 100},
        carried_forward={"a"},
        last_updated={"a": "2026-07-20"},
    )
    assert result.components[0].carried_forward is True
    assert result.components[0].last_updated == "2026-07-20"


# --- levels and scale -----------------------------------------------------


@pytest.mark.parametrize(
    "score,expected",
    [
        (100.0, "Calm"),
        (109.9, "Calm"),
        (110.0, "Elevated"),
        (124.9, "Elevated"),
        (125.0, "Acute"),
        (149.9, "Acute"),
        (150.0, "Severe"),
        (179.9, "Severe"),
        (180.0, "Extreme"),
        (250.0, "Extreme"),
    ],
)
def test_level_band_boundaries(score, expected):
    assert default_level(score)[0] == expected


def test_band_positions_match_level_thresholds():
    """The gauge ticks and the level labels must come from the same constants."""
    positions = band_positions()
    thresholds = [lower for lower, _, _ in LEVEL_BANDS if lower > SCALE_MIN]
    assert [p["lower"] for p in positions] == thresholds
    # 110 on a 100..200 scale is 10% along.
    assert positions[0]["pct"] == pytest.approx(10.0)


def test_scale_pct_clamps_to_the_presentation_range():
    assert scale_pct(100.0) == 0.0
    assert scale_pct(150.0) == pytest.approx(50.0)
    assert scale_pct(200.0) == 100.0
    assert scale_pct(90.0) == 0.0
    assert scale_pct(400.0) == 100.0


# --- Hormuz component sanity ----------------------------------------------
# The ship-traffic baseline was published as 34 "transits/wk" for 29 weeks. It
# was a daily tanker figure mislabelled as a weekly all-vessel one — wrong by a
# factor of ~18. These pin the corrected values so the same class of units error
# cannot come back silently.


def test_hormuz_weights_sum_to_one():
    from app.indices.hormuz import COMPONENTS

    assert sum(c.weight for c in COMPONENTS) == pytest.approx(1.0)


def test_every_component_has_a_baseline_and_a_cap_rationale():
    from app.indices.hormuz import BASELINE_VALUES, COMPONENTS

    for c in COMPONENTS:
        assert c.key in BASELINE_VALUES, f"{c.key} has no baseline"
        assert c.cap_rationale.strip(), f"{c.key} has an undocumented cap"


def test_ship_traffic_baseline_is_a_weekly_all_vessel_count():
    """~88 commercial vessels/day (IMF PortWatch) x 7 == 616/wk.

    Anything in the tens implies a daily figure has been pasted into a weekly
    field again.
    """
    from app.indices.hormuz import BASELINE_VALUES

    weekly = BASELINE_VALUES["ship_traffic"]
    assert 400 <= weekly <= 1100, f"{weekly}/wk is not a plausible weekly all-vessel count"
    daily = weekly / 7
    assert 60 <= daily <= 150, f"{daily:.0f}/day is outside the published 80-138 range"


def test_ship_traffic_cap_can_distinguish_disruption_from_closure():
    """At the old -50% cap a halved strait and a closed one both scored 100."""
    from app.indices.hormuz import BASELINE_VALUES, COMPONENTS_BY_KEY

    c = COMPONENTS_BY_KEY["ship_traffic"]
    base = BASELINE_VALUES["ship_traffic"]

    halved = stress_score(base * 0.50, base, c.cap_pct, c.invert, c.floor)
    closed = stress_score(base * 0.02, base, c.cap_pct, c.invert, c.floor)
    assert halved < closed, "cap saturates before closure — the range is not resolvable"
    assert halved < 100.0


def test_observed_july_2026_reading_is_not_capped_out():
    """105/wk (15 vessels/day, PortWatch 2026-07-19) must still have headroom."""
    from app.indices.hormuz import BASELINE_VALUES, COMPONENTS_BY_KEY

    c = COMPONENTS_BY_KEY["ship_traffic"]
    stress = stress_score(105, BASELINE_VALUES["ship_traffic"], c.cap_pct, c.invert, c.floor)
    assert 85 < stress < 100, f"stress {stress:.1f} leaves no room to worsen"


def test_war_risk_baseline_is_a_plausible_peacetime_rate():
    """Pre-war Hormuz war risk ran ~0.125-0.25% of hull value per transit.

    A baseline an order of magnitude below that makes every crisis reading
    saturate the cap, which is what happened before the 2026-07-26 revision.
    """
    from app.indices.hormuz import BASELINE_VALUES

    base = BASELINE_VALUES["war_risk"]
    assert 0.10 <= base <= 0.40, f"{base}% hull is not a plausible peacetime rate"


def test_war_risk_cap_spans_the_reported_crisis_range():
    """Reported rates ran 2% to 10% of hull. All must be rankable, not pinned."""
    from app.indices.hormuz import BASELINE_VALUES, COMPONENTS_BY_KEY

    c = COMPONENTS_BY_KEY["war_risk"]
    base = BASELINE_VALUES["war_risk"]
    scores = [stress_score(v, base, c.cap_pct, c.invert, c.floor) for v in (2.0, 5.0, 7.5)]
    assert all(s < 100.0 for s in scores), "cap saturates inside the observed range"
    assert scores == sorted(scores), "not monotone across the observed range"
    # The reported peak is the top of the scale by construction.
    assert stress_score(10.0, base, c.cap_pct, c.invert, c.floor) == pytest.approx(100.0, abs=0.5)


def test_manual_components_carry_a_named_source():
    from app.indices.hormuz import COMPONENTS

    for c in COMPONENTS:
        if c.manual:
            assert c.source and "yfinance" not in c.source, f"{c.key} manual but sourced to a feed"
