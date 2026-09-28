"""TEN-05: cron endpoints must execute only on a resolved tenant host.

The central scheduler owns the bearer credential, but the hostname owns the
tenant boundary. In Akye a valid X-Api-Key on the product apex or on a malformed
hostname must not be enough to run a tenant automation against the public schema.

Tenant lifecycle authorization is covered independently. These host-boundary
unit tests deliberately stub that control-plane decision so a minimal Flask app
can exercise only tenant-host resolution without needing a database.
"""
import os

import pytest
from flask import Flask, g, request

import security
import tenancy

CRON_PATHS = sorted(security.CRON_PATHS)


def _app(monkeypatch, base_domain='akye.test'):
    # Isolate the TEN-05 host boundary from TEN-06 lifecycle checks. Production
    # tenancy.resolve() still enforces lifecycle before schema access.
    monkeypatch.setattr(tenancy, '_enforce_request_lifecycle', lambda slug: None)

    if base_domain is None:
        os.environ.pop('BASE_DOMAIN', None)
    else:
        os.environ['BASE_DOMAIN'] = base_domain
    os.environ['FLASK_ENV'] = 'development'

    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'x' * 40
    app.config['TESTING'] = True

    @app.before_request
    def _resolve():
        base = os.environ.get('BASE_DOMAIN')
        slug, _schema = tenancy.resolve(request.host, base)
        g.tenant_slug = slug

    security.install(app)

    def ok():
        return 'ok', 200

    for index, path in enumerate(CRON_PATHS):
        app.add_url_rule(path, endpoint=f'cron_{index}', view_func=ok,
                         methods=['POST'])
    return app


@pytest.fixture(autouse=True)
def _restore_env():
    original = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


@pytest.mark.parametrize('path', CRON_PATHS)
def test_apex_cannot_run_tenant_cron(monkeypatch, path):
    client = _app(monkeypatch).test_client()
    response = client.post(path, base_url='https://akye.test',
                           headers={'X-Api-Key': 'correct-secret'})
    assert response.status_code == 404


@pytest.mark.parametrize('path', CRON_PATHS)
def test_malformed_deep_host_cannot_run_tenant_cron(monkeypatch, path):
    client = _app(monkeypatch).test_client()
    response = client.post(path, base_url='https://alpha.attacker.akye.test',
                           headers={'X-Api-Key': 'correct-secret'})
    assert response.status_code == 404


@pytest.mark.parametrize('path', CRON_PATHS)
def test_resolved_tenant_host_passes_host_boundary(monkeypatch, path):
    client = _app(monkeypatch).test_client()
    response = client.post(path, base_url='https://alpha.akye.test',
                           headers={'X-Api-Key': 'correct-secret'})
    assert response.status_code == 200


def test_single_business_install_keeps_legacy_cron_behavior(monkeypatch):
    client = _app(monkeypatch, base_domain=None).test_client()
    response = client.post('/api/reminders', base_url='https://legacy.example.com',
                           headers={'X-Api-Key': 'correct-secret'})
    assert response.status_code == 200


def test_query_secret_rejection_still_precedes_host_boundary(monkeypatch):
    client = _app(monkeypatch).test_client()
    response = client.post('/api/reminders?api_key=legacy-secret',
                           base_url='https://akye.test')
    assert response.status_code == 403
