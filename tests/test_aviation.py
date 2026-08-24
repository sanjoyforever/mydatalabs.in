"""Tests for the Airline Pressure Index (API-INDEX) engine and routes."""
from __future__ import annotations

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.indices import aviation


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_aviation_components_weight_sum():
    """All 7 components must sum to 1.0 total weight."""
    total_weight = sum(c.weight for c in aviation.COMPONENTS)
    assert abs(total_weight - 1.0) < 1e-6
    assert len(aviation.COMPONENTS) == 7


def test_aviation_compute_snapshot():
    """Snapshot computation returns valid composite result within bounds."""
    snapshot = aviation.compute_snapshot(allow_network=False)
    assert 0.0 <= snapshot.score <= 200.0
    assert snapshot.level_label in [
        "Low Pressure", "Normal Baseline", "Elevated Strain", "Severe Pressure", "Critical Crisis"
    ]
    assert snapshot.level_status in ["good", "neutral", "warning", "serious", "critical"]
    assert len(snapshot.components) == 7


def test_aviation_history():
    """History returns non-empty 52-week series."""
    history = aviation.get_history()
    assert len(history) >= 50
    latest = history[-1]
    assert "week_start" in latest
    assert "score" in latest
    assert "raw_values" in latest


def test_airline_index_route(client):
    """GET /airline-index renders successfully with key elements."""
    response = client.get("/airline-index")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Airline Pressure Index" in html
    assert "API-INDEX" in html
    assert "Jet Fuel Crack Spread" in html
    assert "Stress Test Simulator" in html


def test_airline_api_disabled(client):
    """Public dataset download APIs are disabled to protect proprietary access."""
    assert client.get("/api/airline-index/data.json").status_code == 404
    assert client.get("/api/airline-index/data.csv").status_code == 404


def test_home_page_spotlight(client):
    """GET / renders Airline Pressure Index in flagship featured hero."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "AIRLINE PRESSURE INDEX" in html
    assert "Track. Analyze." in html
    assert "Fuel Crack Margins" in html


def test_aviation_regional_contributions():
    """Regional contributions return all 7 regions + global with structured breakdowns."""
    contribs = aviation.get_regional_contributions()
    assert len(contribs) == 8
    keys = [c["key"] for c in contribs]
    assert "south_asia" in keys
    assert "middle_east" in keys
    assert "europe" in keys
    assert "americas" in keys
    assert "south_east_asia" in keys
    assert "south_west_pacific" in keys
    assert "africa" in keys
    assert "global" in keys

    for c in contribs:
        assert "name" in c
        assert "total_score" in c
        assert "primary_bottleneck" in c
        assert "breakdown" in c
        assert "fleet_grounding" in c["breakdown"]
        assert "detour_pct" in c["breakdown"]
        assert "crack_spread" in c["breakdown"]


def test_aviation_milestones():
    """Aviation milestones returns structured inflection events for trajectory rises and dips."""
    milestones = aviation.get_milestones()
    assert len(milestones) >= 5
    for m in milestones:
        assert "date" in m
        assert "score" in m
        assert "type" in m
        assert "title" in m
        assert "driver" in m
        assert "description" in m


def test_airline_index_regional_chart(client):
    """GET /airline-index renders the Weekly Trajectory, Milestones, and Regional Contribution charts."""
    response = client.get("/airline-index")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Weekly Score Trajectory" in html
    assert "echart-trend-container" in html
    assert "Key Trajectory Inflections" in html
    assert "Regional Stress Contribution Analysis" in html
    assert "echart-regional-container" in html
    assert "#1 Bottleneck" in html
    assert "South Asia" in html
    assert "Middle East" in html
