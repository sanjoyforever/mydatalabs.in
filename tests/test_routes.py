"""Tests for application routes and crawler-facing endpoints."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_sitemap_contains_only_visible_pages(client):
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert response.mimetype == "application/xml"
    xml_data = response.get_data(as_text=True)

    # Must contain visible pages
    assert "<loc>https://mydatalabs.in/</loc>" in xml_data
    assert "<loc>https://mydatalabs.in/hormuz-index</loc>" in xml_data
    assert "<loc>https://mydatalabs.in/lok-sabha-index</loc>" in xml_data
    assert "<loc>https://mydatalabs.in/terms</loc>" in xml_data

    # Must NOT contain hidden / API / data pages
    assert "/data" not in xml_data
    assert "/api" not in xml_data


def test_data_route_redirects(client):
    response = client.get("/data")
    assert response.status_code == 301
    assert response.headers["Location"] == "/api/hormuz-index/data.json"
