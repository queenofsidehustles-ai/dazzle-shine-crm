"""Terms were shown to customers but never recorded as accepted. In a dispute
months later, "our terms say X" is worth nothing without proof the customer saw
and agreed to that wording on that day."""
import os, sys, tempfile, html as _html
from datetime import datetime
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/terms.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['STRIPE_SECRET_KEY'] = 'sk_' + 'test_notareal0042'
os.environ['STRIPE_PUBLISHABLE_KEY'] = 'pk_' + 'test_notareal'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'ok')
notifications.send_email = lambda **k: (True, 'ok')

from app import create_app
from extensions import db
from models import Booking, BusinessSetting
import customer_terms

def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')

app = create_app()

class _PI:
    id, status = 'pi_terms', 'succeeded'
    payment_method = 'pm_x'
    client_secret = 'cs_x'
    @staticmethod
    def create(**kw): return _PI()
    @staticmethod
    def retrieve(pid): return _PI()

with app.app_context():
    db.create_all()
    BusinessSetting.set('business_name', 'Test Cleaning Co')
    BusinessSetting.set('customer_terms', '**Payment terms**\n\nThe July wording.')
    db.session.commit()
    import stripe as _stripe
    _stripe.PaymentIntent = _PI
    pub = app.test_client()

    print('\n1. The deposit page now shows what they are agreeing to')
    b = Booking(service_type='deep', name='A Customer', email='c@example.com',
                phone='4070000000', address='1 St', price=1420,
                deposit_token='dep-tok', status='pending', preferred_date='2026-08-05')
    db.session.add(b); db.session.commit()
    page = _html.unescape(pub.get('/pay-deposit/dep-tok').get_data(as_text=True))
    check('Service &amp; payment terms' in page or 'Service & payment terms' in page,
          'the terms are on the deposit page — they were shown nothing before')
    check('The July wording' in page, 'with the actual wording')
    check('By paying you agree' in page, 'and what paying means')

    print('\n2. Paying the deposit records the agreement')
    check(b.terms_accepted_at is None, 'nothing recorded before they pay')
    pub.post('/pay-deposit/dep-tok/confirm', json={'payment_intent_id': 'pi_terms'})
    db.session.expire_all(); b = Booking.query.get(b.id)
    check(b.terms_accepted_at is not None, 'the moment of agreement is stored')
    check('The July wording' in (b.terms_accepted_text or ''),
          'along with the exact wording they saw')
    check(b.terms_accepted_ip, f'and where from ({b.terms_accepted_ip})')

    print('\n3. Editing the terms later cannot rewrite what was agreed')
    BusinessSetting.set('customer_terms', '**Payment terms**\n\nA much stricter August wording.')
    db.session.commit()
    db.session.expire_all(); b = Booking.query.get(b.id)
    check('July wording' in b.terms_accepted_text, 'the snapshot still says July')
    check('August wording' not in b.terms_accepted_text,
          "today's stricter wording did NOT travel back in time")

    print('\n4. The evidence pack states it as a fact, with that wording')
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'
    clean = _html.unescape(c.get(f'/bookings/{b.id}/dispute-evidence?clean=1').get_data(as_text=True))
    check('The customer accepted these terms on' in clean, 'the document says they accepted')
    check('July wording' in clean, 'and quotes what they accepted')
    check('August wording' not in clean, 'not what the terms say today')
    check(b.terms_accepted_ip in clean, 'with the IP address')

    print('\n5. An older booking with no record says so — loudly')
    old = Booking(service_type='deep', name='Older Job', email='old@example.com',
                  address='9 St', price=900, status='completed', preferred_date='2026-07-01')
    db.session.add(old); db.session.commit()
    working = _html.unescape(c.get(f'/bookings/{old.id}/dispute-evidence').get_data(as_text=True))
    check('no record that this customer accepted' in working,
          'the working copy is blunt about it')
    check('Do not tell the bank they agreed' in working,
          'and says plainly not to claim otherwise')
    clean_old = _html.unescape(
        c.get(f'/bookings/{old.id}/dispute-evidence?clean=1').get_data(as_text=True))
    check('accepted these terms on' not in clean_old,
          'and the document never claims an acceptance that did not happen')
    check('August wording' in clean_old,
          'it submits the terms as standing policy instead')

    print('\n6. Agreement is recorded once, at the first payment')
    first = b.terms_accepted_at
    check(customer_terms.record_acceptance(b) is False, 'a later payment does not overwrite it')
    db.session.expire_all()
    check(Booking.query.get(b.id).terms_accepted_at == first, 'the original moment stands')

print('\n🎉 What a customer agreed to is captured when they agree, and never rewritten.')


# ── Timestamps are stored in UTC and read by people in one place. ────────────
with app.app_context():
    print('\n7. The document shows local time, not UTC arithmetic')
    import scheduling
    BusinessSetting.set('timezone', 'America/New_York'); db.session.commit()

    job = Booking(service_type='deep', name='Timestamp Check', email='ts@example.com',
                  address='4 St', price=800, status='completed',
                  preferred_date='2026-08-05',
                  created_at=datetime(2026, 8, 1, 12, 0),
                  completed_at=datetime(2026, 8, 5, 22, 15),
                  paid_at=datetime(2026, 8, 5, 13, 42))
    db.session.add(job); db.session.commit()

    clean = _html.unescape(
        c.get(f'/bookings/{job.id}/dispute-evidence?clean=1').get_data(as_text=True))
    check('9:42 AM EDT' in clean,
          'a payment stored as 13:42 UTC reads as 9:42 AM EDT — the time it happened')
    check('(13:42 UTC)' in clean,
          'with UTC alongside, so a reviewer can cross-check against Stripe')
    check('Times shown in' in clean and 'EDT' in clean,
          'and the document says once, up front, which clock it is on')
    check('local time where the work was carried out' in clean,
          'in words a reviewer does not have to interpret')

    print('\n8. A job finishing late evening does not slide into the next day')
    check('5 August 2026' in clean,
          '22:15 UTC on the 5th is 6:15 PM on the 5th locally, not the 6th')
    check('6:15 PM' in clean, 'shown as an evening, which is when it happened')

print('\n🎉 Every time on the document is the time it actually happened.')
