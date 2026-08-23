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
    assert "<loc>https://mydatalabs.in/airline-index</loc>" in xml_data
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


@pytest.mark.parametrize("path", ["/", "/airline-index", "/hormuz-index", "/lok-sabha-index", "/terms"])
def test_analytics_tags_render_on_every_page(client, path):
    """GA4 and Clarity are sitewide, so they belong on every rendered page."""
    html_data = client.get(path).get_data(as_text=True)
    assert "googletagmanager.com/gtag/js" in html_data
    assert "clarity.ms/tag/" in html_data


def test_analytics_tags_render_on_error_pages(client):
    """Error templates extend base.html but bypass the normal route context."""
    response = client.get("/no-such-page-exists")
    assert response.status_code == 404
    html_data = response.get_data(as_text=True)
    assert "googletagmanager.com/gtag/js" in html_data
    assert "clarity.ms/tag/" in html_data


def test_csp_permits_the_analytics_tags_it_serves(client):
    """A tag the CSP blocks fails silently — nothing renders, nothing errors.

    Both scripts are injected by base.html, so every origin they load and beacon
    to has to be allow-listed or the tag is dead on arrival in the browser.
    """
    csp = client.get("/").headers["Content-Security-Policy"]
    directives = dict(
        (part.split(" ", 1) + [""])[:2]
        for part in (p.strip() for p in csp.split(";"))
        if part
    )

    assert "https://www.googletagmanager.com" in directives["script-src"]
    assert "https://*.clarity.ms" in directives["script-src"]
    # Clarity's recorder ships payloads to *.clarity.ms and c.bing.com.
    assert "https://*.clarity.ms" in directives["connect-src"]
    assert "https://c.bing.com" in directives["connect-src"]
    # Neither tag can fall back to default-src 'self'.
    assert directives["default-src"] == "'self'"
