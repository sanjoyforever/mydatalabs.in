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
    assert "<loc>https://mydatalabs.in/about</loc>" in xml_data
    assert "<loc>https://mydatalabs.in/terms</loc>" in xml_data

    # Must NOT contain hidden / API / data pages
    assert "/data" not in xml_data
    assert "/api" not in xml_data


@pytest.mark.parametrize("path", [
    "/data",
    "/api/hormuz-index/data.json",
    "/api/hormuz-index/data.csv",
    "/api/lok-sabha-index/overview",
    "/api/lok-sabha-index/daily_forecast",
    "/api/lok-sabha-index/trend_analytics",
    "/api/lok-sabha-index/events",
    "/api/lok-sabha-index/metrics_catalog",
    "/api/lok-sabha-index/sentiment_breakdown",
    "/api/lok-sabha-index/calibration",
    "/api/lok-sabha-index/ml_comparison",
    "/api/lok-sabha-index/backtest_results",
    "/api/lok-sabha-index/state_projections",
    "/api/lok-sabha-index/insights",
    "/api/lok-sabha-index/data_status",
])
def test_no_public_data_endpoints(client, path):
    """The site publishes no machine-readable feed of any dataset.

    Every route here used to hand out the underlying series. They were removed
    deliberately, so a 404 is the assertion — reintroducing one by accident
    (a stray blueprint, a copied route) fails this test.
    """
    assert client.get(path).status_code == 404


def test_no_permutation_simulation_endpoint(client):
    """The one POST that computed a dataset answer for callers is gone too."""
    assert client.post(
        "/api/lok-sabha-index/simulate_permutation", json={}
    ).status_code == 404


def test_pages_advertise_no_api(client):
    """Nothing on a rendered page should point a reader at a data endpoint."""
    for path in ("/", "/hormuz-index", "/lok-sabha-index", "/about", "/terms"):
        html_data = client.get(path).get_data(as_text=True)
        assert "data.json" not in html_data, path
        assert "data.csv" not in html_data, path
        assert 'rel="alternate"' not in html_data, path


def test_llms_txt_offers_no_downloads(client):
    """llms.txt tells crawlers what exists; it must not point at a feed."""
    txt = client.get("/llms.txt").get_data(as_text=True)
    assert "/api/" not in txt
    assert "Machine-readable data" not in txt


def test_llms_txt_states_the_real_manual_share(client):
    """The file makes a data-quality claim to crawlers, so it has to be true.

    It was hardcoded as "four of seven components (50% of index weight)" and
    stayed that way after ship traffic was automated, overstating for months
    how much of the index is keyed by hand.
    """
    from app.indices import hormuz

    manual = [c for c in hormuz.COMPONENTS if c.manual]
    expected = round(sum(c.weight for c in manual) * 100)

    txt = client.get("/llms.txt").get_data(as_text=True)
    assert f"{len(manual)} of the {len(hormuz.COMPONENTS)} components ({expected}% of index weight)" in txt


def test_favicon_is_served(client):
    """/favicon.ico serves the real file.

    It is the one route no page links to and no other test exercises, so a
    missing import in its handler went unnoticed until it 500'd in review.
    """
    response = client.get("/favicon.ico")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "image/x-icon"
    assert len(response.get_data()) > 0


@pytest.mark.parametrize(
    "path",
    ["/", "/airline-index", "/hormuz-index", "/lok-sabha-index", "/about", "/terms"],
)
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


def test_about_page_renders_and_is_linked_from_the_nav(client):
    """The About page is the site's motivation, so every page must reach it."""
    response = client.get("/about")
    assert response.status_code == 200
    html_data = response.get_data(as_text=True)
    assert "Quantifying the unquantifiable" in html_data
    # The nav entry that used to point at /terms now points here.
    assert 'href="/about"' in html_data
    # /terms lost its nav slot, so the footer link is its only route in.
    assert 'href="/terms"' in html_data


def test_about_page_lists_every_live_index_and_defers_to_its_methodology(client):
    """About argues why a number exists; each dashboard documents how it is built.

    So every live index needs a row here, and every row has to hand the reader
    on to that index's own methodology rather than restate its weights.
    """
    from app.routes import REPORTS, _about_indices

    rows = {row["slug"]: row for row in _about_indices()}
    assert set(rows) == {r["slug"] for r in REPORTS}
    assert all(row.get("compresses") and row.get("cadence") for row in rows.values())

    html_data = client.get("/about").get_data(as_text=True)
    for report in REPORTS:
        assert report["title"] in html_data
        assert f'href="{report["url"]}#methodology"' in html_data


def _header(html_data):
    """Just the site header, so a body link cannot satisfy a nav assertion."""
    return html_data[html_data.index("<header"):html_data.index("</header>")]


def test_nav_reaches_every_live_index_and_has_no_dead_links(client):
    """The header is generated from REPORTS, so it cannot drift from reality.

    It previously hand-listed seven links, which is how it ended up carrying a
    "Global" entry pointing at href="#" and two labels ("Intelligence",
    "India") that named no page a reader could have guessed.
    """
    from app.routes import REPORTS

    header = _header(client.get("/").get_data(as_text=True))
    for report in REPORTS:
        assert f'href="{report["url"]}"' in header, report["slug"]
    # Anything reached through the dropdown is named there in full. The India
    # section is the exception on purpose: it is one link under its own label,
    # not a menu row, so the section name is what the header shows.
    for report in REPORTS:
        if report["nav_group"] == "indices":
            assert report["title"] in header, report["slug"]
    assert 'href="#"' not in header


def test_india_is_top_level_and_not_inside_the_indices_menu(client):
    """India is its own section, not one more row in the Indices dropdown."""
    from app.routes import build_nav

    nav = {item["label"]: item for item in build_nav("main.home")}
    assert [item["label"] for item in build_nav("main.home")] == [
        "Home", "Indices", "India", "About",
    ]
    assert nav["India"]["kind"] == "link"
    assert nav["India"]["url"] == "/lok-sabha-index"
    assert nav["Indices"]["kind"] == "menu"
    assert "/lok-sabha-index" not in {i["url"] for i in nav["Indices"]["items"]}


def test_a_group_collapses_to_a_link_and_disappears_when_empty(monkeypatch):
    """A dropdown in front of one page is a click and a hover for nothing, and
    a menu with nothing live behind it is how the dead "Global" link lasted."""
    from app import routes

    monkeypatch.setattr(
        routes, "REPORTS",
        [r for r in routes.REPORTS if r["nav_group"] == "indices"][:1],
    )
    labels = {item["label"]: item for item in routes.build_nav("main.home")}
    assert "India" not in labels
    assert labels["Indices"]["kind"] == "link"


@pytest.mark.parametrize(
    "path,label",
    [("/", "Home"), ("/lok-sabha-index", "India"), ("/about", "About")],
)
def test_nav_marks_the_current_page(client, path, label):
    header = _header(client.get(path).get_data(as_text=True))
    active = header[header.index('class="nav-link active"'):]
    assert label in active[:active.index("</a>")]
    assert header.count('aria-current="page"') >= 1


def test_index_pages_mark_the_indices_menu_active(client):
    """An index inside the dropdown still has to light its parent up."""
    header = _header(client.get("/hormuz-index").get_data(as_text=True))
    assert "dropdown-toggle active" in header
    assert 'href="/hormuz-index" aria-current="page" class="is-current"' in header


def test_every_page_including_errors_carries_the_nav(client):
    """404 and 500 render outside a route context, and are the pages a visitor
    most needs a way off — so the nav is injected app-wide, not per-route."""
    for path in ("/", "/hormuz-index", "/lok-sabha-index", "/about", "/no-such-page"):
        header = _header(client.get(path).get_data(as_text=True))
        assert 'aria-label="Primary"' in header
        # And the drawer, which is the only navigation below 900px.
        assert 'id="mobile-nav"' in header
        assert "/lok-sabha-index" in header
