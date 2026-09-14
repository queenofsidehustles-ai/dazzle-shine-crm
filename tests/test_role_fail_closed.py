import pytest
from flask import Flask, session

import rbac
from auth import is_owner_session, login_required, owner_required
from navigation import sidebar, tabs_for


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


def _sidebar_endpoints(role=None):
    return {
        item["endpoint"]
        for section in sidebar(role=role)
        for item in section["items"]
    }


def test_missing_role_does_not_receive_owner_only_navigation():
    endpoints = _sidebar_endpoints()
    assert "admin.dashboard" in endpoints
    assert "bookings.index" in endpoints
    assert "assistant.page" not in endpoints
    assert "money.pnl" not in endpoints
    assert "settings.business" not in endpoints


def test_explicit_owner_receives_owner_only_navigation():
    endpoints = _sidebar_endpoints("owner")
    assert "assistant.page" in endpoints
    assert "money.pnl" in endpoints
    assert "settings.business" in endpoints


def test_missing_role_does_not_receive_owner_only_tabs():
    tabs, active = tabs_for("settings.business")
    assert active == "settings.business"
    assert tabs == []


def test_owner_argument_cannot_elevate_missing_request_session_role(app):
    with app.test_request_context("/"):
        session["logged_in"] = True
        endpoints = _sidebar_endpoints("owner")
        tabs, active = tabs_for("settings.business", "owner")
    assert "assistant.page" not in endpoints
    assert "money.pnl" not in endpoints
    assert "settings.business" not in endpoints
    assert active == "settings.business"
    assert tabs == []


def test_owner_argument_requires_matching_owner_request_session(app):
    with app.test_request_context("/"):
        session["logged_in"] = True
        session["role"] = "owner"
        endpoints = _sidebar_endpoints("owner")
    assert "assistant.page" in endpoints
    assert "money.pnl" in endpoints
    assert "settings.business" in endpoints


@pytest.mark.parametrize(
    ("role", "permission", "allowed"),
    [
        ("owner", "pay.manage", True),
        ("admin", "pay.manage", False),
        ("dispatcher", "pay.manage", False),
        ("cleaner", "pay.manage", False),
        ("limited", "pay.manage", False),
        ("team", "pay.manage", False),
        (None, "pay.manage", False),
        ("unknown", "pay.manage", False),
        ("owner", "missing.permission", False),
        ("admin", "booking.manage", True),
        ("dispatcher", "booking.manage", False),
        ("cleaner", "booking.manage", False),
        ("limited", "booking.manage", False),
        ("team", "booking.manage", False),
        ("cleaner", "assigned_work.use", True),
    ],
)
def test_iam_permission_matrix_fails_closed(role, permission, allowed):
    assert rbac.has_permission(role, permission) is allowed


@pytest.mark.parametrize(
    ("role", "read", "create", "dispatch", "communicate", "pay", "finance"),
    [
        ("owner", True, True, True, True, True, True),
        ("admin", True, True, True, True, False, False),
        ("dispatcher", True, True, True, True, False, False),
        ("cleaner", False, False, False, False, False, False),
        ("limited", True, False, False, False, False, False),
        ("team", True, False, False, False, False, False),
        ("unknown", False, False, False, False, False, False),
        (None, False, False, False, False, False, False),
    ],
)
def test_booking_role_matrix(role, read, create, dispatch, communicate, pay, finance):
    assert rbac.has_permission(role, "booking.read") is read
    assert rbac.has_permission(role, "booking.create") is create
    assert rbac.has_permission(role, "dispatch.manage") is dispatch
    assert rbac.has_permission(role, "customer.communicate") is communicate
    assert rbac.has_permission(role, "pay.manage") is pay
    assert rbac.has_permission(role, "finance.manage") is finance


@pytest.mark.parametrize(
    ("endpoint", "method", "permission"),
    [
        ("bookings.index", "GET", "booking.read"),
        ("bookings.calendar", "GET", "booking.read"),
        ("bookings.detail", "GET", "booking.read"),
        ("bookings.new", "GET", "booking.create"),
        ("bookings.new", "POST", "booking.create"),
        ("bookings.reschedule", "POST", "dispatch.manage"),
        ("bookings.broadcast", "POST", "dispatch.manage"),
        ("bookings.send_crew", "POST", "dispatch.manage"),
        ("bookings.send_confirmation", "POST", "customer.communicate"),
        ("bookings.detail", "POST", "pay.manage"),
        ("bookings.correct_price", "POST", "pay.manage"),
        ("bookings.notify_pay", "POST", "pay.manage"),
        ("bookings.send_payment_link_route", "POST", "finance.manage"),
        ("bookings.log_ad_cost", "POST", "finance.manage"),
    ],
)
def test_sensitive_booking_endpoints_have_explicit_permissions(endpoint, method, permission):
    assert rbac.required_permission(endpoint, method) == permission


def test_legacy_team_role_is_least_privileged():
    assert rbac.canonical_role("team") == "limited"
    assert rbac.canonical_role("bogus") is None
    assert rbac.canonical_role(None) is None


def _rbac_app(endpoint="bookings.detail", methods=("POST",)):
    test_app = Flask(__name__)
    test_app.secret_key = "rbac-test-secret"
    test_app.add_url_rule(
        "/admin/login", endpoint="admin.login", view_func=lambda: "login"
    )

    def protected():
        return "allowed"

    test_app.add_url_rule(
        "/protected",
        endpoint=endpoint,
        view_func=login_required(protected),
        methods=list(methods),
    )
    return test_app


@pytest.mark.parametrize(
    "role", ["admin", "dispatcher", "cleaner", "limited", "team", "unknown", None]
)
def test_sensitive_booking_mutation_is_owner_only(role):
    test_app = _rbac_app()
    client = test_app.test_client()
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        if role is not None:
            sess["role"] = role
    response = client.post("/protected")
    assert response.status_code == 403
    assert b"not permitted" in response.data


def test_owner_can_reach_sensitive_booking_mutation():
    test_app = _rbac_app()
    client = test_app.test_client()
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["role"] = "owner"
    response = client.post("/protected")
    assert response.status_code == 200
    assert response.data == b"allowed"


@pytest.mark.parametrize("role", ["owner", "admin", "dispatcher"])
def test_dispatch_roles_can_reschedule(role):
    test_app = _rbac_app("bookings.reschedule", ("POST",))
    client = test_app.test_client()
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["role"] = role
    assert client.post("/protected").status_code == 200


@pytest.mark.parametrize("role", ["cleaner", "limited", "team", "unknown"])
def test_non_dispatch_roles_cannot_reschedule(role):
    test_app = _rbac_app("bookings.reschedule", ("POST",))
    client = test_app.test_client()
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["role"] = role
    assert client.post("/protected").status_code == 403


@pytest.mark.parametrize("role", ["owner", "admin", "dispatcher"])
def test_booking_create_roles_can_open_new_booking(role):
    test_app = _rbac_app("bookings.new", ("GET",))
    client = test_app.test_client()
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["role"] = role
    assert client.get("/protected").status_code == 200


@pytest.mark.parametrize("role", ["limited", "team"])
def test_limited_roles_can_read_but_cannot_create_booking(role):
    read_app = _rbac_app("bookings.index", ("GET",))
    read_client = read_app.test_client()
    with read_client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["role"] = role
    assert read_client.get("/protected").status_code == 200

    create_app = _rbac_app("bookings.new", ("POST",))
    create_client = create_app.test_client()
    with create_client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["role"] = role
    assert create_client.post("/protected").status_code == 403


def test_cleaner_cannot_open_back_office_booking_index():
    test_app = _rbac_app("bookings.index", ("GET",))
    client = test_app.test_client()
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["role"] = "cleaner"
    assert client.get("/protected").status_code == 403
