"""TEN-07: a signed Stripe event must never cross tenant schemas.

This is deliberately a real PostgreSQL test. Alpha and Bravo are provisioned as
separate tenant schemas, each gets its own webhook signing secret, and both are
given a booking with the same synthetic PaymentIntent id. That collision makes
the test adversarial: schema isolation, per-tenant signature selection and
booking metadata must all be correct or Bravo can be mutated by Alpha's event.
"""
import hashlib
import hmac
import json
import os
import time

import pytest
from sqlalchemy import create_engine, text

DB_NAME = 'dsm_stripe_webhook_tenant_test'


def _postgres_admin_url():
    for candidate in (
        os.environ.get('TEST_POSTGRES_URL'),
        f'postgresql://{os.environ.get("USER", "postgres")}@localhost/postgres',
    ):
        if not candidate:
            continue
        try:
            engine = create_engine(candidate)
            with engine.connect() as conn:
                conn.execute(text('SELECT 1'))
            engine.dispose()
            return candidate
        except Exception:
            continue
    return None


def _stripe_signature(payload, secret):
    timestamp = int(time.time())
    signed = f'{timestamp}.'.encode() + payload
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f't={timestamp},v1={digest}'


@pytest.fixture(scope='module')
def stripe_app():
    admin_url = _postgres_admin_url()
    if not admin_url:
        pytest.skip('Stripe tenant-isolation test requires PostgreSQL')

    original = dict(os.environ)
    admin = create_engine(admin_url, isolation_level='AUTOCOMMIT')
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE {DB_NAME}'))

    test_url = f'{admin_url.rsplit("/", 1)[0]}/{DB_NAME}'
    os.environ['DATABASE_URL'] = test_url
    os.environ['SECRET_KEY'] = 'stripe-webhook-tenant-secret-key'
    os.environ['BASE_DOMAIN'] = 'akye.test'
    os.environ['SIGNUPS_OPEN'] = '0'
    os.environ['FLASK_ENV'] = 'development'
    os.environ.pop('STRIPE_WEBHOOK_SECRET', None)
    os.environ.pop('STRIPE_SECRET_KEY', None)

    import notifications
    notifications.send_sms = lambda *a, **k: (True, 'stub')
    notifications.send_email = lambda *a, **k: (True, 'stub')

    import provisioning
    for slug, name in (('alpha', 'Alpha Cleaning'), ('bravo', 'Bravo Cleaning')):
        provisioning.provision(slug, name, quiet=True)

    from app import create_app
    app = create_app()
    app.config.update(TESTING=True)

    import integrations
    import tenancy
    from extensions import db
    from models import Booking

    with app.app_context():
        for slug, webhook_secret, token, customer in (
            ('alpha', 'whsec_alpha_only', 'alpha-pay-token', 'ALPHA WEBHOOK CUSTOMER'),
            ('bravo', 'whsec_bravo_only', 'bravo-pay-token', 'BRAVO WEBHOOK CUSTOMER'),
        ):
            with tenancy.use_tenant(slug):
                integrations.set('stripe_webhook_secret', webhook_secret)
                integrations.set('stripe_secret_key', f'sk_test_{slug}')
                db.session.add(Booking(
                    service_type='standard', name=customer,
                    email=f'{slug}@example.test', price=100.0,
                    pay_token=token, deposit_token=f'{slug}-deposit-token',
                    stripe_payment_intent='pi_deliberate_cross_tenant_collision',
                    status='confirmed',
                ))
                db.session.commit()
                db.session.remove()

    import blueprints.payments as payments
    original_receipt = payments._send_receipt
    original_alert = payments._alert_owner_paid
    payments._send_receipt = lambda *a, **k: None
    payments._alert_owner_paid = lambda *a, **k: None

    try:
        yield app
    finally:
        payments._send_receipt = original_receipt
        payments._alert_owner_paid = original_alert
        try:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        except Exception:
            pass
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)'))
        admin.dispose()
        os.environ.clear()
        os.environ.update(original)


def _event_payload(booking_id, token):
    return json.dumps({
        'id': 'evt_alpha_payment',
        'object': 'event',
        'type': 'payment_intent.succeeded',
        'data': {'object': {
            'id': 'pi_deliberate_cross_tenant_collision',
            'object': 'payment_intent',
            'status': 'succeeded',
            'amount': 10000,
            'amount_received': 10000,
            'currency': 'usd',
            'metadata': {
                'booking_id': str(booking_id),
                'pay_token': token,
                'kind': 'full_payment',
                'expected_amount_cents': '10000',
                'tip': '0.00',
            },
        }},
    }, separators=(',', ':')).encode()


def test_alpha_signed_event_updates_alpha_only_and_cannot_replay_to_bravo(stripe_app):
    import tenancy
    from extensions import db
    from models import Booking

    with stripe_app.app_context():
        with tenancy.use_tenant('alpha'):
            alpha = Booking.query.filter_by(
                stripe_payment_intent='pi_deliberate_cross_tenant_collision').one()
            alpha_id = alpha.id
        with tenancy.use_tenant('bravo'):
            bravo = Booking.query.filter_by(
                stripe_payment_intent='pi_deliberate_cross_tenant_collision').one()
            bravo_id = bravo.id
            assert bravo.paid_at is None

    payload = _event_payload(alpha_id, 'alpha-pay-token')
    alpha_sig = _stripe_signature(payload, 'whsec_alpha_only')
    client = stripe_app.test_client()

    accepted = client.post(
        '/api/stripe-webhook', base_url='https://alpha.akye.test',
        data=payload, content_type='application/json',
        headers={'Stripe-Signature': alpha_sig})
    assert accepted.status_code == 200

    with stripe_app.app_context():
        with tenancy.use_tenant('alpha'):
            alpha = Booking.query.get(alpha_id)
            assert alpha.paid_at is not None
            db.session.remove()
        with tenancy.use_tenant('bravo'):
            bravo = Booking.query.get(bravo_id)
            assert bravo.paid_at is None
            db.session.remove()

    # Exact Alpha payload + exact Alpha signature on Bravo must fail provider
    # authentication because Bravo's schema supplies a different webhook secret.
    replay = client.post(
        '/api/stripe-webhook', base_url='https://bravo.akye.test',
        data=payload, content_type='application/json',
        headers={'Stripe-Signature': alpha_sig})
    assert replay.status_code == 400

    with stripe_app.app_context():
        with tenancy.use_tenant('bravo'):
            assert Booking.query.get(bravo_id).paid_at is None
            db.session.remove()

    # Defense in depth: even a correctly signed Bravo delivery carrying Alpha's
    # booking metadata must not mutate Bravo's colliding PaymentIntent row.
    bravo_sig = _stripe_signature(payload, 'whsec_bravo_only')
    wrong_metadata = client.post(
        '/api/stripe-webhook', base_url='https://bravo.akye.test',
        data=payload, content_type='application/json',
        headers={'Stripe-Signature': bravo_sig})
    assert wrong_metadata.status_code == 200

    with stripe_app.app_context():
        with tenancy.use_tenant('bravo'):
            assert Booking.query.get(bravo_id).paid_at is None
            db.session.remove()
