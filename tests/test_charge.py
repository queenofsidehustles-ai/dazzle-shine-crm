"""The charge button must offer the real balance. It was reading a column that
is almost never written, so it sat at $0 and refused to charge."""
import os, sys, tempfile
from datetime import datetime
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/ch.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['STRIPE_SECRET_KEY'] = 'sk_test_fake'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'ok')
notifications.send_email = lambda *a, **k: (True, 'ok')
from app import create_app
from extensions import db
from models import Booking
app = create_app()
import blueprints.bookings as bk
bk._send_booking_confirmation = lambda b: None

# Capture what Stripe would be asked to charge — nothing real is called.
CHARGES = []
import payment_service
class _Intent:
    status = 'succeeded'
    id = 'pi_test_123'          # the real code records the intent id
class _PI:
    @staticmethod
    def create(**kw):
        CHARGES.append(kw)
        return _Intent()
payment_service.stripe.PaymentIntent = _PI
payment_service.send_email = lambda *a, **k: True

def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')

with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print("\n1. Ashley's booking as it stood — the bug")
    b = Booking(service_type='deep', name='Ashley G', address='280 Ballow Dr',
                email='wckmanager@gmail.com', phone='4079890063',
                price=1420, deposit_paid=True, balance_due=0,      # never written
                stripe_customer_id='cus_x', stripe_payment_method_id='pm_x',
                status='confirmed', preferred_date='2026-08-05')
    db.session.add(b); db.session.commit()
    from blueprints.payments import amount_due
    check(b.balance_due == 0, 'the stored balance says $0 even though $1,420 is owed')
    check(amount_due(b) == 1370.0, 'but the real balance is $1,370 (price less the $50 deposit)')

    print('\n2. The page now offers the real figure')
    page = c.get(f'/bookings/{b.id}').get_data(as_text=True)
    check('Charge $1370.00 Now' in page, 'the button says $1,370.00, not $0.00')
    check('$0.00 Now' not in page, 'the stale zero is gone')

    print('\n3. Charging asks Stripe for the right amount')
    CHARGES.clear()
    r = c.post(f'/bookings/{b.id}/charge-balance')
    check(r.get_json()['ok'] is True, 'the charge went through')
    check(len(CHARGES) == 1, 'exactly one charge attempted')
    check(CHARGES[0]['amount'] == 137000, f"Stripe asked for 137000 cents = $1,370 (got {CHARGES[0]['amount']})")
    check(CHARGES[0]['off_session'] is True, 'as an off-session charge on the saved card')
    db.session.expire_all()
    check(Booking.query.get(b.id).balance_due == 1370.0, 'and the stored figure was corrected')

    print('\n4. Editing the price keeps the balance in step')
    b2 = Booking(service_type='standard', name='Price Change', address='1 St',
                 email='p@x.com', price=300, deposit_paid=True,
                 status='confirmed', preferred_date='2026-08-10')
    db.session.add(b2); db.session.commit()
    c.post(f'/bookings/{b2.id}', data={'status': 'confirmed', 'price': '900'},
           follow_redirects=True)
    db.session.expire_all(); b2 = Booking.query.get(b2.id)
    check(b2.price == 900, 'price updated to $900')
    check(b2.balance_due == 850.0, 'and the balance followed to $850, not left at $0')

    print('\n5. A job with nothing owed cannot be charged by accident')
    b3 = Booking(service_type='standard', name='Already Paid', address='2 St', price=200,
                 stripe_customer_id='cus_y', stripe_payment_method_id='pm_y',
                 paid_at=datetime(2026, 8, 1), status='completed', preferred_date='2026-08-01')
    db.session.add(b3); db.session.commit()
    CHARGES.clear()
    r = c.post(f'/bookings/{b3.id}/charge-balance')
    check(r.get_json()['ok'] is False, 'refused')
    check('already paid in full' in r.get_json()['error'], f"and says why: \"{r.get_json()['error']}\"")
    check(CHARGES == [], 'Stripe was never called')
    page = c.get(f'/bookings/{b3.id}').get_data(as_text=True)
    check('Nothing to charge' in page or 'Balance collected' in page,
          'and the button offers nothing to press')

    print('\n6. No card on file is still refused')
    b4 = Booking(service_type='standard', name='No Card', address='3 St', price=400,
                 status='confirmed', preferred_date='2026-08-11')
    db.session.add(b4); db.session.commit()
    CHARGES.clear()
    r = c.post(f'/bookings/{b4.id}/charge-balance')
    check(r.get_json()['ok'] is False and 'No saved payment method' in r.get_json()['error'],
          'refused — no saved card')
    check(CHARGES == [], 'Stripe not called')

    print('\n7. A successful charge marks the booking PAID, not just "collected"')
    import finance
    from datetime import date as _d
    b5 = Booking(service_type='deep', name='Charged Today', address='8 St',
                 email='c@x.com', price=1420, deposit_paid=True,
                 stripe_customer_id='cus_z', stripe_payment_method_id='pm_z',
                 status='completed', preferred_date='2026-08-06')
    db.session.add(b5); db.session.commit()
    check(b5.paid_at is None, 'starts unpaid')
    check(finance.unpaid_outstanding() >= 1420, 'and shows in "still owed to you"')

    CHARGES.clear()
    r = c.post(f'/bookings/{b5.id}/charge-balance')
    check(r.get_json()['ok'] is True, 'the charge succeeds')
    db.session.expire_all(); b5 = Booking.query.get(b5.id)
    check(b5.paid_at is not None, 'paid_at is now set — this was the bug')
    check(b5.paid_method == 'card', 'recorded as a card payment')
    check(b5.balance_collected is True, 'and the balance flag too')

    print('\n8. So the money shows up where it should')
    start, end = finance.month_bounds(2026, 8)
    check(finance.revenue_between(start, end) >= 1420,
          'the $1,420 counts as August income')
    owed_names = [x.name for x in Booking.query.filter(
        Booking.paid_at.is_(None),
        Booking.status.in_(['confirmed', 'completed'])).all()]
    check('Charged Today' not in owed_names, 'and it is no longer "still owed to you"')

print('\n🎉 A charge takes the money AND marks the job paid.')
