"""A job re-scoped upwards after it was paid still owes the difference.

Ashley booked a three-bed two-bath, paid a $50 deposit and then the $340
balance, and the house turned out to be a four-bed three-bath. The scope was
corrected and the price went from $390 to $482.

Every record of payment in the CRM was a flag — deposit_paid, balance_collected,
and a paid_at meaning "settled in full" — and a flag is only true against the
price on the day it was set. So the booking went on saying Paid in full, printed
the NEW price of $482 as the amount received, and amount_due() short-circuited
to $0 the moment it saw paid_at. The charge button read "Balance collected ✓",
the customer's own payment link said the booking was already paid and refused
her card, and the $92 could not be collected by any route in the system. The
business was $92 short and nothing anywhere disagreed.

What is stored is now the amount received, not the verdict. Paid in full became
a question the numbers answer, and it re-answers itself when either moves.
"""
import os, sys, tempfile
from datetime import datetime
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/re.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['STRIPE_SECRET_KEY'] = 'sk_test_fake'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import Booking
import finance, invoicing
from blueprints.payments import amount_due, collected, is_settled, mark_paid

app = create_app()

CHARGES = []
import payment_service
class _Intent:
    status = 'succeeded'
    id = 'pi_topup_1'
    client_secret = 'cs_stub'
class _PI:
    @staticmethod
    def create(**kw):
        CHARGES.append(kw)
        return _Intent()
class _Customer:
    id = 'cus_stub'
    @staticmethod
    def create(**kw):
        return _Customer()
# payment_service.stripe is the stripe module itself, so this covers the
# customer-facing pay page as well as the saved-card charge.
payment_service.stripe.PaymentIntent = _PI
payment_service.stripe.Customer = _Customer
payment_service.send_email = lambda *a, **k: True


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n1. The job as it was booked and paid')
    b = Booking(service_type='standard', name='Ashley G', address='280 Ballow Dr',
                email='ashley@example.com', phone='4079890063',
                bedrooms='3', bathrooms='2', price=390.0, status='completed',
                preferred_date='2026-09-05', pay_token='tok-ash',
                stripe_customer_id='cus_a', stripe_payment_method_id='pm_a',
                deposit_paid=True, deposit_amount_paid=50.0)
    db.session.add(b); db.session.commit()
    mark_paid(b, method='card', notify=False)
    check(collected(b) == 390.0, 'the $50 deposit and the $340 balance are recorded as $390 received')
    check(amount_due(b) == 0 and is_settled(b), 'and at $390 the job is genuinely settled')

    print('\n2. The scope changes — four bed, three bath, $92 more')
    b.bedrooms, b.bathrooms = '4', '3'
    b.price = 482.0
    db.session.commit()
    check(collected(b) == 390.0, 'what was received does not move when the price does')
    check(amount_due(b) == 92.0, 'so $92 is owed — this returned $0.00 before')
    check(not is_settled(b), 'and the job is no longer paid in full')

    print('\n3. The booking page says so, and offers the money')
    page = c.get(f'/bookings/{b.id}').get_data(as_text=True)
    check('Part paid' in page, 'the Payment card calls it part paid')
    check('$390.00 of $482.00 received' in page, 'showing what came in against what the job now costs')
    check('Paid in full' not in page, 'and no longer claims it was paid in full')
    check('Charge $92.00 Now' in page, 'with a button for exactly the $92 outstanding')
    check('Balance collected ✓' not in page, 'the old "balance collected" badge is gone')

    print('\n4. Charging it asks Stripe for $92, not $482 and not nothing')
    CHARGES.clear()
    r = c.post(f'/bookings/{b.id}/charge-balance')
    check(r.get_json()['ok'] is True, 'the charge goes through')
    check(len(CHARGES) == 1 and CHARGES[0]['amount'] == 9200,
          f'Stripe was asked for 9200 cents (got {CHARGES[0]["amount"] if CHARGES else None})')
    db.session.expire_all(); b = Booking.query.get(b.id)
    check(collected(b) == 482.0, 'and the whole $482 is now recorded as received')
    check(is_settled(b) and amount_due(b) == 0, 'the job is settled again')

    print('\n5. The customer could have paid it herself too')
    b2 = Booking(service_type='standard', name='Self Pay', address='2 Oak', price=300.0,
                 pay_token='tok-self', status='completed', preferred_date='2026-09-05')
    db.session.add(b2); db.session.commit()
    mark_paid(b2, method='card', notify=False)
    b2.price = 360.0
    db.session.commit()
    page = c.get('/pay/tok-self').get_data(as_text=True)
    check('60.00' in page, 'her payment link asks for the $60 difference')
    r = c.post('/pay/tok-self/intent', json={})
    check(r.get_json().get('ok') is not False,
          'and the page will raise a payment intent instead of refusing her card')

    print('\n6. An invoice for it reads as owed, not as paid')
    invoicing.issue(b2)
    check(invoicing.status(b2) != 'paid', 'the invoice is not marked paid while $60 is owed')
    rows = invoicing.line_items(b2)
    check(round(sum(a for _, a in rows if a is not None), 2) == amount_due(b2),
          f'and its rows add up to the $60 balance (got {rows})')

    print('\n7. The money is not counted as income until it arrives')
    # b2 has taken $300 against a $360 price. Revenue must show the $300.
    start, end = finance.month_bounds(b2.paid_at.year, b2.paid_at.month)
    rev = finance.revenue_between(start, end)
    check(rev == 482.0 + 300.0, f'revenue counts what was received, not the prices (${rev:,.2f})')
    check(finance.unpaid_outstanding() == 60.0,
          f'and the $60 still owed shows in "still owed to you" (${finance.unpaid_outstanding():,.2f})')

    print('\n8. Correcting a booking whose payment was never recorded as an amount')
    # Every booking from before the amount column reads NULL, so a settled one
    # falls back to its price — right until the price is raised afterwards, at
    # which point nothing on the row remembers the old total. She is asked.
    legacy = Booking(service_type='deep', name='Legacy', address='3 Pine', price=482.0,
                     status='completed', preferred_date='2026-08-01', pay_token='tok-leg',
                     paid_at=datetime(2026, 8, 1, 12, 0), paid_method='card',
                     deposit_paid=True, deposit_amount_paid=50.0)
    db.session.add(legacy); db.session.commit()
    check(legacy.amount_collected is None, 'it records no amount at all, as every old row does')
    check(is_settled(legacy), 'so it falls back to the price and reads as settled')
    r = c.post(f'/bookings/{legacy.id}/amount-collected',
               data={'amount_collected': '390'}, follow_redirects=True)
    db.session.expire_all(); legacy = Booking.query.get(legacy.id)
    check(legacy.amount_collected == 390.0, 'she can say what actually landed')
    check(amount_due(legacy) == 92.0 and not is_settled(legacy),
          'and the $92 becomes collectable')
    check('92.00' in r.get_data(as_text=True), 'the page tells her what is now owed')
    check('Amount received corrected' in (legacy.internal_notes or ''),
          'with the correction written into the booking history')

    print('\n9. The correction cannot be used to invent money')
    r = c.post(f'/bookings/{legacy.id}/amount-collected',
               data={'amount_collected': '900'}, follow_redirects=True)
    db.session.expire_all(); legacy = Booking.query.get(legacy.id)
    check(legacy.amount_collected == 390.0, 'more than the price is refused')
    r = c.post(f'/bookings/{legacy.id}/amount-collected',
               data={'amount_collected': 'nine hundred'}, follow_redirects=True)
    db.session.expire_all(); legacy = Booking.query.get(legacy.id)
    check(legacy.amount_collected == 390.0, 'and so is anything that is not a number')

    print('\n10. Zeroing it takes the job back out of income')
    z = Booking(service_type='standard', name='Never Paid', address='4 Fir', price=200.0,
                status='completed', preferred_date='2026-09-05', pay_token='tok-z')
    db.session.add(z); db.session.commit()
    mark_paid(z, method='cash', notify=False)
    c.post(f'/bookings/{z.id}/amount-collected', data={'amount_collected': '0'},
           follow_redirects=True)
    db.session.expire_all(); z = Booking.query.get(z.id)
    check(z.paid_at is None, 'a job that took nothing is not a paid job')
    check(amount_due(z) == 200.0, 'the whole $200 is owed again')

    print('\n11. A late deposit webhook cannot invent money on a settled job')
    # Stripe's webhook for the $50 deposit can land after the balance has been
    # paid — mark_deposit_paid exists to be called more than once for the same
    # money. By then the deposit is already inside the total received, and
    # adding it again would put $50 nobody paid into the P&L.
    from blueprints.payments import mark_deposit_paid
    w = Booking(service_type='standard', name='Late Webhook', address='5 Ash',
                price=390.0, status='completed', preferred_date='2026-09-05')
    db.session.add(w); db.session.commit()
    mark_paid(w, method='card', notify=False)
    mark_deposit_paid(w, amount_cents=5000)
    check(collected(w) == 390.0, 'the total received is still the $390 that arrived')
    check(amount_due(w) == 0, 'and nothing is owed')


print('\n🎉 A price that moves after payment leaves a balance, and the balance can be charged.\n')
