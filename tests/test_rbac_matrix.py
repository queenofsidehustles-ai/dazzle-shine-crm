import pytest
from flask import Flask, session

import rbac
from auth import login_required


@pytest.mark.parametrize(
    ('role', 'permission', 'allowed'),
    [
        ('owner', 'pay.manage', True),
        ('admin', 'pay.manage', False),
        ('dispatcher', 'pay.manage', False),
        ('cleaner', 'pay.manage', False),
        ('limited', 'pay.manage', False),
        ('team', 'pay.manage', False),
        (None, 'pay.manage', False),
        ('unknown', 'pay.manage', False),
        ('owner', 'missing.permission', False),
        ('admin', 'booking.manage', True),
        ('dispatcher', 'booking.manage', True),
        ('cleaner', 'booking.manage', False),
        ('limited', 'booking.manage', False),
        ('team', 'booking.manage', False),
        ('cleaner', 'assigned_work.use', True),
    ],
)
def test_role_permission_matrix_fails_closed(role, permission, allowed):
    assert rbac.has_permission(role, permission) is allowed


def test_legacy_team_role_is_canonicalized_to_limited():
    assert rbac.canonical_role('team') == 'limited'
    assert rbac.canonical_role('owner') == 'owner'
    assert rbac.canonical_role('bogus') is None
    assert rbac.canonical_role(None) is None


def _app():
    app = Flask(__name__)
    app.secret_key = 'rbac-test-secret'

    app.add_url_rule('/admin/login', endpoint='admin.login', view_func=lambda: 'login')

    @app.route('/bookings/<int:booking_id>', methods=['POST'], endpoint='bookings.detail')
    @login_required
    def booking_detail(booking_id):
        return f'changed:{booking_id}'

    return app


@pytest.mark.parametrize('role', ['admin', 'dispatcher', 'cleaner', 'limited', 'team', 'unknown', None])
def test_sensitive_booking_post_is_owner_only(role):
    app = _app()
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        if role is not None:
            sess['role'] = role

    response = client.post('/bookings/7')

    assert response.status_code == 403
    assert b'not permitted' in response.data


def test_owner_can_reach_sensitive_booking_post():
    app = _app()
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['role'] = 'owner'

    response = client.post('/bookings/7')

    assert response.status_code == 200
    assert response.data == b'changed:7'


def test_unclassified_login_required_route_keeps_existing_behavior():
    app = Flask(__name__)
    app.secret_key = 'rbac-test-secret'
    app.add_url_rule('/admin/login', endpoint='admin.login', view_func=lambda: 'login')

    @app.route('/ordinary')
    @login_required
    def ordinary():
        return 'ok'

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['role'] = 'limited'

    response = client.get('/ordinary')

    assert response.status_code == 200
    assert response.data == b'ok'
