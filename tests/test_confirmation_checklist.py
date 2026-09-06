"""A booking confirmation says what the customer is getting.

It named the service, the date and the price. A customer reading it had no way
to know whether that included the inside of the oven — and this is the email she
opens on the morning of the clean to check exactly that.

The list also has to be the one she was promised, not the standard one for the
service. A quote can have lines taken off it: "they said don't do the oven".
Rebuilding the list from the service default at confirmation time would promise
her the oven back, in writing, over the top of what was agreed on the phone.
"""
import os, sys, tempfile, json
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/cc.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
MAILS, TEXTS = [], []
notifications.send_sms = lambda to_phone=None, message=None, *a, **k: (
    TEXTS.append(message or ''), (True, 'stub'))[1]
def _mail(to_email=None, to_name=None, subject=None, html=None, *a, **k):
    MAILS.append({'to': to_email, 'subject': subject or '', 'html': html or ''})
    return True, 'stub'
notifications.send_email = _mail
from app import create_app
from extensions import db
from models import Booking, Lead
import quoting
from blueprints.bookings import confirmation_content
app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n1. The confirmation lists the work, not just the price')
    b = Booking(service_type='moveout', name='Dana Cole', email='dana@x.com',
                phone='4079990000', address='7 Oak', city='Orlando',
                bedrooms='3', bathrooms='2', price=425.0, status='confirmed',
                preferred_date='2026-09-20')
    db.session.add(b); db.session.commit()
    subject, html, sms = confirmation_content(b)
    expected = quoting.service_checklist('moveout')
    check(len(expected) > 25, f'a move-out is {len(expected)} tasks')
    check(all(i in html for i in expected), 'every one of them is in the email')
    check(f"{len(expected)} tasks" in html, 'headed with the count')
    check('All deep clean tasks' not in html,
          'and none of the shorthand the cleaners work from')

    print('\n2. The text says where to find it without becoming a wall of text')
    check(len(sms) < 320, f'the text stays a text ({len(sms)} chars)')
    check('in your email' in sms, 'and points at the list rather than repeating it')

    print('\n3. What she agreed on the phone is what the confirmation promises')
    # A quote with the oven taken off it, accepted into a booking.
    lead = Lead(name='No Oven', email='nooven@x.com', phone='4075551111',
                service_type='moveout', quoted_price=400.0, quote_token='tok-no')
    db.session.add(lead); db.session.commit()
    kept = [i for i in expected if 'oven' not in i.lower()]
    quoting.set_checklist(lead, kept)
    db.session.commit()
    booking = quoting.accept_quote(lead, preferred_date='2026-09-21')
    check(booking.promised_checklist, 'the promise is carried onto the booking')
    _, html2, _ = confirmation_content(booking)
    check('oven' not in html2.lower(),
          'the confirmation does not re-promise the oven she was told was off')
    check(all(i in html2 for i in kept), 'everything she did agree to is there')

    print('\n4. A booking made by hand still describes the work')
    plain = Booking(service_type='standard', name='Walk In', email='w@x.com',
                    price=180.0, status='confirmed', preferred_date='2026-09-22')
    db.session.add(plain); db.session.commit()
    _, html3, _ = confirmation_content(plain)
    check(all(i in html3 for i in quoting.service_checklist('standard')),
          'it falls back to the standard list for the service')

    print('\n5. The deposit-paid confirmation carries it too')
    # The other confirmation path — the one that fires when a deposit lands —
    # goes through an editable template, so the list is appended rather than
    # required to be in a copy the owner edited months ago.
    from models import EmailTemplate
    if not EmailTemplate.query.filter_by(trigger='booking_confirmed').first():
        db.session.add(EmailTemplate(
            trigger='booking_confirmed', name='Booking confirmed', is_active=True,
            subject='Your booking is confirmed',
            body='Hi {{first_name}}, you are booked for {{booking_date}}. '
                 'Balance due: ${{balance}}.'))
        db.session.commit()
    MAILS.clear(); TEXTS.clear()
    dep = Booking(service_type='deep', name='Deposit Paid', email='dep@x.com',
                  phone='4075552222', address='9 Fir', city='Orlando',
                  bedrooms='3', bathrooms='2', price=300.0, status='confirmed',
                  preferred_date='2026-09-23', deposit_paid=True,
                  deposit_amount_paid=50.0, amount_collected=50.0)
    db.session.add(dep); db.session.commit()
    from blueprints.api import _send_confirmation
    _send_confirmation(dep)
    body = ' '.join(m['html'] for m in MAILS)
    deep = quoting.service_checklist('deep')
    check(all(i in body for i in deep), 'the deep-clean tasks are in that email too')
    check('250.00' in body,
          'and the balance is worked out from what she actually paid, not a constant')

print('\n🎉 A confirmation says what the money buys, and says what was agreed.\n')
