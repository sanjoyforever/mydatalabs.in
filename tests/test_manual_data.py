"""Tests for the hand-entered feeder file.

The behaviours worth pinning down are the ones a wrong answer publishes quietly:
the typo guard, the error/warning split (a late figure must not stop the
automatic half of the index refreshing), and the generated provenance actually
tracking the current value rather than freezing.
"""
from __future__ import annotations

import json

import pytest

from app import manual_data


def write_manual(tmp_path, components: dict) -> str:
    path = tmp_path / "manual.json"
    path.write_text(json.dumps({"components": components}), encoding="utf-8")
    return str(path)


def war_risk(**overrides) -> dict:
    block = {
        "unit": "% hull value",
        "baseline": 0.25,
        "cadence_days": 7,
        "plausible_range": [0.05, 15.0],
        "value": 7.5,
        "as_of": "2026-08-17",
        "source": "Marsh",
        "note": "",
        "confidence": "observed",
    }
    block.update(overrides)
    return block


# --- Reading ----------------------------------------------------------------


def test_entry_reads_the_current_figure(tmp_path):
    path = write_manual(tmp_path, {"war_risk": war_risk()})

    keyed = manual_data.entry("war_risk", path)
    assert keyed.value == 7.5
    assert keyed.as_of == "2026-08-17"
    assert keyed.source == "Marsh"


def test_null_value_yields_no_entry_rather_than_zero(tmp_path):
    """An empty slot must not silently score the component at zero."""
    path = write_manual(tmp_path, {"war_risk": war_risk(value=None)})

    assert manual_data.entry("war_risk", path) is None
    assert manual_data.entries(path) == {}


def test_malformed_block_yields_no_entry_rather_than_raising(tmp_path):
    """A half-edited file is the normal state mid-update."""
    path = write_manual(tmp_path, {
        "war_risk": war_risk(as_of="not-a-date"),
        "reroutes": war_risk(value="abc"),
    })

    assert manual_data.entries(path) == {}


def test_missing_file_is_empty_not_an_error(tmp_path):
    path = str(tmp_path / "absent.json")
    assert manual_data.entries(path) == {}
    assert manual_data.entry("war_risk", path) is None


def test_overdue_is_measured_against_the_figures_own_cadence(tmp_path):
    path = write_manual(tmp_path, {
        "fresh": war_risk(as_of="2026-08-17", cadence_days=36500),
        "old": war_risk(as_of="2020-01-06", cadence_days=7),
    })

    assert manual_data.entry("fresh", path).overdue is False
    assert manual_data.entry("old", path).overdue is True


def test_fallback_entries_are_never_overdue(tmp_path):
    """Nobody keys a fallback weekly, so nagging about it is noise that drowns
    the warning that matters."""
    path = write_manual(tmp_path, {
        "ship_traffic": war_risk(as_of="2020-01-06", role="fallback"),
    })

    assert manual_data.entry("ship_traffic", path).overdue is False


# --- Validation -------------------------------------------------------------


def test_implausible_value_is_an_error(tmp_path):
    """The decimal-point slip this guard exists for: 750 keyed for 7.5."""
    path = write_manual(tmp_path, {"war_risk": war_risk(value=750.0)})

    errors, _ = manual_data.validate(path=path)
    assert any("plausible range" in e for e in errors)


def test_overdue_figure_is_a_warning_not_an_error(tmp_path):
    """A late manual figure must not stop Brent, TTF and VIX refreshing."""
    path = write_manual(tmp_path, {"war_risk": war_risk(as_of="2020-01-06")})

    errors, warnings = manual_data.validate(path=path)
    assert errors == []
    assert any("cadence" in w for w in warnings)


def test_null_value_is_a_warning_not_an_error(tmp_path):
    path = write_manual(tmp_path, {"war_risk": war_risk(value=None)})

    errors, warnings = manual_data.validate(path=path)
    assert errors == []
    assert any("null" in w for w in warnings)


def test_future_date_is_an_error(tmp_path):
    path = write_manual(tmp_path, {"war_risk": war_risk(as_of="2099-01-01")})

    errors, _ = manual_data.validate(path=path)
    assert any("future" in e for e in errors)


def test_unknown_component_key_is_an_error(tmp_path):
    path = write_manual(tmp_path, {"war_rsik": war_risk()})

    errors, _ = manual_data.validate({"war_risk": {}}, path=path)
    assert any("not a component" in e for e in errors)


def test_unit_drift_against_the_index_definition_is_an_error(tmp_path):
    """Documentation drift is how a figure gets keyed in the wrong unit."""
    path = write_manual(tmp_path, {"war_risk": war_risk()})

    errors, _ = manual_data.validate(
        {"war_risk": {"unit": "$ per transit", "baseline": 0.25}}, path=path
    )
    assert any("unit" in e for e in errors)


def test_missing_manual_component_is_an_error(tmp_path):
    """A manual component with no block would silently fall back to baseline."""
    path = write_manual(tmp_path, {"war_risk": war_risk()})

    errors, _ = manual_data.validate(
        {"war_risk": {"manual": True}, "reroutes": {"manual": True}}, path=path
    )
    assert any(e.startswith("reroutes") for e in errors)


def test_bad_confidence_label_is_an_error(tmp_path):
    path = write_manual(tmp_path, {"war_risk": war_risk(confidence="pretty sure")})

    errors, _ = manual_data.validate(path=path)
    assert any("confidence" in e for e in errors)


# --- Generated provenance ---------------------------------------------------


def snapshot_for(value: float, last_updated: str, **comp_kwargs):
    from app.scoring import Component, compute_composite

    comp = Component(
        key="war_risk", label="War-Risk Insurance", weight=1.0,
        source="Marsh / market brokers", cap_pct=3900, unit="% hull value",
        manual=True, **comp_kwargs,
    )
    return compute_composite(
        components=[comp],
        current_values={"war_risk": value},
        baseline_values={"war_risk": 0.25},
        last_updated={"war_risk": last_updated},
        week_start="2026-08-17",
    )


def test_source_notes_report_the_current_value_not_a_frozen_one(tmp_path):
    """The bug this replaced: a note asserting a month-old 'latest observation'."""
    path = write_manual(tmp_path, {"war_risk": war_risk(value=9.0)})
    note = manual_data.build_source_notes(
        snapshot_for(9.0, "2026-08-17"), "2026-01-01/2026-01-31", path
    )["war_risk"]

    assert "Baseline 0.25 % hull value" in note
    assert "2026-01-01/2026-01-31" in note
    assert "Latest 9 % hull value as of 2026-08-17 per Marsh" in note


def test_source_notes_carry_the_editors_note_through(tmp_path):
    path = write_manual(tmp_path, {"war_risk": war_risk(note="low end of a 7.5-10% range")})
    note = manual_data.build_source_notes(
        snapshot_for(7.5, "2026-08-17"), "2026-01-01/2026-01-31", path
    )["war_risk"]

    assert "low end of a 7.5-10% range." in note


def test_source_notes_do_not_credit_a_fallback_for_a_live_figure(tmp_path):
    """PortWatch produced the number; the fallback entry sitting beside it did not."""
    path = write_manual(tmp_path, {"war_risk": war_risk(role="fallback", source="IMF PortWatch")})
    note = manual_data.build_source_notes(
        snapshot_for(9.0, "2026-08-17"), "2026-01-01/2026-01-31", path
    )["war_risk"]

    assert "per IMF PortWatch" not in note
    assert "fallback for feed outages" in note


def test_reconstructed_series_is_derived_from_the_feeder(tmp_path):
    path = write_manual(tmp_path, {
        "war_risk": war_risk(history_reconstructed=True),
        "reroutes": war_risk(history_reconstructed=False),
    })

    assert manual_data.reconstructed_series(path) == ["war_risk"]


def test_reconstructed_series_clears_when_the_flag_is_cleared(tmp_path):
    """Retiring the caveat is a one-field edit, not a code change nobody makes."""
    path = write_manual(tmp_path, {"war_risk": war_risk(history_reconstructed=False)})

    assert manual_data.reconstructed_series(path) == []


@pytest.mark.parametrize("value,baseline,invert,expected", [
    (88.59, 64.77, False, "+37% vs baseline"),
    (31, 616, True, "5% of baseline"),
    (64.77, 64.77, False, "+0% vs baseline"),
])
def test_baseline_comparison_phrasing(value, baseline, invert, expected):
    assert manual_data._vs_baseline(value, baseline, invert) == expected
