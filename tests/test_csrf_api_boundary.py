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

    @app.post('/api/stripe/webhook')
    def stripe_webhook():
        return 'stripe', 200

    @app.post('/api/stripe-webhook')
    def stale_stripe_alias():
        return 'stale', 200

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


def test_exact_stripe_callback_is_exempt_but_stale_alias_is_not():
    client = build_app().test_client()
    provider_headers = {'Origin': 'https://provider.example'}

    exact = client.post('/api/stripe/webhook', headers=provider_headers,
                        base_url='https://crm.example')
    stale = client.post('/api/stripe-webhook', headers=provider_headers,
                        base_url='https://crm.example')

    assert exact.status_code == 200
    assert stale.status_code == 403
    assert '/api/stripe/webhook' in security.CSRF_EXEMPT_PATHS
    assert '/api/stripe-webhook' not in security.CSRF_EXEMPT_PATHS


def test_stripe_csrf_exemption_does_not_bypass_provider_signature(monkeypatch):
    """Cross-origin Stripe delivery reaches the handler, then fails on signature."""
    import billing
    import stripe
    from blueprints.billing_routes import billing_bp

    app = Flask(__name__)
    app.secret_key = 'test-secret'
    app.config['TESTING'] = True
    app.before_request(security.check_request_origin)
    app.register_blueprint(billing_bp)

    monkeypatch.setattr(billing, 'webhook_secret', lambda: 'whsec_test')
    monkeypatch.setattr(billing, 'configured', lambda: True)
    monkeypatch.setattr(billing, 'stripe_key', lambda: 'sk_test')

    calls = []

    def reject_signature(payload, signature, secret):
        calls.append((payload, signature, secret))
        raise ValueError('bad signature')

    monkeypatch.setattr(stripe.Webhook, 'construct_event', reject_signature)
    client = app.test_client()

    invalid = client.post(
        '/api/stripe/webhook',
        data=b'{}',
        headers={
            'Origin': 'https://provider.example',
            'Stripe-Signature': 'forged',
            'Content-Type': 'application/json',
        },
        base_url='https://crm.example',
    )
    missing = client.post(
        '/api/stripe/webhook',
        data=b'{}',
        headers={
            'Origin': 'https://provider.example',
            'Content-Type': 'application/json',
        },
        base_url='https://crm.example',
    )

    assert invalid.status_code == 400
    assert missing.status_code == 400
    assert calls[0][1:] == ('forged', 'whsec_test')
    assert calls[1][1:] == (None, 'whsec_test')


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
