"""TEN-08: X-Forwarded-Host must never choose another tenant.

Akye selects the tenant from the request hostname. Werkzeug ProxyFix is used by
the app for Railway's proxy, including x_host=1. If an untrusted
X-Forwarded-Host value can replace the real Host header, a request sent to one
company hostname could be resolved against another company's schema.

These tests reproduce that boundary with the same ProxyFix configuration used
by create_app(). The authoritative tenant must remain the original Host header.
"""

from flask import Flask, g
from werkzeug.middleware.proxy_fix import ProxyFix

import tenancy


def _app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'forwarded-host-test-secret'
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    @app.before_request
    def resolve_tenant():
        slug, schema = tenancy.resolve('' if not hasattr(g, 'x') else '', 'akye.test')
        # resolve() is normally called with request.host by create_app(). Do the
        # same here after ProxyFix has transformed the request environment.
        from flask import request
        slug, schema = tenancy.resolve(request.host, 'akye.test')
        g.tenant_slug = slug
        g.tenant_schema = schema

    @app.get('/probe')
    def probe():
        return {'slug': g.tenant_slug, 'schema': g.tenant_schema}

    return app


def test_forwarded_host_cannot_switch_tenant():
    client = _app().test_client()
    response = client.get(
        '/probe',
        base_url='https://alpha.akye.test',
        headers={'X-Forwarded-Host': 'bravo.akye.test'},
    )
    assert response.status_code == 200
    assert response.get_json() == {
        'slug': 'alpha',
        'schema': 'tenant_alpha',
    }


def test_forwarded_host_cannot_demote_tenant_to_public():
    client = _app().test_client()
    response = client.get(
        '/probe',
        base_url='https://alpha.akye.test',
        headers={'X-Forwarded-Host': 'akye.test'},
    )
    assert response.status_code == 200
    assert response.get_json() == {
        'slug': 'alpha',
        'schema': 'tenant_alpha',
    }
