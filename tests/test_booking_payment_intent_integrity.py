"""PAY-02: public paid bookings must be bound to one tenant and purpose.

A browser can send Stripe identifiers, but it cannot decide whether an intent is
a valid Akye booking deposit. The app verifies Stripe's amount/customer/status
and Akye's signed tenant + purpose + checkout-instance metadata before a booking
can be marked paid.
"""
import os
import tempfile
from types import SimpleNamespace

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/booking-payment-integrity.db'
os.environ['SECRET_KEY'] = 'booking-payment-integrity-test'
os.environ['FLASK_ENV'] = 'development'
os.environ.pop('BASE_DOMAIN', None)

from app import create_app
from extensions import db
from models import Booking
import blueprints.api as api
import security


app = create_app()
app.config.update(TESTING=True)


BASE_PAYLOAD = {
    'name': 'Payment Integrity Customer',
    'email': 'integrity@example.test',
    'phone': '3015550123',
    'service_type': 'standard',
    'bedrooms': 2,
    'bathrooms': 1,
    'frequency': 'one_time',
    'preferred_date': '2026-09-20',
    'preferred_time': '09:00',
    'address': '1 Integrity Way',
    'city': 'Baltimore',
    'zip_code': '21201',
}


def _bound_metadata(pi_id='pi_claimed', tenant=security.SINGLE_BUSINESS_PAYMENT_TENANT,
                    purpose=security.BOOKING_PAYMENT_PURPOSE, tamper=False):
    with app.app_context():
        binding = security._new_checkout_binding(pi_id, tenant, nonce='n' * 24)
    if tamper:
        binding = binding[:-1] + ('0' if binding[-1] != '0' else '1')
    return {
        security.BOOKING_PAYMENT_META_TENANT: tenant,
        security.BOOKING_PAYMENT_META_PURPOSE: purpose,
        security.BOOKING_PAYMENT_META_CHECKOUT: binding,
    }


def _pi(status='succeeded', amount=5000, currency='usd', customer='cus_expected',
        metadata=None):
    if metadata is None:
        metadata = _bound_metadata()
    return SimpleNamespace(
        id='pi_claimed', status=status, amount=amount, amount_received=amount,
        currency=currency, customer=customer, payment_method='pm_test', metadata=metadata
    )


def _post_paid(client, **overrides):
    payload = {**BASE_PAYLOAD,
               'payment_intent_id': 'pi_claimed',
               'stripe_customer_id': 'cus_expected',
               'stripe_payment_method_id': 'pm_test'}
    payload.update(overrides)
    return client.post('/api/booking', json=payload)


def test_booking_rejects_unverified_or_mismatched_payment_intent(monkeypatch):
    with app.app_context():
        db.drop_all()
        db.create_all()

        monkeypatch.setattr(api.integrations, 'stripe_secret_key', lambda: 'sk_test_integrity')
        monkeypatch.setattr(api, '_send_deposit_request', lambda *a, **k: None)

        class MissingIntent:
            @staticmethod
            def retrieve(_pi_id):
                raise api.stripe.error.InvalidRequestError('No such payment_intent', 'id')

        monkeypatch.setattr(api.stripe, 'PaymentIntent', MissingIntent)
        r = _post_paid(app.test_client(), payment_intent_id='pi_forged')
        assert r.status_code == 400
        assert Booking.query.count() == 0

        for bad in (
            _pi(status='requires_payment_method'),
            _pi(amount=4999),
            _pi(currency='eur'),
            _pi(customer='cus_someone_else'),
        ):
            class BadIntent:
                @staticmethod
                def retrieve(_pi_id, current=bad):
                    return current
            monkeypatch.setattr(api.stripe, 'PaymentIntent', BadIntent)
            r = _post_paid(app.test_client())
            assert r.status_code == 400
            assert Booking.query.count() == 0


def test_booking_rejects_missing_wrong_tenant_wrong_purpose_and_tampered_binding(monkeypatch):
    with app.app_context():
        db.drop_all()
        db.create_all()
        monkeypatch.setattr(api.integrations, 'stripe_secret_key', lambda: 'sk_test_integrity')

        bad_metadata = [
            {},
            _bound_metadata(tenant='another-tenant'),
            _bound_metadata(purpose='full_payment'),
            _bound_metadata(tamper=True),
        ]
        for metadata in bad_metadata:
            class BadBindingIntent:
                @staticmethod
                def retrieve(_pi_id, current=metadata):
                    return _pi(metadata=current)
            monkeypatch.setattr(api.stripe, 'PaymentIntent', BadBindingIntent)
            r = _post_paid(app.test_client())
            assert r.status_code == 400
            assert Booking.query.count() == 0


def test_booking_accepts_only_verified_tenant_bound_booking_deposit(monkeypatch):
    with app.app_context():
        db.drop_all()
        db.create_all()

        monkeypatch.setattr(api.integrations, 'stripe_secret_key', lambda: 'sk_test_integrity')
        monkeypatch.setattr(api, '_send_confirmation', lambda *a, **k: None)

        class GoodIntent:
            @staticmethod
            def retrieve(_pi_id):
                return _pi()

        monkeypatch.setattr(api.stripe, 'PaymentIntent', GoodIntent)
        r = _post_paid(app.test_client())
        assert r.status_code == 201
        booking = Booking.query.one()
        assert booking.deposit_paid is True
        assert booking.status == 'confirmed'
        assert booking.stripe_payment_intent == 'pi_claimed'


def test_payment_creation_is_bound_before_client_secret_leaves_server(monkeypatch):
    with app.app_context():
        db.drop_all()
        db.create_all()

    monkeypatch.setattr(api.integrations, 'stripe_secret_key', lambda: 'sk_test_integrity')
    monkeypatch.setattr(api, 'calculate_price', lambda **_kwargs: 125.0)
    monkeypatch.setattr(api, 'get_deposit', lambda: 50.0)

    class Customer:
        @staticmethod
        def create(**_kwargs):
            return SimpleNamespace(id='cus_created')

    captured = {}

    class PaymentIntent:
        @staticmethod
        def create(**_kwargs):
            return SimpleNamespace(client_secret='pi_created_secret_abc')

        @staticmethod
        def modify(pi_id, metadata):
            captured['pi_id'] = pi_id
            captured['metadata'] = metadata
            return SimpleNamespace(id=pi_id)

    monkeypatch.setattr(api.stripe, 'Customer', Customer)
    monkeypatch.setattr(api.stripe, 'PaymentIntent', PaymentIntent)

    r = app.test_client().post('/api/create-payment-intent', json={
        'name': 'Bound Checkout', 'email': 'bound@example.test', 'phone': '3015550188',
        'service_type': 'standard', 'bedrooms': 2, 'bathrooms': 1,
        'frequency': 'one_time',
    })

    assert r.status_code == 200
    assert r.get_json()['client_secret'] == 'pi_created_secret_abc'
    assert captured['pi_id'] == 'pi_created'
    metadata = captured['metadata']
    assert metadata[security.BOOKING_PAYMENT_META_TENANT] == security.SINGLE_BUSINESS_PAYMENT_TENANT
    assert metadata[security.BOOKING_PAYMENT_META_PURPOSE] == security.BOOKING_PAYMENT_PURPOSE
    with app.app_context():
        assert security._checkout_binding_valid(
            metadata[security.BOOKING_PAYMENT_META_CHECKOUT],
            'pi_created', security.SINGLE_BUSINESS_PAYMENT_TENANT,
        )


def test_payment_creation_fails_closed_if_binding_cannot_be_persisted(monkeypatch):
    with app.app_context():
        db.drop_all()
        db.create_all()

    monkeypatch.setattr(api.integrations, 'stripe_secret_key', lambda: 'sk_test_integrity')
    monkeypatch.setattr(api, 'calculate_price', lambda **_kwargs: 125.0)
    monkeypatch.setattr(api, 'get_deposit', lambda: 50.0)

    class Customer:
        @staticmethod
        def create(**_kwargs):
            return SimpleNamespace(id='cus_created')

    class PaymentIntent:
        @staticmethod
        def create(**_kwargs):
            return SimpleNamespace(client_secret='pi_unbound_secret_abc')

        @staticmethod
        def modify(*_args, **_kwargs):
            raise RuntimeError('metadata write failed')

    monkeypatch.setattr(api.stripe, 'Customer', Customer)
    monkeypatch.setattr(api.stripe, 'PaymentIntent', PaymentIntent)

    r = app.test_client().post('/api/create-payment-intent', json={
        'name': 'Unbound Checkout', 'email': 'unbound@example.test', 'phone': '3015550199',
        'service_type': 'standard', 'bedrooms': 2, 'bathrooms': 1,
        'frequency': 'one_time',
    })

    assert r.status_code == 502
    assert r.get_json()['ok'] is False
    assert 'client_secret' not in r.get_json()
