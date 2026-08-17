"""A paid job has to produce a receipt the customer can hand to a landlord.

The invoice page printed 'Amount paid: $0.00' on anything already settled — it
was showing what was still owed, which is $0.00 by definition once someone has
paid. It also required an invoice number to be reachable, so a job paid straight
off a pay link had no document at all."""
import os, sys, tempfile
from datetime import datetime
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/rc.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import Booking
import invoicing
app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


with app.app_context():
    db.create_all()
    c = app.test_client()

    print('\n1. A job paid off a pay link, no invoice ever issued')
    b = Booking(service_type='moveout', name='Miriam U', address='9 Elm', city='Orlando',
                bedrooms=3, bathrooms=2, price=350.50, email='m@example.com',
                preferred_date='2026-07-19', pay_token='tok-paid',
                paid_at=datetime(2026, 7, 19, 18, 44), paid_method='card',
                deposit_paid=True)
    db.session.add(b); db.session.commit()
    check(b.invoice_number is None, 'she has no invoice number — she never got an invoice')

    r = c.get('/invoice/tok-paid')
    html = r.get_data(as_text=True)
    check(r.status_code == 200, 'the document still opens on the pay token alone')
    check('RECEIPT' in html and 'PAID IN FULL' in html, 'and it presents itself as a paid receipt')
    check('$350.50' in html, 'showing the amount she actually paid')
    check('Amount paid' in html and '$0.00' not in html, 'not $0.00, which is what she still owes')
    check('19 Jul 2026' in html, 'with the date the money arrived')
    check('by card' in html, 'and how she paid')
    check('Move-Out / Move-In Cleaning' in html, 'naming the service she bought, in plain English')

    print('\n2. The deposit is part of what she paid, not a deduction from it')
    items = invoicing.line_items(b)
    check(not any('Deposit' in d for d, _ in items), 'no "deposit already paid" credit on a settled job')
    check(round(sum(a for _, a in items if a is not None), 2) == invoicing.total_paid(b),
          'and the line items add up to the total printed at the bottom')

    print('\n3. Still an invoice, not a receipt, while money is owed')
    u = Booking(service_type='standard', name='Owes Money', address='4 Oak', price=200,
                pay_token='tok-owed', deposit_paid=True)
    db.session.add(u); db.session.commit()
    invoicing.issue(u)
    html = c.get('/invoice/tok-owed').get_data(as_text=True)
    check('Total due' in html and 'PAID IN FULL' not in html, 'it reads as an invoice')
    check('Pay this invoice' in html, 'and still offers her a way to pay')
    items = invoicing.line_items(u)
    check(any('Deposit' in d for d, _ in items), 'the deposit she already paid is credited back')
    from blueprints.payments import amount_due
    check(round(sum(a for _, a in items if a is not None), 2) == amount_due(u),
          'and the rows add up to the balance she owes')

    print('\n4. A discount is shown once, not taken off twice')
    d = Booking(service_type='standard', name='Discounted', address='5 Pine', price=180,
                discount_amount=20, discount_code='SPRING', pay_token='tok-disc',
                paid_at=datetime(2026, 8, 1, 12, 0), paid_method='cash')
    db.session.add(d); db.session.commit()
    items = invoicing.line_items(d)
    check(round(sum(a for _, a in items if a is not None), 2) == 180.00,
          f'$200 of cleaning less $20 comes to the $180 she paid (got {items})')

    print('\n5. A tip is receipted too — she paid it')
    t = Booking(service_type='standard', name='Tipper', address='6 Fir', price=150,
                tip_amount=25, pay_token='tok-tip',
                paid_at=datetime(2026, 8, 2, 12, 0), paid_method='card')
    db.session.add(t); db.session.commit()
    check(invoicing.total_paid(t) == 175.00, 'the total she was charged includes the tip')
    html = c.get('/invoice/tok-tip').get_data(as_text=True)
    check('Tip for the cleaner' in html and '$175.00' in html, 'and the receipt itemizes it')


# ── The link has to be reachable from the paid booking, not just exist ──────
with app.app_context():
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n6. The owner can reach it from the paid booking itself')
    paid = Booking.query.filter_by(pay_token='tok-paid').first()
    html = c.get(f'/bookings/{paid.id}').get_data(as_text=True)
    check(f'/invoice/{paid.pay_token}' in html, 'the paid booking page links to the receipt')
    check('Paid receipt' in html, 'and calls it a receipt, in the Payment card')

    print('\n7. Nothing was broken on a booking still waiting to be paid')
    owed = Booking.query.filter_by(pay_token='tok-owed').first()
    html = c.get(f'/bookings/{owed.id}').get_data(as_text=True)
    check('Send invoice' in html or 'Resend invoice' in html, 'the invoice controls are still there')
    check('Paid receipt' not in html, 'and no receipt is offered for money that has not arrived')

print('\n🎉 All receipt checks passed.')
