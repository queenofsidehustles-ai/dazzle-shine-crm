"""The public widget cannot assert that a deposit was paid."""
import os
import sys
import tempfile
from types import SimpleNamespace

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/widget-payment.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
os.environ['STRIPE_SECRET_KEY'] = 'sk_test_widget'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
from models import Booking, Client
import blueprints.api as api
import blueprints.portal as portal

app = create_app()

payload = {
    'name': 'Widget Customer', 'email': 'widget@example.test',
    'phone': '2025550100', 'service_type': 'standard',
    'bedrooms': 1, 'bathrooms': 1, 'payment_intent_id': 'pi_widget',
    # These are attacker-controlled and must be ignored.
    'stripe_customer_id': 'cus_attacker',
    'stripe_payment_method_id': 'pm_attacker',
}

with app.app_context():
    db.create_all()
    client = app.test_client()

    original = api.stripe.PaymentIntent
    current = SimpleNamespace(
        status='requires_payment_method', amount=5000, amount_received=0,
        currency='usd', customer='cus_verified', payment_method='pm_verified',
        metadata={'kind': 'booking_deposit', 'customer_email': payload['email'],
                  'service_type': 'standard', 'total_price': '0'},
    )

    class FakePaymentIntent:
        @staticmethod
        def retrieve(_intent_id):
            return current

    api.stripe.PaymentIntent = FakePaymentIntent
    try:
        rejected = client.post('/api/booking', json=payload)
        assert rejected.status_code == 400
        assert Booking.query.count() == 0

        from pricing import calculate_job
        total = calculate_job('standard', 1, 1, extras='', frequency='one_time')['client_price']
        current.status = 'succeeded'
        current.amount_received = 5000
        current.metadata['total_price'] = str(total)
        accepted = client.post('/api/booking', json=payload)
        assert accepted.status_code == 201
        booking = Booking.query.one()
        assert booking.deposit_paid is True
        assert booking.stripe_customer_id == 'cus_verified'
        assert booking.stripe_payment_method_id == 'pm_verified'

        replay = client.post('/api/booking', json=payload)
        assert replay.status_code == 409
        assert Booking.query.count() == 1

        customer = Client.query.one()
        customer.portal_token = 'portal-integrity-token'
        customer.stripe_customer_id = 'cus_verified'
        db.session.commit()
        with client.session_transaction() as sess:
            sess[f'portal_ok_{customer.id}'] = True

        original_pm = portal.stripe.PaymentMethod
        current_pm = SimpleNamespace(
            customer='cus_someone_else',
            card=SimpleNamespace(brand='visa', last4='4242'))

        class FakePaymentMethod:
            @staticmethod
            def retrieve(_payment_method_id):
                return current_pm

        portal.stripe.PaymentMethod = FakePaymentMethod
        try:
            wrong_owner = client.post(
                '/portal/portal-integrity-token/save-card',
                json={'payment_method_id': 'pm_other'})
            assert wrong_owner.status_code == 400
            db.session.refresh(customer)
            assert customer.stripe_payment_method_id is None

            current_pm.customer = 'cus_verified'
            saved = client.post(
                '/portal/portal-integrity-token/save-card',
                json={'payment_method_id': 'pm_verified'})
            assert saved.status_code == 200
            db.session.refresh(customer)
            assert customer.stripe_payment_method_id == 'pm_verified'
        finally:
            portal.stripe.PaymentMethod = original_pm
    finally:
        api.stripe.PaymentIntent = original

print('✅ Widget deposits and portal cards are verified against their Stripe owner.')
