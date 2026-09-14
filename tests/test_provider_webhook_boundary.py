"""TEN-07: provider webhooks must be authenticated and tenant-host scoped.

Stripe verifies its provider signature in the billing route handler. Twilio's
inbound-SMS route is authenticated here by security.validate_twilio_webhook.
In hosted Akye both provider callbacks must also resolve to a tenant host before
they can touch a schema.

Tenant lifecycle authorization is covered independently. These webhook-boundary
unit tests deliberately stub that control-plane decision so a minimal Flask app
can exercise only host and provider-signature behavior without needing a database.
"""
import os

import pytest
from flask import Flask, g, request
from twilio.request_validator import RequestValidator

import security
import tenancy


@pytest.fixture(autouse=True)
def _restore_env():
    original = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def _app(monkeypatch, base_domain='akye.test'):
    # Isolate the TEN-07 provider/host boundary from TEN-06 lifecycle checks.
    # Production tenancy.resolve() still enforces lifecycle before schema access.
    monkeypatch.setattr(tenancy, '_enforce_request_lifecycle', lambda slug: None)

    if base_domain is None:
        os.environ.pop('BASE_DOMAIN', None)
    else:
        os.environ['BASE_DOMAIN'] = base_domain
    os.environ['FLASK_ENV'] = 'development'
    os.environ['TWILIO_AUTH_TOKEN'] = 'tenant-twilio-auth-token'

    app = Flask(__name__)
    app.config.update(SECRET_KEY='x' * 40, TESTING=True)

    @app.before_request
    def _resolve():
        slug, _schema = tenancy.resolve(request.host, os.environ.get('BASE_DOMAIN'))
        g.tenant_slug = slug

    security.install(app)

    app.add_url_rule('/api/stripe/webhook', endpoint='stripe_hook',
                     view_func=lambda: ('ok', 200), methods=['POST'])
    app.add_url_rule('/messages/incoming', endpoint='twilio_hook',
                     view_func=lambda: ('ok', 200), methods=['POST'])
    return app


def _twilio_headers(url, form, token='tenant-twilio-auth-token'):
    signature = RequestValidator(token).compute_signature(url, form)
    return {'X-Twilio-Signature': signature}


def test_stripe_webhook_requires_resolved_tenant_host_in_akye(monkeypatch):
    client = _app(monkeypatch).test_client()
    assert client.post('/api/stripe/webhook', base_url='https://akye.test').status_code == 404
    assert client.post('/api/stripe/webhook',
                       base_url='https://alpha.attacker.akye.test').status_code == 404
    assert client.post('/api/stripe/webhook',
                       base_url='https://alpha.akye.test').status_code == 200


def test_stale_stripe_webhook_alias_is_not_a_provider_boundary():
    assert '/api/stripe-webhook' not in security.PROVIDER_WEBHOOK_PATHS
    assert '/api/stripe/webhook' in security.PROVIDER_WEBHOOK_PATHS


def test_twilio_webhook_requires_resolved_tenant_host_before_signature_check(monkeypatch):
    client = _app(monkeypatch).test_client()
    form = {'From': '+13015550123', 'Body': 'hello', 'MessageSid': 'SM123'}
    apex_url = 'https://akye.test/messages/incoming'
    deep_url = 'https://alpha.attacker.akye.test/messages/incoming'

    assert client.post('/messages/incoming', base_url='https://akye.test', data=form,
                       headers=_twilio_headers(apex_url, form)).status_code == 404
    assert client.post('/messages/incoming', base_url='https://alpha.attacker.akye.test',
                       data=form, headers=_twilio_headers(deep_url, form)).status_code == 404


def test_twilio_webhook_rejects_missing_or_invalid_signature_on_tenant_host(monkeypatch):
    client = _app(monkeypatch).test_client()
    form = {'From': '+13015550123', 'Body': 'hello', 'MessageSid': 'SM123'}

    missing = client.post('/messages/incoming', base_url='https://alpha.akye.test', data=form)
    invalid = client.post('/messages/incoming', base_url='https://alpha.akye.test', data=form,
                          headers={'X-Twilio-Signature': 'forged'})
    assert missing.status_code == 403
    assert invalid.status_code == 403


def test_twilio_webhook_accepts_exact_valid_signature_on_tenant_host(monkeypatch):
    client = _app(monkeypatch).test_client()
    form = {'From': '+13015550123', 'Body': 'hello', 'MessageSid': 'SM123'}
    url = 'https://alpha.akye.test/messages/incoming'
    response = client.post('/messages/incoming', base_url='https://alpha.akye.test',
                           data=form, headers=_twilio_headers(url, form))
    assert response.status_code == 200


def test_twilio_signature_is_bound_to_callback_host(monkeypatch):
    client = _app(monkeypatch).test_client()
    form = {'From': '+13015550123', 'Body': 'hello', 'MessageSid': 'SM123'}
    alpha_url = 'https://alpha.akye.test/messages/incoming'

    response = client.post('/messages/incoming', base_url='https://bravo.akye.test',
                           data=form, headers=_twilio_headers(alpha_url, form))
    assert response.status_code == 403


def test_single_business_webhook_keeps_legacy_host_but_still_requires_signature(monkeypatch):
    client = _app(monkeypatch, base_domain=None).test_client()
    form = {'From': '+13015550123', 'Body': 'hello', 'MessageSid': 'SM123'}
    url = 'https://legacy.example.com/messages/incoming'

    assert client.post('/messages/incoming', base_url='https://legacy.example.com',
                       data=form).status_code == 403
    assert client.post('/messages/incoming', base_url='https://legacy.example.com', data=form,
                       headers=_twilio_headers(url, form)).status_code == 200
