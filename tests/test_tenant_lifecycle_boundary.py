"""TEN-06: tenant lifecycle state must gate schema access fail-closed."""
from types import SimpleNamespace

import pytest
from flask import Flask, jsonify, session

import control_plane
import extensions
import tenancy


def _app(monkeypatch, state):
    engine = object()
    monkeypatch.setattr(extensions, 'db', SimpleNamespace(engine=engine))

    def fake_find(actual_engine, slug):
        assert actual_engine is engine
        assert slug == 'alpha'
        error = state.get('error')
        if error is not None:
            raise error
        return state.get('org')

    monkeypatch.setattr(control_plane, 'find', fake_find)

    app = Flask(__name__)
    app.config.update(SECRET_KEY='tenant-lifecycle-test-secret', TESTING=True)

    @app.before_request
    def resolve_tenant():
        slug, schema = tenancy.resolve('alpha.akye.test', 'akye.test')
        state['resolved'] = (slug, schema)

    @app.get('/')
    def index():
        return jsonify(
            tenant=state.get('resolved'),
            user_id=session.get('user_id'),
            role=session.get('role'),
        )

    return app


def _authenticated(client):
    with client.session_transaction() as sess:
        sess['user_id'] = 41
        sess['role'] = 'owner'
        sess['tenant_slug'] = 'alpha'


def _active_org(**overrides):
    org = {
        'slug': 'alpha',
        'schema_name': 'tenant_alpha',
        'status': 'active',
    }
    org.update(overrides)
    return org


def test_active_tenant_resolves_to_control_plane_schema_and_keeps_session(monkeypatch):
    state = {'org': _active_org()}
    client = _app(monkeypatch, state).test_client()
    _authenticated(client)

    response = client.get('/', base_url='https://alpha.akye.test')

    assert response.status_code == 200
    assert response.get_json()['tenant'] == ['alpha', 'tenant_alpha']
    assert response.get_json()['user_id'] == 41
    assert response.get_json()['role'] == 'owner'


def test_suspension_denies_access_and_clears_presented_session(monkeypatch):
    state = {'org': _active_org(status='suspended')}
    client = _app(monkeypatch, state).test_client()
    _authenticated(client)

    response = client.get('/', base_url='https://alpha.akye.test')

    assert response.status_code == 423
    with client.session_transaction() as sess:
        assert 'user_id' not in sess
        assert 'role' not in sess
        assert 'tenant_slug' not in sess


def test_reactivation_restores_workspace_but_not_stale_pre_suspension_login(monkeypatch):
    state = {'org': _active_org(status='suspended')}
    client = _app(monkeypatch, state).test_client()
    _authenticated(client)

    suspended = client.get('/', base_url='https://alpha.akye.test')
    assert suspended.status_code == 423

    state['org'] = _active_org(status='active')
    reenabled = client.get('/', base_url='https://alpha.akye.test')

    assert reenabled.status_code == 200
    assert reenabled.get_json()['tenant'] == ['alpha', 'tenant_alpha']
    assert reenabled.get_json()['user_id'] is None
    assert reenabled.get_json()['role'] is None


@pytest.mark.parametrize('org', [
    None,
    _active_org(status='closed'),
    _active_org(status='deprovisioned'),
    _active_org(status='unexpected-state'),
])
def test_missing_closed_or_unknown_tenant_is_not_resolvable(monkeypatch, org):
    state = {'org': org}
    client = _app(monkeypatch, state).test_client()
    _authenticated(client)

    response = client.get('/', base_url='https://alpha.akye.test')

    assert response.status_code == 404
    with client.session_transaction() as sess:
        assert 'user_id' not in sess


def test_control_plane_read_failure_is_503_not_implicit_access(monkeypatch):
    state = {'org': None, 'error': RuntimeError('database unavailable')}
    client = _app(monkeypatch, state).test_client()
    _authenticated(client)

    response = client.get('/', base_url='https://alpha.akye.test')

    assert response.status_code == 503


def test_active_tenant_with_mismatched_schema_assignment_fails_closed(monkeypatch):
    state = {'org': _active_org(schema_name='tenant_bravo')}
    client = _app(monkeypatch, state).test_client()
    _authenticated(client)

    response = client.get('/', base_url='https://alpha.akye.test')

    assert response.status_code == 503
    with client.session_transaction() as sess:
        assert 'user_id' not in sess
        assert 'role' not in sess
        assert 'tenant_slug' not in sess


def test_active_tenant_with_missing_schema_assignment_fails_closed(monkeypatch):
    state = {'org': _active_org(schema_name=None)}
    client = _app(monkeypatch, state).test_client()

    response = client.get('/', base_url='https://alpha.akye.test')

    assert response.status_code == 503
