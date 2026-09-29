"""Tests for reader comments: validation, anti-spam heuristics, and moderation.

Rules tested here run before touching the database to protect serverless resources.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import comments, create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def _payload(**overrides):
    payload = {
        "name": "Marcus Vance",
        "body": "The standard deviation scaling cleanly accounts for the French distribution spread.",
        "elapsed": 12.5,
        "website": "",
    }
    payload.update(overrides)
    return payload


# --- Validation & Anti-Spam ---


def test_valid_payload():
    cleaned = comments.validate(_payload(), "cross-cultural-metric-normalization")
    assert cleaned["article_slug"] == "cross-cultural-metric-normalization"
    assert cleaned["author_name"] == "Marcus Vance"
    assert "standard deviation" in cleaned["body"]


def test_body_too_short_rejected():
    with pytest.raises(comments.CommentRejected, match="at least 15 characters"):
        comments.validate(_payload(body="Too brief"), "imdb-deflation")


def test_invalid_slug_rejected():
    with pytest.raises(comments.CommentRejected, match="Invalid article identifier"):
        comments.validate(_payload(), "bad/slug/with/slashes")


def test_honeypot_rejection():
    with pytest.raises(comments.CommentRejected, match="Submission rejected"):
        comments.check_honeypot(_payload(website="https://spamsite.com"))


def test_fast_fill_elapsed_rejection():
    with pytest.raises(comments.CommentRejected, match="submitted very quickly"):
        comments.check_honeypot(_payload(elapsed=0.8))


@pytest.mark.parametrize(
    "spam_input,field",
    [
        ("Read more on https://myblog.com/seo", "comment"),
        ("Contact us at test@domain.org for queries", "comment"),
        ("Follow my channel on t.me/freecrypto now", "comment"),
        ("Call +91 9876543210 immediately", "comment"),
        ("Check out my portfolio site dot com", "comment"),
        ("See scam аpplе.соm with Cyrillic vowels", "comment"),
    ],
)
def test_link_rejection_in_body(spam_input, field):
    with pytest.raises(comments.CommentRejected, match="looks like it contains"):
        comments.validate(_payload(body=f"Important research note: {spam_input}"), "test-slug")


def test_link_rejection_in_author_name():
    with pytest.raises(comments.CommentRejected, match="looks like it contains"):
        comments.validate(_payload(name="visit myblog.com"), "test-slug")


def test_empty_author_defaults_to_none():
    cleaned = comments.validate(_payload(name="   "), "test-slug")
    assert cleaned["author_name"] is None


# --- HTTP API Endpoints ---


def test_api_comments_get(client):
    res = client.get("/api/comments/cross-cultural-metric-normalization")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert isinstance(data["comments"], list)


def test_api_comments_submit_too_short(client):
    res = client.post(
        "/api/comments/cross-cultural-metric-normalization",
        json={"body": "Short", "elapsed": 10},
    )
    assert res.status_code == 422
    data = res.get_json()
    assert "at least 15 characters" in data["error"]


def test_api_comments_submit_honeypot(client):
    res = client.post(
        "/api/comments/cross-cultural-metric-normalization",
        json={
            "body": "This is a valid length comment trying to spam.",
            "website": "bot-site.com",
            "elapsed": 10,
        },
    )
    assert res.status_code == 422
    data = res.get_json()
    assert "rejected" in data["error"]


def test_api_comments_submit_link_rejected(client):
    res = client.post(
        "/api/comments/cross-cultural-metric-normalization",
        json={
            "body": "Visit https://promosite.xyz/deals for top movies.",
            "elapsed": 10,
        },
    )
    assert res.status_code == 422
    data = res.get_json()
    assert "web address" in data["error"]


# --- Admin Access Control ---


def test_admin_comments_unauthenticated_redirects(monkeypatch):
    from werkzeug.security import generate_password_hash

    monkeypatch.setenv("SECRET_KEY", "test-only-key")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", generate_password_hash("s3cret-passphrase"))
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get("/admin/comments")
        assert res.status_code == 302
        assert "/admin/login" in res.headers["Location"]


def test_admin_moderate_comment_unauthenticated(monkeypatch):
    from werkzeug.security import generate_password_hash

    monkeypatch.setenv("SECRET_KEY", "test-only-key")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", generate_password_hash("s3cret-passphrase"))
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.post("/admin/comment/1", data={"action": "publish"})
        assert res.status_code == 302
        assert "/admin/login" in res.headers["Location"]


def test_admin_login_with_plain_password(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("ADMIN_PASSWORD", "super-secret-plain-password")
    monkeypatch.setenv("SECRET_KEY", "test-only-key")
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        # GET login page
        res = client.get("/admin/login")
        assert res.status_code == 200

        # Submit wrong password
        res = client.post("/admin/login", data={"password": "wrong-password"})
        assert res.status_code == 401

        # Submit correct password
        res = client.post("/admin/login", data={"password": "super-secret-plain-password"})
        assert res.status_code == 302
        assert "/admin/comments" in res.headers["Location"]


def test_published_comment_rendering_and_api(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test_render.db")
    monkeypatch.setattr(comments, "SQLITE_PATH", db_file)
    monkeypatch.setenv("COMMENTS_DB", "sqlite")

    slug = "cross-cultural-metric-normalization"
    sub = comments.submit(
        {
            "name": "Jane Analyst",
            "body": "This normalization methodology is sound and empirically robust.",
            "website": "",
            "elapsed": 10.0,
        },
        slug,
        voter_hash="vh_123",
        origin_hash="oh_123",
    )
    cid = sub["id"]

    # Moderate to published
    comments.moderate(cid, status="published", response="Thanks for the feedback!")

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        # 1. API endpoint returns formatted date and comment
        api_res = client.get(f"/api/comments/{slug}")
        assert api_res.status_code == 200
        data = api_res.get_json()
        assert data["ok"] is True
        assert len(data["comments"]) == 1
        c = data["comments"][0]
        assert c["author"] == "Jane Analyst"
        assert "empirically robust" in c["body"]
        assert c["response"] == "Thanks for the feedback!"
        assert c["created_at"] != ""

        # 2. Lab Note page renders comment in HTML
        page_res = client.get(f"/lab-notes/{slug}")
        assert page_res.status_code == 200
        html = page_res.get_data(as_text=True)
        assert "Jane Analyst" in html
        assert "empirically robust" in html
        assert "Thanks for the feedback!" in html
        assert "comment_submitted" in html
        assert "comment_submit" in html



def test_admin_honeypot_and_lockout(tmp_path, monkeypatch):
    from app import admin
    db_file = str(tmp_path / "test_admin_lock.db")
    monkeypatch.setattr(comments, "SQLITE_PATH", db_file)
    monkeypatch.setenv("COMMENTS_DB", "sqlite")
    monkeypatch.setenv("ADMIN_PASSWORD", "super-secret-desk-key")
    monkeypatch.setenv("SECRET_KEY", "test-only-key")
    admin._ATTEMPTS.clear()

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        # 1. Honeypot check: bot fills admin_username
        res_hp = client.post("/admin/login", data={"password": "any", "admin_username": "bot_crawler"})
        assert res_hp.status_code == 403
        assert "Access denied" in res_hp.get_data(as_text=True)

        # 2. Immediate lockout (429) following honeypot strike
        res_locked = client.post("/admin/login", data={"password": "any"})
        assert res_locked.status_code == 429
        assert "Access locked" in res_locked.get_data(as_text=True)

        # 3. Clear lockout and test normal wrong passwords up to MAX_ATTEMPTS
        admin._clear_lockout()
        admin._ATTEMPTS.clear()

        for _ in range(admin.MAX_ATTEMPTS):
            res = client.post("/admin/login", data={"password": "bad"})
            assert res.status_code in (401, 429)

        # Now locked out
        res_locked2 = client.post("/admin/login", data={"password": "bad"})
        assert res_locked2.status_code == 429

        # Reset and verify successful login
        admin._clear_lockout()
        admin._ATTEMPTS.clear()
        res_ok = client.post("/admin/login", data={"password": "super-secret-desk-key"})
        assert res_ok.status_code == 302
        assert "/admin/comments" in res_ok.headers["Location"]


def test_admin_custom_prefix(monkeypatch):
    import importlib
    monkeypatch.setenv("ADMIN_PREFIX", "/internal-desk-77")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret123")
    monkeypatch.setenv("SECRET_KEY", "test-key")

    import app.admin as admin_module
    importlib.reload(admin_module)

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        # Old /admin path is now 404
        assert client.get("/admin/login").status_code == 404
        # New custom path works
        res = client.get("/internal-desk-77/login")
        assert res.status_code == 200

    # Reset admin module back to default /admin prefix for other tests
    monkeypatch.delenv("ADMIN_PREFIX", raising=False)
    importlib.reload(admin_module)

