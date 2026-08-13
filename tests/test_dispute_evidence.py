"""A card network gives you days to prove a service was authorised and delivered.
The evidence is already in the CRM — the booking, the payment, every message and
when it went, the photos the cleaner took — but scattered across pages, and
nobody assembles it calmly under a deadline."""
import os, sys, tempfile, json, html as _html
from datetime import datetime, timedelta
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/eviD.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'ok')
notifications.send_email = lambda **k: (True, 'ok')

from app import create_app
from extensions import db
from models import Booking, Client, JobChecklist, OutboundLog, BusinessSetting

def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')

app = create_app()
with app.app_context():
    db.create_all()
    BusinessSetting.set('business_name', 'Test Cleaning Co'); db.session.commit()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n1. A disputed job, as it sits in the CRM')
    cl = Client(name='A Customer', email='cust@example.com', phone='4079990063',
                address='280 Ballow Dr', card_brand='Visa', card_last4='8313')
    db.session.add(cl); db.session.commit()
    b = Booking(client_id=cl.id, service_type='deep', name='A Customer',
                email='cust@example.com', phone='4079990063', address='280 Ballow Dr',
                city='Orlando', zip_code='32801', bedrooms='5', bathrooms='3',
                price=1420.0, deposit_paid=True, status='completed',
                preferred_date='2026-08-05', preferred_time='9:00 AM',
                assigned_cleaner='Lauren Diaz', hours_worked=11.5,
                paid_at=datetime(2026, 8, 6, 14, 30), paid_method='card',
                completed_at=datetime(2026, 8, 5, 18, 0),
                stripe_payment_intent='pi_test_evidence',
                stripe_payment_method_id='pm_test_card')
    db.session.add(b); db.session.commit()

    for when, ch, subj, body in [
        (datetime(2026, 8, 1, 9, 0), 'email', "You're booked", 'Your deep clean is confirmed'),
        (datetime(2026, 8, 5, 8, 0), 'sms', '', 'Your cleaner is on the way'),
        (datetime(2026, 8, 6, 14, 31), 'email', 'Payment received', 'Thank you for your payment'),
    ]:
        db.session.add(OutboundLog(channel=ch, to_address=cl.email if ch == 'email' else cl.phone,
                                   to_name=cl.name, subject=subj, body=body,
                                   status='sent', created_at=when))
    db.session.add(OutboundLog(channel='email', to_address='someone.else@example.com',
                               to_name='Not Them', subject='Unrelated', body='x',
                               status='sent', created_at=datetime(2026, 8, 3)))
    chk = JobChecklist(booking_id=b.id, token='tok-e', items='[]', completed_items='[]',
                       before_photos=json.dumps(['https://img/before1.jpg']),
                       after_photos=json.dumps(['https://img/after1.jpg', 'https://img/after2.jpg']),
                       photos_submitted_at=datetime(2026, 8, 5, 17, 45))
    db.session.add(chk); db.session.commit()

    print('\n2. The pack states the service that was sold')
    # Unescape so an apostrophe in a subject line doesn't fail the check.
    page = _html.unescape(c.get(f'/bookings/{b.id}/dispute-evidence').get_data(as_text=True))
    check('280 Ballow Dr' in page, 'the address the work was done at')
    check('Deep Cleaning' in page or 'deep' in page.lower(), 'the service')
    check('2026-08-05' in page, 'the date of service')
    check('Lauren Diaz' in page, 'who was on site')
    check('11.5' in page, 'and how long it took')

    print('\n3. And the payment, with the Stripe reference')
    check('$1420.00' in page, 'the amount')
    check('pi_test_evidence' in page, 'the charge id the bank will match against')
    check('Visa ending 8313' in page, 'the card')
    check('entered their own card details' in page,
          'and that the deposit was paid by the customer on their own card')

    print('\n4. Proof the work happened')
    check('before1.jpg' in page, 'the before photo')
    check('after1.jpg' in page and 'after2.jpg' in page, 'both after photos')
    check('strongest evidence' in page, 'flagged as the thing most worth attaching')

    print('\n5. Every message to that customer — and nobody else\'s')
    check("You're booked" in page, 'the confirmation')
    check('on the way' in page, 'the on-the-way text')
    check('Payment received' in page, 'the receipt')
    check('someone.else@example.com' not in page,
          "another customer's mail is not swept into this pack")
    check('Unrelated' not in page, 'nor its contents')

    print('\n6. It warns rather than letting her overstate her case')
    check('as they stand today' in page, 'the terms are labelled as current')
    check('paste the wording that was in' in page,
          'telling her to use the version in force at the time')
    check('matches what this' in page, 'and why that matters')

    print('\n7. Gaps are named, not hidden')
    bare = Booking(service_type='standard', name='No Records', address='9 Nowhere',
                   price=200, status='completed', preferred_date='2026-08-01')
    db.session.add(bare); db.session.commit()
    page = _html.unescape(c.get(f'/bookings/{bare.id}/dispute-evidence').get_data(as_text=True))
    check('No photographs were recorded' in page, 'it says plainly there are no photos')
    check('No messages to this customer are on record' in page, 'and no messages')
    check('a call log with dates still counts' in page, 'while suggesting what to use instead')

    print('\n8. The clean copy carries no advice, only the record')
    clean = _html.unescape(
        c.get(f'/bookings/{b.id}/dispute-evidence?clean=1').get_data(as_text=True))

    # Every phrase below is guidance for the owner. None belongs in front of a bank.
    for phrase in ['strongest evidence', 'gap you', 'winnable case',
                   'Submit only what', 'attach those instead', 'call log with dates',
                   'not what this customer agreed to', 'as they stand today',
                   'This is your working copy']:
        check(phrase not in clean, f'no coaching: "{phrase}" is gone')
    # The only remaining mention is a navigation link, and printing drops the
    # navigation along with the rest of the app.
    check('@media print' in clean and 'aside { display: none' in clean.replace(', ', ', '),
          'the sidebar, top bar and banners are all excluded from the PDF')

    check('Record of service and payment' in clean, 'it reads as a document')
    check('Test Cleaning Co' in clean, 'headed with the business name')
    check('Prepared' in clean, 'and dated')

    print('\n9. But every fact survives')
    for fact in ['280 Ballow Dr', '2026-08-05', 'Lauren Diaz', '$1420.00',
                 'pi_test_evidence', 'Visa ending 8313', 'before1.jpg', 'after2.jpg',
                 'Payment received', '11.5']:
        check(fact in clean, f'kept: {fact}')

    print('\n10. The terms are in the clean copy, stated plainly')
    check('Service terms' in clean, 'a terms section is included')
    check('Payment terms' in clean, 'with the actual wording')
    check('Test Cleaning Co provides cleaning services' in clean,
          'introduced as the terms this business trades under')
    check('winnable' not in clean and 'as they stand today' not in clean,
          'and without any of the internal commentary about them')
    working = _html.unescape(c.get(f'/bookings/{b.id}/dispute-evidence').get_data(as_text=True))
    check('as they stand today' in working,
          'while the working copy still reminds her to check the version')

print('\n🎉 A working copy that advises her, and a clean document that does not.')
