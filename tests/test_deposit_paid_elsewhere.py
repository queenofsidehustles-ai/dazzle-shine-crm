"""Recording a deposit that was paid somewhere else.

A booking re-entered here after being taken in another system has already had
its deposit — the money is in the bank and the customer has been receipted.
Until now the only way to say so was “Mark paid”, which settles the booking in
full and reports a balance as collected that is still owed. This records the
deposit alone: the money counts, the balance stays owed, and nothing is sent to
a customer who paid days ago somewhere else.
"""
import os, sys, tempfile
from datetime import datetime
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/dpe.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SENT = []
import notifications
notifications.send_sms = lambda *a, **k: (SENT.append('sms'), (True, 'stub'))[1]
notifications.send_email = lambda *a, **k: (SENT.append('email'), (True, 'stub'))[1]

from app import create_app
from extensions import db
from models import Booking
from blueprints.payments import amount_due, collected

app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


def new_booking(price=390.0):
    b = Booking(service_type='moveout', name='Savannah Wyker', price=price,
                email='savannah@example.com', phone='5612359586',
                address='1 Palm Way', city='Orlando',
                preferred_date='2026-09-28', preferred_time='11:00 AM',
                status='pending')
    db.session.add(b); db.session.commit()
    return b


with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n1. The deposit counts, and the balance stays owed')
    b = new_booking()
    SENT.clear()
    r = c.post(f'/bookings/{b.id}/record-deposit',
               data={'amount': '50', 'paid_on': '2026-09-26',
                     'note': 'paid in the old CRM — ch_3UJxWs'},
               follow_redirects=True)
    check(r.status_code == 200, 'the page comes back')
    b = Booking.query.get(b.id)
    check(b.deposit_paid, 'the deposit is marked paid')
    check(float(b.deposit_amount_paid) == 50.0, 'for the amount actually taken')
    check(float(collected(b)) == 50.0, 'fifty dollars counts as received')
    check(float(amount_due(b)) == 340.0, 'and $340 of the $390 is still owed')
    check(b.status == 'confirmed', 'a pending booking becomes confirmed')
    check(b.deposit_paid_at.strftime('%Y-%m-%d') == '2026-09-26',
          'dated the day the money changed hands, not today')
    check('old CRM' in (b.notes or ''), 'the note says where it was paid')

    print('\n2. The customer hears nothing — they already paid, elsewhere')
    check(SENT == [], 'no email and no text went out')
    check(b.deposit_notified_at is not None,
          'and it is stamped as told, so nothing chases it later')

    print('\n3. It cannot be recorded twice')
    r = c.post(f'/bookings/{b.id}/record-deposit', data={'amount': '50'},
               follow_redirects=True)
    b = Booking.query.get(b.id)
    check(float(collected(b)) == 50.0, 'a second attempt does not double the money')

    print('\n4. Nonsense amounts are refused rather than stored')
    b2 = new_booking()
    c.post(f'/bookings/{b2.id}/record-deposit', data={'amount': '0'}, follow_redirects=True)
    check(not Booking.query.get(b2.id).deposit_paid, 'zero is refused')
    c.post(f'/bookings/{b2.id}/record-deposit', data={'amount': '900'}, follow_redirects=True)
    check(not Booking.query.get(b2.id).deposit_paid,
          'more than the price of the job is refused — that is a full payment')
    c.post(f'/bookings/{b2.id}/record-deposit', data={'amount': 'abc'}, follow_redirects=True)
    check(not Booking.query.get(b2.id).deposit_paid, 'and so is a word')

    print('\n5. A job already settled in full is left alone')
    b3 = new_booking()
    b3.paid_at = datetime(2026, 9, 20); b3.amount_collected = 390.0
    db.session.commit()
    c.post(f'/bookings/{b3.id}/record-deposit', data={'amount': '50'}, follow_redirects=True)
    b3 = Booking.query.get(b3.id)
    check(not b3.deposit_paid and float(collected(b3)) == 390.0,
          'no deposit is bolted onto a booking that is fully paid')

    print('\nAll deposit-paid-elsewhere checks passed.')
