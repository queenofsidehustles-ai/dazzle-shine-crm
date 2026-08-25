"""A customer who pays a $50 deposit has to be told the money arrived.

Two things record that deposit: the browser posting to /pay-deposit/<token>/confirm
once Stripe confirms the card, and Stripe's payment_intent.succeeded webhook.
Both guarded on deposit_paid, and whichever got there first set it — but only the
browser path sent the customer anything. Stripe's webhook is usually the faster
of the two, so the common case was: money taken, booking confirmed, customer
emailed nothing at all.

And even when the browser did win, what it sent was the booking confirmation.
That mentions the $50 but never says it was received and is dated to the booking
rather than the payment — not something anyone could treat as a receipt.
"""
import os, sys, tempfile
from datetime import datetime
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/dr.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Capture every outbound email instead of sending one.
SENT = []
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda to_email=None, to_name=None, subject='', html='', **k: (
    SENT.append({'to': to_email, 'subject': subject, 'html': html}), (True, 'stub'))[1]

from app import create_app
from extensions import db
from models import Booking
import blueprints.payments as pay
pay.send_email = notifications.send_email
app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


def to_customer(email):
    return [m for m in SENT if m['to'] == email]


def receipt_for(email):
    return [m for m in to_customer(email) if 'eceipt' in m['subject']]


with app.app_context():
    db.create_all()

    print('\n1. Alice pays her deposit and Stripe\'s webhook lands first')
    alice = Booking(service_type='deep', name='Alice Greene', email='alice.greene62@gmail.com',
                    phone='3344620191', address='3749 Paradiso Cr', city='Kissimmee',
                    zip_code='34746', bedrooms=3, bathrooms=2, price=390.00,
                    balance_due=340.00, preferred_date='2026-08-27', preferred_time='8:30',
                    deposit_token='tok-alice', status='pending')
    db.session.add(alice); db.session.commit()

    # The webhook, arriving before the customer's browser posts its confirm.
    pay.mark_deposit_paid(alice, amount_cents=5000)
    check(alice.deposit_paid, 'the deposit is recorded')
    check(alice.status == 'confirmed', 'and the booking is confirmed')
    check(len(receipt_for(alice.email)) == 1,
          'she is sent a receipt — the webhook path used to send her nothing')

    r = receipt_for(alice.email)[0]
    check('$50.00' in r['html'], 'stating the amount that actually left her card')
    check('$340.00' in r['html'], 'and what is still due on the day')
    check(alice.deposit_paid_at is not None, 'the day the money arrived is recorded')
    check(alice.deposit_paid_at.strftime('%d %b %Y') in r['html'],
          'and the receipt is dated to it, not to the day she booked')
    check(f'#{alice.id}' in r['html'], 'with a booking reference she can quote')

    print('\n2. Her browser then posts its confirm, as it always would')
    before = len(to_customer(alice.email))
    sent_again = pay.mark_deposit_paid(alice, amount_cents=5000)
    check(sent_again is False, 'the second arrival knows it has nothing to say')
    check(len(to_customer(alice.email)) == before, 'so she is not receipted twice')

    print('\n3. The other order — browser first, webhook second')
    bob = Booking(service_type='standard', name='Bob Reyes', email='bob@example.com',
                  phone='4075550142', address='12 Oak', price=200.00, balance_due=150.00,
                  deposit_token='tok-bob', status='pending')
    db.session.add(bob); db.session.commit()

    check(pay.mark_deposit_paid(bob, amount_cents=5000) is True, 'the browser notifies him')
    check(pay.mark_deposit_paid(bob, amount_cents=5000) is False, 'the webhook then stays quiet')
    check(len(receipt_for(bob.email)) == 1, 'exactly one receipt, whichever order they land in')

    print('\n4. A balance charge is not a deposit')
    # charge_balance stamps the booking with its own payment intent, so the
    # webhook for that charge finds this booking too. mark_paid has already
    # receipted the full amount; a deposit receipt on top would be nonsense.
    carol = Booking(service_type='deep', name='Carol Diaz', email='carol@example.com',
                    phone='4075550188', address='8 Pine', price=300.00,
                    paid_at=datetime.utcnow(), paid_method='card', deposit_paid=True)
    db.session.add(carol); db.session.commit()

    check(pay.mark_deposit_paid(carol, amount_cents=25000) is False,
          'a booking already settled in full sends no deposit receipt')
    check(receipt_for(carol.email) == [], 'her inbox stays as it was')

    print('\n5. The receipt quotes the charge, not what we meant to charge')
    dee = Booking(service_type='standard', name='Dee Okafor', email='dee@example.com',
                  phone='4075550199', address='5 Birch', price=280.00, balance_due=205.00,
                  deposit_token='tok-dee', status='pending')
    db.session.add(dee); db.session.commit()
    pay.mark_deposit_paid(dee, amount_cents=7500)   # a $75 deposit on a bigger job
    check('$75.00' in receipt_for(dee.email)[0]['html'],
          'a deposit that was not $50 is receipted at what Stripe actually took')

    print('\n6. The back office can receipt a deposit taken before receipts existed')
    # Exactly the state every deposit already in the database is in: the money
    # is recorded, nothing was ever sent, and no payment date was ever stored.
    old = Booking(service_type='deep', name='Prior Customer', email='prior@example.com',
                  phone='4075550123', address='2 Cedar', price=390.00,
                  deposit_paid=True, status='confirmed')
    db.session.add(old); db.session.commit()
    check(old.deposit_notified_at is None, 'she was never receipted')
    check(old.deposit_paid_at is None, 'and we never recorded when she paid')

    ok, detail = pay.send_deposit_receipt_now(old)
    check(ok, f'the back office can still send her one ({detail or "sent"})')
    check(len(receipt_for(old.email)) == 1, 'and she gets it')
    check(old.deposit_notified_at is not None, 'the booking now knows she has been told')

    print('\n7. A receipt with no known date says nothing rather than guessing')
    # She paid days ago. Stamping today's date would put a false date on a
    # document she may hand to someone who cares about the difference.
    body = receipt_for(old.email)[0]['html']
    check('Date paid' not in body,
          'no date row at all, rather than one claiming she paid today')
    check(datetime.utcnow().strftime('%d %b %Y') not in body,
          "and today's date appears nowhere on it")
    check('$50.00' in body and '$340.00' in body, 'the amounts are still right')

    print('\n8. Resending is allowed, and does not move the payment date')
    was = old.deposit_notified_at
    ok, _ = pay.send_deposit_receipt_now(old)
    check(ok, 'a second copy can be sent on request')
    check(len(receipt_for(old.email)) == 2, 'she receives it')
    check(old.deposit_notified_at == was,
          'the first-told timestamp is left alone — it records when, not how often')

    print('\nAll deposit-receipt checks passed.')
