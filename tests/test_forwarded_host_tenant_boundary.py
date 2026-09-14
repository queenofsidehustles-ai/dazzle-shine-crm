"""TEN-08: X-Forwarded-Host must never choose another tenant.

Akye selects the tenant from the request hostname. The production app currently
uses Werkzeug ProxyFix with x_host=1 so reverse-proxy host information can be
applied. Tenant selection must nevertheless remain bound to the original Host
header that entered the WSGI app; X-Forwarded-Host must not switch a company or
demote a company request to the public schema.
"""

from flask import Flask, g, request
from werkzeug.middleware.proxy_fix import ProxyFix

import tenancy


def _app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'forwarded-host-test-secret'
    # Match create_app() exactly. The protection belongs in tenant resolution,
    # not in a weaker test-only ProxyFix configuration.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    @app.before_request
    def resolve_tenant():
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
