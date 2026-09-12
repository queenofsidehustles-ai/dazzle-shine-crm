import pytest
from flask import Flask, session

from auth import is_owner_session, owner_required


@pytest.fixture
def app():
    app = Flask(__name__)
    app.secret_key = "test-secret"

    @app.route("/login")
    def login():
        return "login"

    @app.route("/dashboard")
    def dashboard():
        return "dashboard"

    @app.route("/owner-only")
    @owner_required
    def owner_only():
        return "owner"

    app.add_url_rule(
        "/admin/login",
        endpoint="admin.login",
        view_func=lambda: "login",
    )
    app.add_url_rule(
        "/admin/dashboard",
        endpoint="admin.dashboard",
        view_func=lambda: "dashboard",
    )
    return app


def test_explicit_owner_session_is_owner(app):
    with app.test_request_context("/"):
        session["logged_in"] = True
        session["role"] = "owner"
        assert is_owner_session() is True


@pytest.mark.parametrize("role", [None, "admin", "cleaner", "dispatcher", "limited", ""])
def test_non_owner_and_missing_role_fail_closed(app, role):
    with app.test_request_context("/"):
        session["logged_in"] = True
        if role is not None:
            session["role"] = role
        assert is_owner_session() is False


def test_legacy_session_without_role_cannot_open_owner_route(app):
    client = app.test_client()

    with client.session_transaction() as sess:
        sess["logged_in"] = True
        # Deliberately no role: simulates a stale pre-RBAC session.

    response = client.get("/owner-only", follow_redirects=False)

    assert response.status_code in (301, 302, 303, 307, 308)
    assert response.headers["Location"].endswith("/admin/dashboard")


def test_explicit_owner_can_open_owner_route(app):
    client = app.test_client()

    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["role"] = "owner"

    response = client.get("/owner-only")

    assert response.status_code == 200
    assert response.data == b"owner"
