"""PAY-02: public booking creation must not trust a client-supplied Stripe id.

A browser can send any payment_intent_id. The booking endpoint may only mark a
deposit paid/confirmed after Stripe itself reports a succeeded USD PaymentIntent
for the exact expected deposit amount and this booking/customer context.
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


def _pi(status='succeeded', amount=5000, currency='usd', customer='cus_expected'):
    return SimpleNamespace(
        id='pi_claimed', status=status, amount=amount, amount_received=amount,
        currency=currency, customer=customer, payment_method='pm_test', metadata={}
    )


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
        r = app.test_client().post('/api/booking', json={**BASE_PAYLOAD,
                                                        'payment_intent_id': 'pi_forged',
                                                        'stripe_customer_id': 'cus_expected'})
        assert r.status_code == 400
        assert Booking.query.count() == 0

        class FailedIntent:
            @staticmethod
            def retrieve(_pi_id):
                return _pi(status='requires_payment_method')

        monkeypatch.setattr(api.stripe, 'PaymentIntent', FailedIntent)
        r = app.test_client().post('/api/booking', json={**BASE_PAYLOAD,
                                                        'payment_intent_id': 'pi_claimed',
                                                        'stripe_customer_id': 'cus_expected'})
        assert r.status_code == 400
        assert Booking.query.count() == 0

        for bad in (
            _pi(amount=4999),
            _pi(currency='eur'),
            _pi(customer='cus_someone_else'),
        ):
            class BadIntent:
                @staticmethod
                def retrieve(_pi_id, current=bad):
                    return current
            monkeypatch.setattr(api.stripe, 'PaymentIntent', BadIntent)
            r = app.test_client().post('/api/booking', json={**BASE_PAYLOAD,
                                                            'payment_intent_id': 'pi_claimed',
                                                            'stripe_customer_id': 'cus_expected'})
            assert r.status_code == 400
            assert Booking.query.count() == 0


def test_booking_accepts_only_verified_succeeded_exact_deposit(monkeypatch):
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
        r = app.test_client().post('/api/booking', json={**BASE_PAYLOAD,
                                                        'payment_intent_id': 'pi_claimed',
                                                        'stripe_customer_id': 'cus_expected',
                                                        'stripe_payment_method_id': 'pm_test'})
        assert r.status_code == 201
        booking = Booking.query.one()
        assert booking.deposit_paid is True
        assert booking.status == 'confirmed'
        assert booking.stripe_payment_intent == 'pi_claimed'
