"""Tests for the Hard-Metric Democracy Index.

These pin the things that were actually wrong in the source engine, so a
regression reintroduces a failing test rather than a plausible-looking number:
a composite that could exceed its own documented scale, two indicators that
were the same indicator, and an aggregation that let a monopoly legislature be
averaged away.
"""

import json
import math
import os

import pytest

from app import create_app
from app.indices import democracy


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# --- Data integrity ---------------------------------------------------------


def test_panel_is_complete():
    years = democracy.available_years()
    assert years == list(range(2000, 2025))
    for year in years:
        rows = democracy.index_for_year(year)
        assert len(rows) == len(democracy.COUNTRIES), f"{year} is missing countries"


def test_every_scored_metric_present_in_every_row():
    for row in democracy._records():
        for key in democracy.METRIC_KEYS:
            assert row.get(key) is not None, f"{row['country_code']} {row['year']} missing {key}"


def test_history_carries_anchor_flags():
    """Provenance is the load-bearing honesty claim on the page; without the
    flags the methodology tab is asserting something it cannot show."""
    meta = democracy.get_meta()
    prov = meta["provenance"]
    assert prov["total_cells"] == 9000
    assert 0.1 < prov["anchor_share"] < 0.5
    assert any(r["anchored"] for r in democracy._records())


# --- Normalisation ----------------------------------------------------------


def test_normalise_respects_direction_and_bounds():
    # turnout is higher-is-better on [20, 95]
    assert democracy.normalise("turnout_vap_pct", 20.0) == 0.0
    assert democracy.normalise("turnout_vap_pct", 95.0) == 100.0
    # gini is lower-is-better on [22, 60]
    assert democracy.normalise("gini_coefficient", 22.0) == 100.0
    assert democracy.normalise("gini_coefficient", 60.0) == 0.0


def test_normalise_clamps_outside_bounds():
    assert democracy.normalise("turnout_vap_pct", 0.0) == 0.0
    assert democracy.normalise("turnout_vap_pct", 200.0) == 100.0
    assert democracy.normalise("incarceration_rate_per_100k", 9999.0) == 0.0


# --- The weight-normalisation bug -------------------------------------------


def test_partial_weights_cannot_exceed_the_scale():
    """The engine this replaces defaulted an unmentioned pillar to 0.20 after
    normalising the mentioned ones, so weights summed to 1.8 and a composite
    reached 166.9 on a 0-100 scale."""
    rows = democracy.index_for_year(2024, {"electoral": 100.0})
    assert rows, "no rows returned"
    for row in rows:
        assert 0.0 <= row["composite"] <= 100.0, row


def test_weights_always_sum_to_one():
    for weights in ({}, None, {"electoral": 100.0}, {"electoral": 3, "economic_equity": 1}):
        w = democracy.normalise_weights(weights)
        assert set(w) == set(democracy.PILLAR_KEYS)
        assert math.isclose(sum(w.values()), 1.0, rel_tol=1e-9)


def test_all_zero_weights_falls_back_to_equal():
    w = democracy.normalise_weights({k: 0.0 for k in democracy.PILLAR_KEYS})
    assert w == democracy.DEFAULT_WEIGHTS


# --- Aggregation ------------------------------------------------------------


def test_geometric_mean_penalises_imbalance():
    """Two profiles with the same arithmetic mean must not score the same: the
    unbalanced one is what the geometric mean exists to catch."""
    balanced = {k: 50.0 for k in democracy.PILLAR_KEYS}
    lopsided = dict(zip(democracy.PILLAR_KEYS, [100.0, 100.0, 50.0, 0.0, 0.0]))

    assert math.isclose(
        democracy.arithmetic_composite(balanced),
        democracy.arithmetic_composite(lopsided),
        abs_tol=0.01,
    )
    assert democracy.composite_from_pillars(lopsided) < democracy.composite_from_pillars(balanced)


def test_geometric_equals_arithmetic_when_pillars_are_equal():
    flat = {k: 72.0 for k in democracy.PILLAR_KEYS}
    assert math.isclose(democracy.composite_from_pillars(flat), 72.0, abs_tol=0.02)


def test_zero_pillar_does_not_annihilate_the_composite():
    """A pillar floor of 1.0 keeps a genuine zero devastating without throwing
    away every other measurement in the row."""
    row = dict(zip(democracy.PILLAR_KEYS, [90.0, 90.0, 90.0, 90.0, 0.0]))
    score = democracy.composite_from_pillars(row)
    assert 0.0 < score < 40.0


def test_absolute_monarchy_lands_in_a_bottom_tier():
    """Face validity. Under the arithmetic mean the UAE scored 61.7 — four
    points below the United States — because an appointed 50%-female chamber
    was averaged against a legislature with an HHI of 10,000."""
    rows = {r["country_code"]: r for r in democracy.index_for_year(2024)}
    are = rows["ARE"]
    usa = rows["USA"]
    assert are["composite"] < usa["composite"] - 5
    assert are["composite"] < are["composite_arithmetic"]
    for code in ("CHN", "SAU"):
        assert rows[code]["composite"] < 35.0, f"{code} should reach the closed-regime tier"


def test_bottom_tier_is_reachable():
    """A tier no country can enter is a legend entry, not a classification."""
    rows = democracy.index_for_year(2024)
    assert any(r["tier"] == democracy.TIERS[-1]["label"] for r in rows)


# --- Collinearity fix -------------------------------------------------------


def test_enp_and_hhi_are_not_both_scored():
    """They are the same statistic: ENP = 10000 / HHI. Scoring both put party
    fragmentation into the composite twice, through two different pillars."""
    assert "legislative_hhi" in democracy.METRIC_KEYS
    assert "effective_parties" not in democracy.METRIC_KEYS
    assert "palma_ratio" not in democracy.METRIC_KEYS
    context_keys = {c["key"] for c in democracy.CONTEXT_METRICS}
    assert context_keys == {"effective_parties", "palma_ratio"}


def test_derived_enp_is_the_exact_inverse_of_hhi():
    for row in democracy.index_for_year(2024):
        hhi = row["metrics"]["legislative_hhi"]["raw"]
        enp = row["context"]["effective_parties"]["raw"]
        # abs_tol rather than rel_tol: the published value is rounded to 2dp.
        assert math.isclose(enp, 10000.0 / hhi, abs_tol=0.011)


def test_no_scored_pair_is_effectively_identical():
    """The two removed pairs sat at |rho| >= 0.98. Nothing left should."""
    for pair in democracy.pillar_correlations(2024):
        assert abs(pair["rho"]) < 0.95, pair


def test_every_metric_belongs_to_a_declared_pillar():
    for spec in democracy.METRICS:
        assert spec["pillar"] in democracy.PILLAR_KEYS
    covered = {k for keys in democracy.PILLAR_METRICS.values() for k in keys}
    assert covered == set(democracy.METRIC_KEYS)
    for pillar, keys in democracy.PILLAR_METRICS.items():
        assert keys, f"{pillar} has no indicators"


# --- Ranking ----------------------------------------------------------------


def test_rankings_are_dense_and_ordered():
    rows = democracy.index_for_year(2024)
    assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))
    scores = [r["composite"] for r in rows]
    assert scores == sorted(scores, reverse=True)


def test_reweighting_changes_the_order():
    """If the table survived every weighting the sliders would be decoration."""
    base = [r["country_code"] for r in democracy.index_for_year(2024)]
    skewed = [
        r["country_code"]
        for r in democracy.index_for_year(2024, {"economic_equity": 100.0})
    ]
    assert base != skewed


def test_country_history_spans_the_panel():
    hist = democracy.country_history("IND")
    assert len(hist) == 25
    assert [r["year"] for r in hist] == list(range(2000, 2025))


def test_movers_are_signed_consistently():
    for row in democracy.movers():
        assert row["delta"] == pytest.approx(row["to_score"] - row["from_score"], abs=0.011)
        assert row["rank_delta"] == row["from_rank"] - row["to_rank"]


# --- Diagnostics ------------------------------------------------------------


def test_dispersion_reports_saturation():
    disp = {d["key"]: d for d in democracy.metric_dispersion(2024)}
    assert len(disp) == len(democracy.METRIC_KEYS)
    # The information pillar's indicators are floor detectors: most of the
    # panel sits at the ceiling. If that stops being true the methodology text
    # describing them that way is wrong.
    assert disp["journalists_detained_per_10m"]["at_ceiling"] > 15


def test_anchor_coverage_is_sorted_thinnest_first():
    cov = democracy.anchor_coverage()
    assert len(cov) == len(democracy.COUNTRIES)
    assert cov == sorted(cov, key=lambda r: r["share"])
    assert all(0.0 <= r["share"] <= 1.0 for r in cov)


def test_anchor_density_covers_every_year():
    density = democracy.anchor_density()
    assert [d["year"] for d in density] == democracy.available_years()


# --- Snapshot / integration -------------------------------------------------


def test_snapshot_matches_the_panel_mean():
    snap = democracy.compute_snapshot()
    rows = democracy.index_for_year(democracy.latest_year())
    expected = sum(r["composite"] for r in rows) / len(rows)
    assert snap.score == pytest.approx(expected, abs=0.05)
    assert snap.level_status in {"good", "warning", "serious", "critical"}
    assert snap.week_start == str(democracy.latest_year())


def test_precomputed_artifact_decodes_against_the_engine():
    """The page renders from the artifact, so a stale or mis-shaped artifact is
    a wrong page rather than an error."""
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "data", "precomputed", "democracy-index.json",
    )
    with open(path, encoding="utf-8") as fh:
        art = json.load(fh)

    assert art["panel_row_schema"][0] == "composite"
    assert art["panel_row_keys"]["metrics"] == democracy.METRIC_KEYS
    assert art["panel_row_keys"]["pillars"] == democracy.PILLAR_KEYS
    assert len(art["panel_rows"]) == len(democracy.COUNTRIES) * len(democracy.available_years())

    live = {r["country_code"]: r for r in democracy.index_for_year(2024)}
    for code, row in live.items():
        packed = art["panel_rows"][f"{code}-2024"]
        assert packed[0] == pytest.approx(row["composite"], abs=0.011)
        assert packed[1] == row["rank"]
        assert packed[2] == pytest.approx([row["pillars"][p] for p in democracy.PILLAR_KEYS], abs=0.011)


def test_anchor_bitmask_round_trips():
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "data", "precomputed", "democracy-index.json",
    )
    with open(path, encoding="utf-8") as fh:
        art = json.load(fh)

    row = democracy.index_for_year(2024)[0]
    mask = art["panel_rows"][f"{row['country_code']}-2024"][5]
    for i, key in enumerate(democracy.METRIC_KEYS):
        assert bool(mask >> i & 1) == row["metrics"][key]["anchor"]


# --- Route ------------------------------------------------------------------


def test_route_renders(client):
    res = client.get("/democracy-index")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "Hard-Metric Democracy Index" in body
    # Server-rendered rankings, so the page works without JS and a crawler sees
    # the table rather than an empty tbody.
    assert "United States" in body
    assert "Norway" in body
    assert 'id="hmdi-data"' in body


def test_route_states_its_limits(client):
    """The provenance and 'what it cannot see' caveats are part of the
    deliverable, not decoration; a refactor that drops them ships a claim the
    data does not support."""
    body = client.get("/democracy-index").get_data(as_text=True)
    assert "interpolated" in body
    assert "expert survey" in body.lower()
    assert "geometric" in body.lower()


def test_index_appears_in_nav_and_home(client):
    home = client.get("/")
    assert home.status_code == 200
    assert "/democracy-index" in home.get_data(as_text=True)

    about = client.get("/about")
    assert about.status_code == 200
    assert "Hard-Metric Democracy Index" in about.get_data(as_text=True)


# --- V-Dem comparator ------------------------------------------------------


def test_vdem_covers_every_country_and_year():
    years = democracy.available_years()
    table = democracy.vdem_table()
    assert table["years"] == years
    for country in democracy.COUNTRIES:
        scores = table["scores"][country["code"]]
        ranks = table["ranks"][country["code"]]
        assert len(scores) == len(years)
        assert all(s is not None and 0.0 <= s <= 1.0 for s in scores)
        assert all(r is not None and 1 <= r <= len(democracy.COUNTRIES) for r in ranks)


def test_vdem_rank_is_within_panel_and_ordered_by_score():
    year = democracy.latest_year()
    ordered = sorted(
        democracy.COUNTRIES,
        key=lambda c: -(democracy.vdem_score(c["code"], year) or 0.0),
    )
    assert democracy.vdem_rank(ordered[0]["code"], year) == 1
    assert democracy.vdem_rank(ordered[-1]["code"], year) == len(ordered)


def test_vdem_never_enters_the_composite():
    """The comparator must not move a score. Zeroing it out of the module is
    the only test that actually proves that."""
    year = democracy.latest_year()
    before = {r["country_code"]: r["composite"] for r in democracy.index_for_year(year)}
    original = democracy._vdem_cache
    try:
        democracy._vdem_cache = {"values": {}, "years": [], "_ranks": {}}
        after = democracy.index_for_year(year)
        assert {r["country_code"]: r["composite"] for r in after} == before
        assert all(r["vdem_rank"] is None for r in after)
    finally:
        democracy._vdem_cache = original


def test_vdem_agreement_is_strong_but_not_a_restatement():
    rho = democracy.vdem_agreement()["rho"]
    assert rho is not None
    assert 0.5 < rho < 0.99


def test_vdem_column_is_rendered(client):
    body = client.get("/democracy-index").get_data(as_text=True)
    assert "hmdi-vdem-chip" in body
    assert "V-Dem" in body
    assert 'id="hmdi-vdem"' in body
