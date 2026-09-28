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
    assert "<loc>https://mydatalabs.in/indices/airline-pressure</loc>" in xml_data
    assert "<loc>https://mydatalabs.in/indices/hormuz-crisis</loc>" in xml_data
    assert "<loc>https://mydatalabs.in/indices/us-solvency</loc>" in xml_data
    assert "<loc>https://mydatalabs.in/indices/democracy-index</loc>" in xml_data
    assert "<loc>https://mydatalabs.in/india-story/lok-sabha-projection</loc>" in xml_data
    assert "<loc>https://mydatalabs.in/lab-notes</loc>" in xml_data
    assert "<loc>https://mydatalabs.in/lab-notes/cross-cultural-metric-normalization</loc>" in xml_data
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


def test_india_story_and_indices_menu_structure(client):
    """Indices, India Story and Lab Notes are distinct dropdown sections."""
    from app.routes import build_nav

    nav = {item["label"]: item for item in build_nav("main.home")}
    assert [item["label"] for item in build_nav("main.home")] == [
        "Home", "Indices", "India Story", "Lab Notes", "About",
    ]
    assert nav["Indices"]["kind"] == "menu"
    assert nav["India Story"]["kind"] == "menu"
    assert nav["Lab Notes"]["kind"] == "menu"
    assert nav["Home"]["kind"] == "link"
    assert nav["About"]["kind"] == "link"

    # Lok Sabha is NOT in Indices dropdown
    assert "/india-story/lok-sabha-projection" not in {i.get("url") for i in nav["Indices"]["items"]}
    assert "/lok-sabha-index" not in {i.get("url") for i in nav["Indices"]["items"]}

    # Indices dropdown has exactly the 4 requested indices
    assert len(nav["Indices"]["items"]) == 4
    assert [i["label"] for i in nav["Indices"]["items"]] == [
        "Hormuz Crisis Index",
        "Airline Pressure Index",
        "U.S. Sovereign Solvency Index",
        "Hard-Metric Democracy Index",
    ]

    # India Story dropdown has Lok Sabha + 2 upcoming items
    assert [i["label"] for i in nav["India Story"]["items"]] == [
        "Lok Sabha Projection Engine",
        "State Assembly Swing Models",
        "India Macro & Capex Tracker",
    ]
    assert nav["India Story"]["items"][0]["url"] == "/india-story/lok-sabha-projection"
    assert nav["India Story"]["items"][1]["badge"] == "Upcoming"
    assert nav["India Story"]["items"][1]["disabled"] is True
    assert nav["India Story"]["items"][2]["badge"] == "Upcoming"
    assert nav["India Story"]["items"][2]["disabled"] is True

    # Lab Notes dropdown is built from LAB_NOTES: latest notes, then the archive
    assert [i["label"] for i in nav["Lab Notes"]["items"]] == [
        "IMDb Rating Deflation",
        "All Lab Notes",
    ]
    assert nav["Lab Notes"]["items"][0]["url"] == "/lab-notes/cross-cultural-metric-normalization"
    assert nav["Lab Notes"]["items"][1]["url"] == "/lab-notes"


@pytest.mark.parametrize(
    "path,label",
    [("/", "Home"), ("/about", "About")],
)
def test_nav_marks_the_current_page(client, path, label):
    header = _header(client.get(path).get_data(as_text=True))
    active = header[header.index('class="nav-link active"'):]
    assert label in active[:active.index("</a>")]
    assert header.count('aria-current="page"') >= 1


def test_dropdown_active_states(client):
    """Dropdown menus light up when their child pages are active."""
    # Indices dropdown active on Hormuz
    header_indices = _header(client.get("/indices/hormuz-crisis").get_data(as_text=True))
    assert "dropdown-toggle active" in header_indices
    assert 'href="/indices/hormuz-crisis" aria-current="page" class="is-current"' in header_indices

    # India Story dropdown active on Lok Sabha
    header_india = _header(client.get("/india-story/lok-sabha-projection").get_data(as_text=True))
    assert "dropdown-toggle active" in header_india
    assert 'href="/india-story/lok-sabha-projection" aria-current="page" class="is-current"' in header_india

    # Lab Notes dropdown active on IMDB note
    header_lab = _header(client.get("/lab-notes/cross-cultural-metric-normalization").get_data(as_text=True))
    assert "dropdown-toggle active" in header_lab
    assert 'href="/lab-notes/cross-cultural-metric-normalization" aria-current="page" class="is-current"' in header_lab

    # Lab Notes dropdown active on Archive
    header_lab_arc = _header(client.get("/lab-notes").get_data(as_text=True))
    assert "dropdown-toggle active" in header_lab_arc
    assert 'href="/lab-notes" aria-current="page" class="is-current"' in header_lab_arc


def test_every_page_including_errors_carries_the_nav(client):
    """404 and 500 render outside a route context, and are the pages a visitor
    most needs a way off — so the nav is injected app-wide, not per-route."""
    for path in ("/", "/indices/hormuz-crisis", "/india-story/lok-sabha-projection", "/lab-notes", "/about", "/no-such-page"):
        header = _header(client.get(path).get_data(as_text=True))
        assert 'aria-label="Primary"' in header
        # And the drawer, which is the only navigation below 900px.
        assert 'id="mobile-nav"' in header
        assert "/india-story/lok-sabha-projection" in header


def test_legacy_routes_resolve(client):
    """Legacy routes continue to resolve so existing links and bookmarks work."""
    for path in ("/hormuz-index", "/airline-index", "/solvency-index", "/democracy-index", "/lok-sabha-index"):
        resp = client.get(path)
        assert resp.status_code in (200, 301, 302)


def test_lab_notes_article_and_archive(client):
    """Lab Notes archive and article render from the LAB_NOTES registry."""
    res_arc = client.get("/lab-notes")
    assert res_arc.status_code == 200
    arc_text = res_arc.get_data(as_text=True)
    assert "Why Raw Scores Lie" in arc_text
    assert "/lab-notes/cross-cultural-metric-normalization" in arc_text
    assert "Sanjoy" not in arc_text

    res_art = client.get("/lab-notes/cross-cultural-metric-normalization")
    assert res_art.status_code == 200
    art_text = res_art.get_data(as_text=True)
    assert "Sanjoy" not in art_text
    assert "Why Raw Scores Lie" in art_text
    assert "Heart of the Beast" in art_text
    # The example is illustrative, and the page has to say so up front.
    assert "worked example, not a measured study" in art_text
    assert "100-film" in art_text
    assert "Top Gun: Maverick" in art_text
    assert "Oppenheimer" in art_text
    assert '"datePublished": "2026-09-27"' in art_text
    # No leftover LaTeX or markdown from the first draft.
    for junk in ("\text{", "$N$", "*Hochdeutsch*"):
        assert junk not in art_text


def test_unknown_lab_note_is_404(client):
    assert client.get("/lab-notes/no-such-note").status_code == 404


def test_every_lab_note_is_in_sitemap_and_llms(client):
    from app.routes import LAB_NOTES
    xml = client.get("/sitemap.xml").get_data(as_text=True)
    llms = client.get("/llms.txt").get_data(as_text=True)
    for n in LAB_NOTES:
        assert f"https://mydatalabs.in{n['url']}</loc>" in xml
        assert n["url"] in llms
