"""Tests for the U.S. Sovereign Solvency Index (USS-INDEX) engine and route."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.indices import solvency


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


# --- Index definition ------------------------------------------------------


def test_components_weight_sum():
    """The seven components must sum to exactly 1.0."""
    assert abs(sum(c.weight for c in solvency.COMPONENTS) - 1.0) < 1e-9
    assert len(solvency.COMPONENTS) == 7


def test_block_weights_match_components():
    """Each block's declared weight must equal its components' actual weights."""
    for block in solvency.BLOCKS:
        actual = sum(
            c.weight for c in solvency.COMPONENTS if solvency.COMPONENT_BLOCK[c.key] == block["key"]
        )
        assert abs(actual - block["weight"]) < 1e-9, block["key"]
    assert abs(sum(b["weight"] for b in solvency.BLOCKS) - 1.0) < 1e-9


def test_every_component_has_a_band_and_a_block():
    for comp in solvency.COMPONENTS:
        assert comp.key in solvency.BANDS
        assert comp.key in solvency.COMPONENT_BLOCK
        assert comp.key in solvency.BASELINE_ANCHORS
        assert comp.cap_rationale, f"{comp.key} has no crisis-threshold rationale"


def test_statuses_exist_in_stylesheet_vocabulary():
    """A band whose status has no CSS role renders as an unstyled badge."""
    allowed = {"good", "warning", "serious", "critical"}
    assert {status for _, _, status in solvency.LEVEL_BANDS} <= allowed


# --- Scoring ---------------------------------------------------------------


def test_stress_is_zero_at_baseline_and_100_at_crisis():
    for key, (baseline, crisis) in solvency.BANDS.items():
        assert solvency.stress_for(key, baseline) == pytest.approx(0.0), key
        assert solvency.stress_for(key, crisis) == pytest.approx(100.0), key


def test_stress_is_clamped_both_ways():
    # Debt far below baseline is not negative stress; far above is capped.
    assert solvency.stress_for("debt_gdp", 0.0) == 0.0
    assert solvency.stress_for("debt_gdp", 500.0) == 100.0
    # Inverted component: high productivity is calm, negative is max stress.
    assert solvency.stress_for("productivity", 5.0) == 0.0
    assert solvency.stress_for("productivity", -3.0) == 100.0


def test_missing_value_scores_none_not_zero():
    """A gap must not be scored as if the indicator were calm."""
    assert solvency.stress_for("productivity", None) is None


def test_score_row_renormalises_on_missing_components():
    """Dropping the growth block must not make a year look healthier."""
    full = {
        "debt_gdp": 100.0, "interest_burden": 20.0, "primary_deficit": 4.0,
        "productivity": 0.0, "real_gdp_pc": 0.0, "inflation": 2.0, "r_minus_g": -1.0,
    }
    without_growth = dict(full, productivity=None, real_gdp_pc=None)

    scored_full = solvency.score_row(full)
    scored_partial = solvency.score_row(without_growth)

    assert scored_full["partial"] is False
    assert scored_partial["partial"] is True
    assert scored_partial["covered_weight"] == pytest.approx(0.70)

    # The growth block was pinned at maximum stress, so dropping it must lower
    # the score — but the remaining weight is renormalised, so the fiscal and
    # monetary contributions each rise rather than vanishing.
    assert scored_partial["score"] < scored_full["score"]
    assert scored_partial["contributions"]["debt_gdp"] > scored_full["contributions"]["debt_gdp"]


def test_score_row_contributions_sum_to_score():
    row = solvency.latest_row()
    scored = solvency.score_row(row["raw_values"])
    assert sum(scored["contributions"].values()) == pytest.approx(
        scored["score"] - solvency.SCALE_MIN, abs=0.05
    )


def test_block_contributions_sum_to_total():
    row = solvency.latest_row()
    blocks = row["block_contributions"]
    assert sum(blocks.values()) == pytest.approx(row["score"] - solvency.SCALE_MIN, abs=0.05)


# --- History ---------------------------------------------------------------


def test_history_is_real_and_complete():
    history = solvency.get_history()
    assert len(history) >= 80
    assert history[0]["year"] == 1945
    years = [row["year"] for row in history]
    assert years == sorted(years), "history must be chronological"
    assert years == list(range(years[0], years[-1] + 1)), "no gaps allowed"


def test_every_year_scores_within_the_declared_scale():
    for row in solvency.get_history():
        assert solvency.SCALE_MIN <= row["score"] <= solvency.SCALE_MAX, row["year"]


def test_known_historical_landmarks():
    """Spot-checks against the published fiscal record.

    These are assertions about FRED's data, not about the index weighting, so
    they catch a units error or a broken join in the build script.
    """
    by_year = {row["year"]: row for row in solvency.get_history()}

    # FY1945: debt held by the public peaked just above 100% of GDP.
    assert 100.0 < by_year[1945]["raw_values"]["debt_gdp"] < 110.0
    # FY2000: the surplus years ran a primary *surplus* of several points.
    assert by_year[2000]["raw_values"]["primary_deficit"] < -3.0
    # 1980: the Great Inflation peak.
    assert by_year[1980]["raw_values"]["inflation"] > 12.0
    # FY2025: net interest passed 18% of receipts.
    assert by_year[2025]["raw_values"]["interest_burden"] > 18.0
    # The effective rate on the debt stock is a rate, not a ratio of raw units.
    assert 0.5 < by_year[2025]["context"]["effective_rate"] < 10.0


def test_calibration_lands_the_post_war_low_near_baseline():
    """FY1965 is the post-war minimum; well-chosen baselines put it near 100.

    This is the check that the bands are calibrated rather than fitted to make
    the present look alarming. If a baseline is retuned and this drifts far
    from 100, the equilibrium being claimed is no longer the one measured.
    """
    by_year = {row["year"]: row for row in solvency.get_history()}
    assert 98.0 <= by_year[1965]["score"] <= 108.0


def test_partial_years_are_exactly_the_pre_1957_growth_gap():
    partial = [row["year"] for row in solvency.get_history() if row.get("partial")]
    assert partial == list(range(1945, 1957))


# --- Snapshot --------------------------------------------------------------


def test_compute_snapshot():
    snapshot = solvency.compute_snapshot()
    assert solvency.SCALE_MIN <= snapshot.score <= solvency.SCALE_MAX
    assert snapshot.level_label in {"Sustainable", "Watch", "Strained", "Severe"}
    assert snapshot.level_status in {"good", "warning", "serious", "critical"}
    assert len(snapshot.components) == 7
    assert snapshot.degraded is False, "the latest year should have full coverage"


def test_top_driver_is_the_largest_contributor():
    snapshot = solvency.compute_snapshot()
    driver = solvency.top_driver(snapshot)
    assert driver.contribution == max(c.contribution for c in snapshot.components)


# --- Projection ------------------------------------------------------------


def test_projection_runs_and_is_monotone_in_r_minus_g():
    """A higher r - g must produce a higher terminal debt ratio. If this fails
    the recursion has been wired up backwards."""
    projs = {p["key"]: p for p in solvency.projections()}
    assert projs["favorable"]["end_debt_gdp"] < projs["baseline"]["end_debt_gdp"]
    assert projs["baseline"]["end_debt_gdp"] < projs["adverse"]["end_debt_gdp"]


def test_projection_path_length_and_continuity():
    for proj in solvency.projections():
        assert len(proj["path"]) == solvency.PROJECTION_YEARS
        start = solvency.latest_row()["year"]
        assert proj["path"][0]["year"] == start + 1
        assert proj["path"][-1]["year"] == start + solvency.PROJECTION_YEARS


def test_effective_rate_converges_toward_terminal_but_never_overshoots():
    for proj in solvency.projections():
        rates = [step["effective_rate"] for step in proj["path"]]
        terminal = proj["terminal_r"]
        start = solvency.latest_row()["context"]["effective_rate"]
        if terminal > start:
            assert rates == sorted(rates)
            assert max(rates) <= terminal + 1e-6
        else:
            assert min(rates) >= terminal - 1e-6


def test_horizon_reports_a_range_not_a_point():
    """The whole argument of the projection panel is that the spread is the
    result. A threshold reached under every scenario in the same year would
    mean the scenarios are not actually spanning anything."""
    horizon = solvency.horizon_summary()
    fiscal_dominance = [t for t in horizon["thresholds"] if t["pct"] == 35.0][0]
    assert fiscal_dominance["earliest"] is not None
    # Favourable must not reach fiscal dominance; adverse must, and well before
    # baseline does.
    assert fiscal_dominance["scenario_years"]["favorable"] is None
    assert fiscal_dominance["scenario_years"]["adverse"] < fiscal_dominance["scenario_years"]["baseline"]


def test_decade_averages_cover_the_series():
    decades = solvency.decade_averages()
    assert decades[0]["start"] == 1940
    assert sum(d["years"] for d in decades) == len(solvency.get_history())


def test_turning_points_all_resolve_to_a_year_in_the_series():
    points = solvency.turning_points_with_scores()
    assert len(points) == len(solvency.TURNING_POINTS)
    for point in points:
        assert point["score"] is not None


# --- Route -----------------------------------------------------------------


def test_route_renders(client):
    resp = client.get("/solvency-index")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "U.S. Sovereign Solvency Index" in body
    assert "USS-INDEX" in body


def test_route_publishes_the_score_and_the_calibration_check(client):
    body = client.get("/solvency-index").data.decode()
    snapshot = solvency.compute_snapshot()
    assert f"{snapshot.score:.1f}" in body
    # The FY1965 calibration check must be on the methodology tab.
    by_year = {row["year"]: row for row in solvency.get_history()}
    assert f"{by_year[1965]['score']:.1f}" in body


def test_route_states_the_attribution_limitation(client):
    """The scorecard was dropped for stated reasons; the page must say so."""
    body = client.get("/solvency-index").data.decode()
    assert "No presidential attribution" in body
    assert "mean reversion" in body


def test_route_cites_its_sources(client):
    body = client.get("/solvency-index").data.decode()
    for series in solvency.SOURCE_SERIES:
        assert series["id"] in body, series["id"]


def test_home_lists_the_index(client):
    body = client.get("/").data.decode()
    assert "/solvency-index" in body


def test_no_leftover_jinja(client):
    body = client.get("/solvency-index").data.decode()
    assert "{{" not in body and "{%" not in body


# --- Quadrant --------------------------------------------------------------


def test_quadrant_classification_covers_all_four_signs():
    assert solvency.quadrant_for(1.0, 1.0) == "compounding"
    assert solvency.quadrant_for(-1.0, 1.0) == "outgrowing"
    assert solvency.quadrant_for(-1.0, -1.0) == "consolidating"
    assert solvency.quadrant_for(1.0, -1.0) == "running_to_stand_still"


def test_quadrant_keys_match_the_declared_quadrants():
    declared = {q["key"] for q in solvency.QUADRANTS}
    assert {p["quadrant"] for p in solvency.quadrant_points()} <= declared


def test_quadrant_points_carry_both_axes():
    points = solvency.quadrant_points()
    assert len(points) >= 75
    for point in points:
        assert point["x"] is not None and point["y"] is not None
        assert point["era"] in {e["key"] for e in solvency.ERAS}


def test_quadrant_counts_sum_to_the_point_count():
    counts = solvency.quadrant_counts()
    assert sum(c["years"] for c in counts) == len(solvency.quadrant_points())
    assert sum(1 for c in counts if c["current"]) == 1, "exactly one quadrant is current"


def test_eras_are_contiguous_and_cover_the_series():
    for a, b in zip(solvency.ERAS, solvency.ERAS[1:]):
        assert b["start"] == a["end"] + 1, "era boundaries must not gap or overlap"
    for row in solvency.get_history():
        assert solvency.era_for(row["year"]) is not None


# --- Decomposition ---------------------------------------------------------


def test_decomposition_identity_holds_exactly():
    """change = snowball + primary + sfa is an identity by construction; if it
    stops holding, the residual is being computed against different inputs."""
    for row in solvency.debt_decomposition():
        assert row["snowball"] + row["primary"] + row["sfa"] == pytest.approx(
            row["change"], abs=0.02
        ), row["year"]


def test_decomposition_residual_stays_small():
    """A large mean residual would mean r, g or pb are inconsistent with the
    debt series they are supposed to explain."""
    rows = solvency.debt_decomposition()
    mean_abs = sum(abs(r["sfa"]) for r in rows) / len(rows)
    assert mean_abs < 1.5, f"mean |SFA| = {mean_abs:.2f}pp is too large to ignore"


def test_decomposition_finds_the_2022_inflation_erosion():
    """FY2022 is the clearest case of the two terms opposing: a primary deficit
    more than offset by inflation eroding the stock."""
    row = next(r for r in solvency.debt_decomposition() if r["year"] == 2022)
    assert row["primary"] > 0, "2022 ran a primary deficit"
    assert row["snowball"] < -3.0, "2022 had a strongly negative snowball"
    assert row["change"] < 0, "the ratio nonetheless fell"


# --- Reserve-currency simulator --------------------------------------------


def test_simulator_defaults_are_complete():
    defaults = solvency.simulator_defaults()
    for key in ("debt_gdp", "effective_rate", "primary_deficit", "receipts_pct_gdp",
                "terminal_r", "nominal_growth", "terminal_pb", "passthrough_bp",
                "repricing_speed", "projection_years", "index_horizon_years",
                "bands", "weights", "thresholds", "level_bands"):
        assert defaults.get(key) is not None, key
    assert set(defaults["bands"]) == set(solvency.BANDS)
    assert set(defaults["weights"]) == {c.key for c in solvency.COMPONENTS}


def test_zero_shift_reproduces_the_baseline_scenario():
    """The simulator's null setting must land exactly on the published
    baseline, or the two panels would quietly disagree."""
    baseline = next(p for p in solvency.projections() if p["key"] == "baseline")
    sim = solvency.simulate_reserve_shift(0.0)
    assert sim["end_debt_gdp"] == pytest.approx(baseline["end_debt_gdp"], abs=0.01)
    assert sim["crossings"] == baseline["crossings"]
    assert sim["premium_bp"] == 0.0


def test_displacement_raises_rates_debt_and_pulls_the_threshold_forward():
    none_ = solvency.simulate_reserve_shift(0.0)
    some = solvency.simulate_reserve_shift(30.0)
    assert some["terminal_r"] > none_["terminal_r"]
    assert some["end_debt_gdp"] > none_["end_debt_gdp"]
    assert some["crossings"]["35"] < none_["crossings"]["35"]


def test_displacement_is_monotone_in_share_and_in_passthrough():
    debts = [solvency.simulate_reserve_shift(s)["end_debt_gdp"] for s in (0, 5, 10, 20, 30, 40)]
    assert debts == sorted(debts)
    by_pass = [
        solvency.simulate_reserve_shift(20.0, passthrough_bp=p)["end_debt_gdp"]
        for p in (0.5, 1.5, 2.5, 4.0, 6.0)
    ]
    assert by_pass == sorted(by_pass)


def test_share_accounting_conserves_the_shifted_points():
    sim = solvency.simulate_reserve_shift(15.0)
    assert sim["usd_share_after"] == pytest.approx(solvency.USD_RESERVE_SHARE - 15.0)
    assert sim["cny_share_after"] == pytest.approx(solvency.CNY_RESERVE_SHARE + 15.0)


def test_default_passthrough_is_derived_from_the_stated_anchor():
    """The default must stay the quotient of the two published constants, so a
    reader checking the arithmetic on the page gets the same number."""
    assert solvency.DEFAULT_PASSTHROUGH_BP == pytest.approx(
        solvency.FULL_DISPLACEMENT_BP / solvency.USD_RESERVE_SHARE, abs=0.01
    )
    full = solvency.simulate_reserve_shift(solvency.USD_RESERVE_SHARE)
    assert full["premium_bp"] == pytest.approx(solvency.FULL_DISPLACEMENT_BP, abs=1.0)


def test_simulated_index_is_reported_before_it_saturates():
    """The index readout is taken at a horizon where the debt component has not
    hit its cap; otherwise the control looks broken to the user."""
    sim = solvency.simulate_reserve_shift(0.0)
    assert sim["index_year"] == solvency.latest_row()["year"] + solvency.INDEX_HORIZON_YEARS
    spread = (
        solvency.simulate_reserve_shift(40.0)["end_index"]
        - solvency.simulate_reserve_shift(0.0)["end_index"]
    )
    assert spread > 0.5, "the index must still respond at the reported horizon"


def test_primary_deficit_lever_moves_the_index_too():
    tight = solvency.simulate_reserve_shift(0.0, terminal_pb=1.5)
    loose = solvency.simulate_reserve_shift(0.0, terminal_pb=6.0)
    assert loose["end_debt_gdp"] > tight["end_debt_gdp"]
    assert loose["end_index"] > tight["end_index"]


# --- Route (new sections) --------------------------------------------------


def test_route_renders_the_new_panels(client):
    body = client.get("/solvency-index").data.decode()
    for marker in ("echart-quadrant-container", "echart-decomp-container",
                   "echart-sim-container", "sim-shift", "ussSimReset"):
        assert marker in body, marker


def test_route_states_the_simulator_assumption_and_its_limits(client):
    body = client.get("/solvency-index").data.decode()
    assert "Warnock" in body, "the pass-through anchor must be cited"
    assert "Not modelled" in body, "unmodelled channels must be named"


def test_route_explains_why_this_quadrant(client):
    body = client.get("/solvency-index").data.decode()
    assert "Which quadrant this is" in body


# --- Weighting schemes -----------------------------------------------------


def test_every_scheme_is_a_valid_probability_weighting():
    for key, scheme in solvency.WEIGHTING_SCHEMES.items():
        weights = scheme["weights"]
        assert set(weights) == set(solvency.BANDS), key
        assert sum(weights.values()) == pytest.approx(1.0, abs=1e-9), key
        assert all(w > 0 for w in weights.values()), key


def test_balanced_scheme_matches_the_published_component_weights():
    """The 'balanced' scheme must BE the published index, not a near copy — the
    presidential panel would otherwise silently rank on a different index than
    the rest of the page shows."""
    published = {c.key: c.weight for c in solvency.COMPONENTS}
    assert solvency.WEIGHTING_SCHEMES["balanced"]["weights"] == published


def test_history_under_balanced_reproduces_the_published_series():
    published = {r["year"]: r["score"] for r in solvency.get_history()}
    for row in solvency.history_under("balanced"):
        assert row["score"] == pytest.approx(published[row["year"]], abs=0.05), row["year"]


def test_alternative_schemes_actually_differ():
    balanced = [r["score"] for r in solvency.history_under("balanced")]
    for key in ("fiscal_heavy", "growth_heavy", "equal"):
        other = [r["score"] for r in solvency.history_under(key)]
        assert other != balanced, f"{key} produced an identical series"


def test_score_row_weight_override_renormalises():
    raw = solvency.latest_row()["raw_values"]
    a = solvency.score_row(raw)
    b = solvency.score_row(raw, weights=solvency.WEIGHTING_SCHEMES["fiscal_heavy"]["weights"])
    assert a["score"] != b["score"]
    assert sum(b["contributions"].values()) == pytest.approx(b["score"] - solvency.SCALE_MIN, abs=0.05)


# --- OLS helper ------------------------------------------------------------


def test_ols_recovers_a_known_line():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [3.0 + 2.0 * x for x in xs]
    fit = solvency._ols(xs, ys)
    assert fit["alpha"] == pytest.approx(3.0, abs=1e-9)
    assert fit["beta"] == pytest.approx(2.0, abs=1e-9)
    assert fit["r2"] == pytest.approx(1.0, abs=1e-9)
    assert fit["resid_sd"] == pytest.approx(0.0, abs=1e-9)


def test_ols_is_safe_on_degenerate_input():
    assert solvency._ols([1.0, 2.0], [1.0, 2.0])["n"] == 2          # too few points
    assert solvency._ols([2.0] * 5, [1.0, 2.0, 3.0, 4.0, 5.0])["beta"] == 0.0  # no x variance


# --- Presidential terms ----------------------------------------------------


def test_presidential_terms_are_contiguous_and_ordered():
    for a, b in zip(solvency.PRESIDENTS, solvency.PRESIDENTS[1:]):
        assert b["first"] == a["last"] + 1, f"gap or overlap between {a['id']} and {b['id']}"
        assert a["first"] <= a["last"]
    assert len(solvency.PRESIDENTS) == 14


def test_terms_lie_inside_the_series():
    years = {row["year"] for row in solvency.get_history()}
    for pres in solvency.PRESIDENTS:
        assert pres["first"] - 1 in years, f"{pres['id']} inherits a year outside the series"
        assert pres["last"] in years


def test_inherited_chains_to_the_predecessors_ending_value():
    rows = solvency.presidential_scores()["rows"]
    for prev, cur in zip(rows, rows[1:]):
        assert cur["inherited"] == pytest.approx(prev["ending"], abs=0.05), cur["id"]


# --- Decomposition ---------------------------------------------------------


def test_raw_change_is_ending_minus_inherited():
    for row in solvency.presidential_scores()["rows"]:
        assert row["raw_change"] == pytest.approx(row["ending"] - row["inherited"], abs=0.05), row["id"]


def test_residual_identity_holds():
    """residual = raw - cyclical - expected. If this drifts the panel is
    reporting a number that is not the one it describes."""
    for row in solvency.presidential_scores()["rows"]:
        assert row["residual"] == pytest.approx(
            row["raw_change"] - (row["cyclical"] or 0.0) - row["expected"], abs=0.15
        ), row["id"]


def test_cyclical_coefficient_is_negative_and_well_determined():
    """A widening output gap must RAISE the index (deficits open, growth falls).
    A positive slope would mean the correction is being applied backwards."""
    model = solvency.cyclical_model()
    assert model["beta"] < 0
    assert abs(model["t"]) > 3.0, "the cyclical correction should be firmly estimated"
    assert model["n"] > 60


def test_mean_reversion_slope_is_negative():
    """Inheriting a higher index must predict a larger subsequent fall; that is
    the artifact the correction exists to remove."""
    assert solvency.presidential_scores()["reversion_model"]["beta"] < 0


def test_correction_reduces_dependence_on_the_inherited_level():
    """The whole point: raw change is strongly explained by the starting level,
    the corrected residual is not."""
    comparison = solvency.presidential_comparison()
    assert comparison["correlations"]["raw_vs_inherited"] > 0.3
    assert comparison["correlations"]["adjusted_vs_inherited"] < comparison["correlations"]["raw_vs_inherited"]


def test_residuals_are_orthogonal_to_inherited_level_by_construction():
    """Residualising removes the dependence on the inherited level.

    Not bit-exact zero: the published figures are rounded to one decimal, which
    leaves a slope of order 1e-3 against a pre-correction slope of about -0.5.
    The assertion is that the dependence is gone to within rounding, which is
    two orders of magnitude tighter than any claim the page makes.
    """
    scores = solvency.presidential_scores()
    rows = scores["rows"]
    fit = solvency._ols([r["inherited"] for r in rows], [r["residual"] for r in rows])
    before = abs(scores["reversion_model"]["beta"])
    assert abs(fit["beta"]) < 0.01
    assert abs(fit["beta"]) < before / 100.0


def test_truman_has_no_cyclical_estimate_rather_than_a_fabricated_zero():
    """CBO potential GDP starts in 1949, so 1945 has no output gap. That must
    surface as None, not be silently treated as a measured zero."""
    truman = next(r for r in solvency.presidential_scores()["rows"] if r["id"] == "truman")
    assert truman["cyclical"] is None
    others = [r for r in solvency.presidential_scores()["rows"] if r["id"] != "truman"]
    assert all(r["cyclical"] is not None for r in others)


# --- Comparison / significance --------------------------------------------


def test_comparison_reports_an_error_band_and_uses_it():
    comparison = solvency.presidential_comparison()
    assert comparison["residual_sd"] > 0
    named = set(comparison["indistinguishable"])
    for row in comparison["rows"]:
        inside = abs(row["residual"]) <= comparison["residual_sd"]
        assert (row["name"] in named) == inside, row["name"]
    assert comparison["indistinguishable_count"] == len(named)


def test_most_terms_are_not_distinguishable_from_zero():
    """The honest headline. If this ever flips, the page's framing is wrong and
    should be rewritten rather than the test relaxed."""
    comparison = solvency.presidential_comparison()
    assert comparison["indistinguishable_count"] >= len(comparison["rows"]) // 2


def test_party_gap_is_small_relative_to_the_error_band():
    comparison = solvency.presidential_comparison()
    assert comparison["party_gap"] < comparison["residual_sd"], (
        "the page claims there is no party signal; if the gap exceeds the noise "
        "that claim needs revisiting"
    )


def test_rows_are_ranked_by_residual_and_ranks_are_dense():
    comparison = solvency.presidential_comparison()
    residuals = [r["residual"] for r in comparison["rows"]]
    assert residuals == sorted(residuals, reverse=True)
    assert [r["rank"] for r in comparison["rows"]] == list(range(1, len(residuals) + 1))


def test_rank_ranges_span_every_scheme():
    comparison = solvency.presidential_comparison()
    for row in comparison["rows"]:
        ranks = list(row["ranks_by_scheme"].values())
        assert set(row["ranks_by_scheme"]) == set(solvency.WEIGHTING_SCHEMES)
        assert row["rank_min"] == min(ranks)
        assert row["rank_max"] == max(ranks)
        assert row["rank_spread"] == max(ranks) - min(ranks)


def test_correction_actually_reorders_the_table():
    """If the corrected ranking matched the raw one, the correction would be
    decorative. Several presidents should move materially."""
    comparison = solvency.presidential_comparison()
    shifts = [abs(r["rank_shift_vs_raw"]) for r in comparison["rows"]]
    assert max(shifts) >= 5, "the mean-reversion correction should move the table"


def test_every_scheme_ranks_all_fourteen():
    for key in solvency.WEIGHTING_SCHEMES:
        rows = solvency.presidential_scores(key)["rows"]
        assert len(rows) == 14, key


# --- Route -----------------------------------------------------------------


def test_route_renders_the_presidential_panel(client):
    body = client.get("/solvency-index").data.decode()
    for marker in ("echart-pres-container", "echart-inherited-container",
                   "Presidential Structural Contribution", "Full Decomposition"):
        assert marker in body, marker
    for pres in solvency.PRESIDENTS:
        assert pres["name"] in body, pres["name"]


def test_route_publishes_the_uncertainty_not_just_the_ranking(client):
    body = client.get("/solvency-index").data.decode()
    assert "indistinguishable from zero" in body
    assert "no party signal" in body.lower()
    assert "budget-responsibility convention" in body
    assert "No exogenous-shock adjustment" in body


def test_route_publishes_both_regression_diagnostics(client):
    body = client.get("/solvency-index").data.decode()
    comparison = solvency.presidential_comparison()
    assert f"{comparison['cyclical_model']['r2']:.3f}" in body
    assert f"{comparison['reversion_model']['r2']:.3f}" in body


# --- Executive summary -----------------------------------------------------
#
# The summary card makes definite claims in prose. These tests guard the claims,
# not the wording: if the annual rebuild ever stops supporting a sentence, the
# test fails rather than the page quietly asserting something untrue.


def test_summary_matches_the_published_series():
    summary = solvency.executive_summary()
    latest = solvency.latest_row()
    assert summary["year"] == latest["year"]
    assert summary["score"] == latest["score"]
    assert summary["points_above_baseline"] == pytest.approx(
        latest["score"] - solvency.SCALE_MIN, abs=0.05
    )
    assert summary["level"] == latest["level_label"]


def test_summary_peak_and_trough_are_the_real_extremes():
    summary = solvency.executive_summary()
    scores = [r["score"] for r in solvency.get_history()]
    assert summary["peak"]["score"] == max(scores)
    assert summary["trough"]["score"] == min(scores)


def test_summary_interest_burden_high_claim_is_checked_not_assumed():
    """The card says the interest burden is either a series high or near one.
    Whichever it says must follow from the data."""
    summary = solvency.executive_summary()
    burdens = [
        (r["year"], r["raw_values"]["interest_burden"])
        for r in solvency.get_history()
        if r["raw_values"]["interest_burden"] is not None
    ]
    worst_year, worst = max(burdens, key=lambda t: t[1])
    assert summary["worst_burden_year"] == worst_year
    assert summary["worst_burden"] == worst
    assert summary["interest_burden_is_series_high"] == (worst_year == summary["year"])


def test_summary_decade_claim_holds():
    """'Highest of any decade since the X' must name a decade that really was
    higher, and every decade in between must really be lower."""
    summary = solvency.executive_summary()
    decades = solvency.decade_averages()
    current = summary["current_decade"]
    prior = summary["prior_worst_decade"]
    assert prior["mean"] >= current["mean"], "the named decade must actually be higher"
    between = [d for d in decades[:-1] if d["start"] > prior["start"]]
    assert all(d["mean"] < current["mean"] for d in between), (
        "a decade between the named one and now is higher, so the claim is wrong"
    )


def test_summary_names_only_statistically_separable_presidents():
    """The card names 'best' and 'worst' presidents. Only administrations that
    clear the error band may be named."""
    summary = solvency.executive_summary()
    comparison = solvency.presidential_comparison()
    named = [r["name"] for r in summary["reducers"] + summary["adders"]]
    assert named, "at least one term should separate from the noise"
    for name in named:
        row = next(r for r in comparison["rows"] if r["name"] == name)
        assert abs(row["residual"]) > comparison["residual_sd"], name
    assert all(r["residual"] < 0 for r in summary["reducers"])
    assert all(r["residual"] > 0 for r in summary["adders"])


def test_summary_party_claim_is_guarded():
    """The card states there is no party signal. That must remain true."""
    summary = solvency.executive_summary()
    assert summary["party_gap"] < summary["residual_sd"]
    assert summary["party_gap_ratio"] < 1.0


def test_summary_quadrant_matches_the_quadrant_panel():
    summary = solvency.executive_summary()
    current = next(q for q in solvency.quadrant_counts() if q["current"])
    assert summary["quadrant"]["key"] == current["key"]


def test_summary_lever_comparison_is_the_right_way_round():
    """The card claims tightening the primary deficit buys more time than
    de-dollarisation costs. If that ordering flips, the sentence is wrong."""
    summary = solvency.executive_summary()
    assert summary["sim_tight_pb"] > summary["fiscal_dominance"]["latest"] or (
        summary["sim_tight_pb"] > summary["sim_loose_pb"]
    )
    assert summary["sim_loose_pb"] <= summary["fiscal_dominance"]["latest"]
    assert summary["sim_full_shift"] <= summary["fiscal_dominance"]["latest"]


def test_summary_recent_decomposition_signs():
    """The card says inflation eroded debt while policy added to it. Both signs
    must hold for that sentence to be true."""
    summary = solvency.executive_summary()
    assert summary["snowball_5y"] < 0, "snowball should have been eroding the ratio"
    assert summary["primary_5y"] > 0, "the primary deficit should have been adding to it"


def test_route_renders_the_executive_summary(client):
    body = client.get("/solvency-index").data.decode()
    summary = solvency.executive_summary()
    assert "Executive Summary" in body
    assert "Bottom line" in body
    # The prose quotes these; if the wiring breaks they silently vanish.
    assert f"{summary['score']:.1f}" in body
    assert str(summary["fiscal_dominance"]["earliest"]) in body
    assert str(summary["sim_tight_pb"]) in body
    for row in summary["reducers"] + summary["adders"]:
        assert row["name"] in body


def test_route_summary_does_not_overclaim(client):
    """It must carry the not-advice caveat and must not present the ranking as
    settled."""
    body = client.get("/solvency-index").data.decode()
    assert "not a forecast and not investment advice" in body
    assert "not distinguishable from one another" in body


# --- Defence burden and wars -----------------------------------------------


def test_defence_series_covers_the_history():
    series = solvency.defence_series()
    assert len(series) == len(solvency.get_history())
    populated = [d for d in series if d["defence"] is not None]
    assert len(populated) >= 75


def test_defence_burden_matches_the_record():
    """Spot-checks against the published defence share. Catches a units slip in
    the FRED join."""
    by_year = {d["year"]: d["defence"] for d in solvency.defence_series()}
    assert 35.0 < by_year[1945] < 40.0, "WWII final year should be ~37% of GDP"
    assert 12.0 < by_year[1953] < 18.0, "Korea peak should be mid-teens"
    assert 2.5 < by_year[2025] < 5.0, "today should be low single digits"


def test_defence_burden_summary_ranking_is_consistent():
    summary = solvency.defence_burden_summary()
    values = [d["defence"] for d in solvency.defence_series() if d["defence"] is not None]
    assert summary["highest"]["defence"] == max(values)
    assert summary["lowest"]["defence"] == min(values)
    assert 1 <= summary["rank_from_bottom"] <= summary["total"]
    assert summary["is_near_record_low"] == (summary["rank_from_bottom"] <= 5)


def test_defence_is_historically_low_today():
    """The page states today's burden is near a post-war low even with a $1tn
    budget. If that stops being true the sentence must change."""
    summary = solvency.defence_burden_summary()
    assert summary["defence"] < summary["highest"]["defence"] / 3


def test_war_periods_are_measured_within_the_series():
    periods = solvency.war_periods_measured()
    years = {r["year"] for r in solvency.get_history()}
    assert len(periods) == len(solvency.WAR_PERIODS)
    for period in periods:
        assert period["start"] in years and period["end"] in years
        assert period["peak_defence"] is not None
        assert period["debt_gdp_change"] is not None


def test_crs_war_table_is_internally_consistent():
    """Constant dollars must exceed then-year dollars for every pre-2011 war,
    and the war's own share cannot exceed total defence at the peak."""
    for war in solvency.CRS_WAR_COSTS:
        assert war["constant2011_bn"] >= war["current_bn"], war["war"]
        assert war["war_pct_gdp_peak"] <= war["defence_pct_gdp_peak"] + 0.01, war["war"]
        assert war["source"] if "source" in war else True


def test_crs_wwii_matches_the_measured_series():
    """CRS puts total defence at 37.5% of GDP in 1945; the FRED-derived series
    should agree closely. A wide gap means one of them is being misread."""
    wwii = next(w for w in solvency.CRS_WAR_COSTS if w["war"] == "World War II")
    measured = next(d["defence"] for d in solvency.defence_series() if d["year"] == 1945)
    assert abs(measured - wwii["defence_pct_gdp_peak"]) < 2.0


# --- Debt by administration ------------------------------------------------


def test_debt_by_administration_covers_every_term():
    result = solvency.debt_by_administration()
    assert len(result["rows"]) == len(solvency.PRESIDENTS)


def test_debt_added_reconciles_with_the_stock():
    for row in solvency.debt_by_administration()["rows"]:
        assert row["nominal_added_bn"] == pytest.approx(
            row["debt_end_bn"] - row["debt_start_bn"], abs=0.2
        ), row["id"]
        assert row["debt_gdp_change"] == pytest.approx(
            row["debt_gdp_end"] - row["debt_gdp_start"], abs=0.15
        ), row["id"]


def test_debt_rows_are_sorted_by_share_of_gdp():
    changes = [r["debt_gdp_change"] for r in solvency.debt_by_administration()["rows"]]
    assert changes == sorted(changes, reverse=True)


def test_the_three_debt_measures_disagree():
    """The panel's whole argument is that nominal, real and share-of-GDP
    rankings pick different presidents. If they ever agreed, the framing would
    need rewriting rather than the test relaxing."""
    result = solvency.debt_by_administration()
    winners = {
        result["top_nominal"]["id"],
        result["top_real"]["id"],
        result["top_share"]["id"],
    }
    assert len(winners) > 1, "nominal and real/share rankings should not coincide"


def test_nominal_ranking_is_biased_toward_recent_terms():
    """The stated reason to distrust nominal dollars: it sorts by era. The
    nominal leader should be a modern president."""
    result = solvency.debt_by_administration()
    assert result["top_nominal"]["first"] > 2000


def test_truman_is_the_largest_reducer_by_share():
    result = solvency.debt_by_administration()
    assert result["bottom_share"]["id"] == "truman"
    assert result["bottom_share"]["debt_gdp_change"] < -30


# --- Items enacted after the series ends -----------------------------------


def test_fiscal_items_are_sourced():
    for item in solvency.FISCAL_ITEMS:
        assert item["source"] and item["source_url"].startswith("https://"), item["key"]
        assert item["note"]


def test_obbba_converts_to_a_plausible_share_of_gdp():
    result = solvency.fiscal_items_with_impact()
    obbba = next(i for i in result["entries"] if i["key"] == "obbba")
    # $3.4tn over a ten-year window on a ~$30tn economy is order 1% of GDP a year.
    assert 0.5 < obbba["pct_gdp_per_year"] < 1.5
    assert obbba["pct_gdp_per_year_extended"] > obbba["pct_gdp_per_year"]


def test_obbba_worsens_the_path_and_costs_years():
    result = solvency.fiscal_items_with_impact()
    assert result["obbba_end_debt"] > result["baseline_end_debt"]
    assert result["obbba_crossing"] <= result["baseline_crossing"]
    assert result["years_lost"] >= 1


def test_legislation_dwarfs_the_conflict_fiscally():
    """The panel's headline comparison. Guarded because it is counterintuitive
    and would be embarrassing to state if it stopped being true."""
    result = solvency.fiscal_items_with_impact()
    assert result["obbba_vs_iran_ratio"] > 10
    assert result["obbba_cumulative_pct_gdp"] > result["iran_pct_gdp"] * 10


def test_pending_items_are_not_in_the_measured_series():
    """The index must still end at the last closed fiscal year. If a projection
    ever leaks into the history, this catches it."""
    history = solvency.get_history()
    assert history[-1]["year"] == solvency.latest_row()["year"]
    assert all(r["year"] <= history[-1]["year"] for r in history)


# --- Route -----------------------------------------------------------------


def test_route_renders_war_and_debt_panels(client):
    body = client.get("/solvency-index").data.decode()
    for marker in ("echart-war-container", "Enacted Since the Data Ends",
                   "Debt Added, by Administration", "Wars and the Defence Burden"):
        assert marker in body, marker


def test_route_cites_war_and_legislation_sources(client):
    body = client.get("/solvency-index").data.decode()
    assert "RS22926" in body, "CRS war-cost table must be cited"
    assert "Costs of War" in body, "the Brown estimate must be named alongside CRS"
    for item in solvency.FISCAL_ITEMS:
        assert item["source_url"] in body, item["key"]


def test_route_marks_projections_as_outside_the_index(client):
    body = client.get("/solvency-index").data.decode()
    assert "Why these are listed rather than added in" in body
    assert "no longer a measurement" in body
