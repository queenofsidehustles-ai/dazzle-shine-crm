from flask import Flask

import security


def build_app():
    app = Flask(__name__)
    app.secret_key = 'test-secret'
    app.before_request(security.check_request_origin)

    @app.post('/api/future-admin-mutation')
    def future_admin_mutation():
        return 'mutated', 200

    @app.post('/api/reminders')
    def reminders():
        return 'cron', 200

    @app.post('/api/quote')
    def quote():
        return 'public', 200

    @app.post('/messages/incoming')
    def incoming():
        return 'twilio', 200

    return app


def test_future_api_mutation_is_not_implicitly_exempt():
    client = build_app().test_client()
    response = client.post(
        '/api/future-admin-mutation',
        headers={'Origin': 'https://evil.example'},
        base_url='https://crm.example',
    )
    assert response.status_code == 403


def test_future_api_mutation_allows_same_site_origin():
    client = build_app().test_client()
    response = client.post(
        '/api/future-admin-mutation',
        headers={'Origin': 'https://crm.example'},
        base_url='https://crm.example',
    )
    assert response.status_code == 200


def test_known_cron_route_remains_explicitly_exempt():
    client = build_app().test_client()
    response = client.post(
        '/api/reminders',
        headers={'Origin': 'https://scheduler.example'},
        base_url='https://crm.example',
    )
    assert response.status_code == 200


def test_public_quote_route_remains_explicitly_exempt():
    client = build_app().test_client()
    response = client.post(
        '/api/quote',
        headers={'Origin': 'https://website.example'},
        base_url='https://crm.example',
    )
    assert response.status_code == 200


def test_twilio_route_remains_explicitly_exempt():
    client = build_app().test_client()
    response = client.post(
        '/messages/incoming',
        headers={'Origin': 'https://provider.example'},
        base_url='https://crm.example',
    )
    assert response.status_code == 200


def test_exemption_table_has_no_api_namespace_wildcard():
    assert '/api/' not in security.CSRF_EXEMPT_PATHS
    assert all(not path.endswith('*') for path in security.CSRF_EXEMPT_PATHS)
