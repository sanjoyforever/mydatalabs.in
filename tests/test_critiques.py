"""Tests for reader critiques: validation, link detection, and admin gating.

Nothing here touches the database. The rules that decide whether a submission
is accepted all run before the first query (see ``critiques.submit``), which is
what makes them cheap to test and is also why they are ordered that way: a
malformed or spammy submission should not cost a round trip to Neon.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, critiques


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def _payload(**overrides):
    payload = {
        "verdict": "wrong",
        "target": "brent",
        "body": "The Brent weighting is too high given that 2026 volumes fell.",
        "elapsed": 30,
    }
    payload.update(overrides)
    return payload


# --- Target whitelists -----------------------------------------------------

def test_targets_come_from_the_index_definitions():
    """A report's own components must appear as critique targets."""
    keys = [key for key, _ in critiques.targets_for("hormuz")]
    assert "brent" in keys
    assert "ship_traffic" in keys
    # ...followed by the generic targets every report shares.
    assert "weighting" in keys
    assert "conclusion" in keys


def test_report_without_components_still_has_generic_targets():
    keys = [key for key, _ in critiques.targets_for("elections")]
    assert keys == [key for key, _ in critiques.GENERIC_TARGETS]


def test_unknown_report_has_no_targets():
    assert critiques.targets_for("not-a-report") == []


# --- Validation ------------------------------------------------------------

def test_valid_submission_passes():
    fields = critiques.validate(_payload(), "hormuz")
    assert fields["verdict"] == "wrong"
    assert fields["target_key"] == "brent"


@pytest.mark.parametrize("overrides", [
    {"verdict": ""},
    {"verdict": "excellent"},
    {"target": ""},
    {"target": "made_up_key"},
    {"body": "useless"},
])
def test_malformed_submissions_are_refused(overrides):
    with pytest.raises(critiques.CritiqueRejected):
        critiques.validate(_payload(**overrides), "hormuz")


def test_body_below_the_minimum_is_refused():
    """The length floor is what turns a mood into an argument."""
    short = "x" * (critiques.MIN_BODY - 1)
    with pytest.raises(critiques.CritiqueRejected):
        critiques.validate(_payload(body=short), "hormuz")


def test_a_target_from_another_report_is_refused():
    """Component keys are scoped to their own report, not pooled."""
    with pytest.raises(critiques.CritiqueRejected):
        critiques.validate(_payload(target="debt_gdp"), "hormuz")


# --- Bot filters -----------------------------------------------------------

def test_honeypot_field_rejects():
    with pytest.raises(critiques.CritiqueRejected):
        critiques.check_honeypot(_payload(website="http://spam.example"))


def test_instant_submission_rejects():
    with pytest.raises(critiques.CritiqueRejected):
        critiques.check_honeypot(_payload(elapsed=1))


def test_honest_timing_passes():
    critiques.check_honeypot(_payload(elapsed=45))


# --- Link detection --------------------------------------------------------

@pytest.mark.parametrize("text", [
    "check out https://spam.example.com now",
    "visit www.spam.com",
    "go to spam dot com for details",
    "see spam(dot)com",
    "see spam [dot] com",
    "mail me at foo@bar.com",
    "hxxp://evil.co",
    "ping me @spamhandle",
    "call +91 98765 43210",
    "join t.me/spamchan",
    "h t t p : / / spam.com",
    "SPAM.COM is better",
    # Cyrillic 'a' — visually identical, and a working domain.
    "the site is spаm.com",
    # Zero-width space mid-domain.
    "the site is spa​m.com",
])
def test_obfuscated_links_are_caught(text):
    assert critiques.find_link(text) is not None


@pytest.mark.parametrize("text", [
    "The Brent weighting of 20% is too high given that volumes fell sharply.",
    "Your baseline covers Jan 2026, which predates the tanker war entirely.",
    "The r minus g component double counts inflation already in the CPI series.",
    "In 2026 the index moved 1,200 points, which cannot be right at all.",
    "IMF PortWatch data lags by 8 days, so the transit figure is always stale.",
])
def test_ordinary_critiques_are_not_false_positives(text):
    assert critiques.find_link(text) is None


def test_link_anywhere_in_the_submission_is_refused():
    long_tail = " and the rest of the argument follows here at length."
    for field in ("body", "remedy", "display_name"):
        payload = _payload(**{field: "see spam.com" + long_tail})
        with pytest.raises(critiques.CritiqueRejected):
            critiques.validate(payload, "hormuz")


def test_folding_is_for_detection_only():
    """The reader's own text must never be rewritten by the spam check."""
    original = "The r−g component is wrong because of the 2026 revision."
    fields = critiques.validate(_payload(body=original), "hormuz")
    assert "−" in fields["body"]


# --- Publication state -----------------------------------------------------

def test_pending_is_not_a_public_status():
    """The queue is the whole point: nothing is visible until a human moves it."""
    assert "pending" not in critiques.PUBLIC_STATUSES
    assert "rejected" not in critiques.PUBLIC_STATUSES
    assert set(critiques.PUBLIC_STATUSES) == {"published", "accepted"}


# --- Routes ----------------------------------------------------------------

def test_form_endpoint_lists_targets(client):
    payload = client.get("/api/hormuz/critique").get_json()
    assert payload["report"] == "hormuz"
    assert len(payload["targets"]) == len(critiques.targets_for("hormuz"))
    assert payload["min_body"] == critiques.MIN_BODY


def test_form_endpoint_404s_on_unknown_report(client):
    assert client.get("/api/nonsense/critique").status_code == 404


def test_submission_without_a_token_is_refused(client):
    resp = client.post("/api/hormuz/critique", json=_payload())
    assert resp.status_code == 400


def test_rejected_submission_answers_422_with_a_readable_reason(client):
    resp = client.post(
        "/api/hormuz/critique",
        json=_payload(body="useless"),
        headers={"X-Voter-Token": "a" * 24},
    )
    # 503 when no database is configured in the environment running the tests;
    # either way it must not be a 500, and must never be a 200.
    assert resp.status_code in (422, 503)
    assert "error" in resp.get_json()


def test_admin_is_absent_without_credentials(monkeypatch):
    """No signing key or password hash means no admin blueprint at all."""
    monkeypatch.delenv("ADMIN_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        assert client.get("/admin/queue").status_code == 404


def test_admin_requires_login_and_is_never_indexed(monkeypatch):
    from werkzeug.security import generate_password_hash

    monkeypatch.setenv("SECRET_KEY", "test-only-key")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", generate_password_hash("s3cret-passphrase"))
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        assert client.get("/admin/queue").status_code == 302  # to the login page
        resp = client.get("/admin/login")
        assert resp.status_code == 200
        assert "noindex" in resp.headers.get("X-Robots-Tag", "")
        assert "no-store" in resp.headers.get("Cache-Control", "")


def test_robots_does_not_block_admin(client):
    """A path blocked in robots.txt is one whose noindex header is never read."""
    body = client.get("/robots.txt").get_data(as_text=True)
    assert "/admin" not in body
