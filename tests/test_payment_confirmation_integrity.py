"""A browser POST cannot turn an unrelated or absent charge into paid work."""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/payment-integrity.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import Booking
import blueprints.payments as payments
from types import SimpleNamespace


app = create_app()

with app.app_context():
    db.create_all()
    booking = Booking(service_type='standard', name='Integrity Customer',
                      email='customer@example.test', address='1 Test Street',
                      price=200, pay_token='pay-right', deposit_token='dep-right',
                      stripe_payment_intent='pi_right', status='confirmed')
    db.session.add(booking)
    db.session.commit()

    client = app.test_client()
    response = client.post('/pay/pay-right/confirm', json={})
    assert response.status_code == 400
    db.session.refresh(booking)
    assert booking.paid_at is None

    response = client.post('/pay/pay-right/confirm',
                           json={'payment_intent_id': 'pi_someone_else'})
    assert response.status_code == 400
    db.session.refresh(booking)
    assert booking.paid_at is None

    response = client.post('/pay-deposit/dep-right/confirm', json={})
    assert response.status_code == 400
    db.session.refresh(booking)
    assert booking.deposit_paid is not True

    original_secret = payments.integrations.stripe_secret_key
    original_pi = payments.stripe.PaymentIntent
    current = None

    class FakePaymentIntent:
        @staticmethod
        def retrieve(_intent_id):
            return current

    payments.integrations.stripe_secret_key = lambda: 'sk_test_integrity'
    payments.stripe.PaymentIntent = FakePaymentIntent
    try:
        current = SimpleNamespace(
            status='succeeded', payment_method='pm_1', amount_received=20000,
            amount=20000, currency='usd',
            metadata={'booking_id': str(booking.id), 'pay_token': 'wrong-token',
                      'kind': 'full_payment', 'expected_amount_cents': '20000'},
        )
        _, error = payments.verify_intent_for_booking(booking, 'pi_right', 'full_payment')
        assert 'link reference' in error

        current.metadata['pay_token'] = 'pay-right'
        current.amount_received = 19999
        _, error = payments.verify_intent_for_booking(booking, 'pi_right', 'full_payment')
        assert 'amount' in error

        current.amount_received = 20000
        verified, error = payments.verify_intent_for_booking(
            booking, 'pi_right', 'full_payment')
        assert error is None and verified is current
    finally:
        payments.integrations.stripe_secret_key = original_secret
        payments.stripe.PaymentIntent = original_pi

print('✅ Only the exact booking, token, type, currency, and amount can be paid.')
