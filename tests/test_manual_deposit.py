"""Not every deposit goes through Stripe — cash on the doorstep, Zelle, Venmo,
a check. The back office needs to record one of those without either (a)
marking the whole booking paid in full, which is what the existing
"mark paid manually" button does, or (b) leaving the deposit uncredited, which
would let a saved card get auto-charged the full price instead of just the
remaining balance — collecting the deposit a second time, on the card, on top
of the cash already in hand.
"""
import os, sys, tempfile
from datetime import datetime
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/manualdep.db'
os.environ['SECRET_KEY'] = 'test-secret-key'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
sent = []
notifications.send_sms = lambda *a, **k: (True, 'ok')
notifications.send_email = lambda **k: (sent.append(k), (True, 'ok'))[1]

from app import create_app
from extensions import db
from models import Booking
from blueprints.payments import amount_due, collected
import pricing

app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


def a_booking(name, **kw):
    b = Booking(service_type='standard', name=name, email=f'{name.lower()}@example.com',
                status='pending', price=300.0, **kw)
    db.session.add(b)
    db.session.commit()
    return b


with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n1. Recording a cash deposit credits only the deposit, not the whole job')
    b = a_booking('Cash Paying Carla')
    check(amount_due(b) == 300.0, 'nothing paid yet')
    sent.clear()
    r = c.post(f'/bookings/{b.id}/mark-deposit-paid',
               data={'method': 'cash', 'amount': '50', 'paid_on': '2026-01-10',
                     'send_receipt': '1'},
               follow_redirects=True)
    check(r.status_code == 200, 'the form posts')
    db.session.refresh(b)
    check(b.deposit_paid is True, 'the deposit is recorded as paid')
    check(b.deposit_method == 'cash', 'and by what method')
    check(float(b.deposit_amount_paid) == 50.0, 'for the amount actually handed over')
    check(b.status == 'confirmed', 'a tentative booking is confirmed by taking the deposit')
    check(amount_due(b) == 250.0,
          'only the deposit is credited — the balance still asks for the rest')
    receipt = next((m for m in sent if 'deposit' in m['subject'].lower()
                     and m['to_email'] == b.email), None)
    check(receipt is not None, 'and she is emailed a deposit receipt')
    check('Cash' in receipt['html'] and 'Paid by' in receipt['html'],
          'that correctly says she paid by Cash, not the hardcoded "Card" it used to say')

    print('\n2. It does not double-book if pressed again')
    sent.clear()
    r = c.post(f'/bookings/{b.id}/mark-deposit-paid',
               data={'method': 'cash', 'amount': '50'}, follow_redirects=True)
    check('already has a deposit' in r.get_data(as_text=True).lower(),
          'the second attempt is refused')
    check(amount_due(b) == 250.0, 'the balance is unchanged')
    check(len(sent) == 0, 'and no second receipt goes out')

    print('\n3. Leaving the amount blank uses the standing deposit setting')
    d = a_booking('Default Amount Dee')
    c.post(f'/bookings/{d.id}/mark-deposit-paid', data={'method': 'zelle'},
           follow_redirects=True)
    db.session.refresh(d)
    check(float(d.deposit_amount_paid) == float(pricing.get_deposit()),
          'the standard deposit is used when none is typed')
    check(d.deposit_method == 'zelle', 'with the method she picked')

    print('\n4. Unticking the receipt box records the money and stays silent')
    # A real <input type=checkbox> that is unticked is simply absent from the
    # POST body — this is that case, same as the existing "mark paid" button.
    e = a_booking('Quiet Quinn')
    sent.clear()
    c.post(f'/bookings/{e.id}/mark-deposit-paid',
           data={'method': 'venmo', 'amount': '50'}, follow_redirects=True)
    db.session.refresh(e)
    check(e.deposit_paid is True, 'the deposit is still recorded')
    check(e.deposit_notified_at is None, 'but marked as not yet receipted')
    check(len(sent) == 0, 'no email goes out — none was requested')

    print('\n5. A saved card is never asked for the deposit a second time')
    # This is the whole point: a customer who paid the $50 deposit in cash but
    # left a card on file for the balance must only ever be charged the $250
    # that is actually still owed, never the full $300.
    g = a_booking('Card On File Gina', stripe_customer_id='cus_test123',
                  stripe_payment_method_id='pm_test123')
    c.post(f'/bookings/{g.id}/mark-deposit-paid',
           data={'method': 'cash', 'amount': '50'}, follow_redirects=True)
    db.session.refresh(g)
    check(amount_due(g) == 250.0,
          "amount_due — what autocharge() and 'Charge Balance Now' both read — "
          "is $250, not $300: the card can never be charged for the cash deposit")

print('\n🎉 Manual (non-Stripe) deposits are credited, receipted once, and never double-collected.')
