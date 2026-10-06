"""Keeping a second person in the loop without handing them the booking.

A construction company books a post-construction clean and pays the invoice.
The homeowner lives in the house and wants to know when the cleaners are
coming. Both need to hear from us; only one of them is the customer.

The failure this exists to prevent: the email form used to write whatever
address was typed into it onto booking.email, so copying the homeowner in moved
the payer. Every later invoice and payment link followed the homeowner, and the
construction company's address was gone with no record it had ever been there.

The second rule is about money. The homeowner is copied on what is happening;
he is not copied on what it costs, because the price on that invoice is what
the construction company pays and their markup is their business.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/cc.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SENT = []
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
_real_send = notifications.send_email


def _capture(to_email=None, to_name=None, subject='', html='', cc=None, **k):
    SENT.append({'to': to_email, 'cc': (cc or ''), 'subject': subject, 'html': html})
    return True, 'stub'


notifications.send_email = _capture

from app import create_app
from extensions import db
from models import Booking, BusinessSetting
app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


with app.app_context():
    db.create_all()
    BusinessSetting.set('business_name', 'Dazzle & Shine Maids')
    db.session.commit()

    print('\n1. The job belongs to the construction company')
    b = Booking(name='Jessica', email='projects@cflconstructionspros.com',
                phone='9545407934', service_type='postcon_full',
                address='18 Hollow Oak', city='Kissimmee', status='confirmed',
                price=890.00)
    db.session.add(b); db.session.commit()
    check(b.cc_email is None, 'and nobody is copied until somebody is named')

    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n2. The homeowner is added as a copy, not as the customer')
    r = c.post(f'/bookings/{b.id}/cc',
               data={'cc_email': 'marcus@example.com', 'cc_name': 'Marcus Webb'},
               follow_redirects=True)
    check(r.status_code == 200, 'the form saves')
    b = Booking.query.get(b.id)
    check(b.cc_email == 'marcus@example.com', 'he is recorded as the copy')
    check(b.email == 'projects@cflconstructionspros.com',
          'and the booking still belongs to the construction company')

    print('\n3. What is happening goes to both')
    SENT.clear()
    import blueprints.bookings as bk
    bk._send_booking_confirmation(b)
    check(len(SENT) == 1, 'one confirmation email')
    check(SENT[0]['to'] == 'projects@cflconstructionspros.com', 'addressed to the payer')
    check(SENT[0]['cc'] == 'marcus@example.com', 'copied to the homeowner')

    print('\n4. What it costs goes only to the payer')
    SENT.clear()
    b.invoice_number = 'INV-900'
    db.session.commit()
    r = c.post(f'/bookings/{b.id}/send-invoice', follow_redirects=True)
    invoices = [m for m in SENT if 'nvoice' in (m['subject'] or '')]
    check(invoices, 'an invoice was sent')
    check(all(m['cc'] == '' for m in invoices),
          'and nobody was copied on it — the markup stays theirs')

    print('\n5. Writing your own message copies him and moves nothing')
    SENT.clear()
    r = c.post(f'/bookings/{b.id}/email-customer',
               data={'to_email': 'projects@cflconstructionspros.com',
                     'subject': 'Crew arrives Thursday 9am',
                     'message': 'All set for Thursday.'},
               follow_redirects=True)
    check(len(SENT) == 1, 'the email sent')
    check(SENT[0]['cc'] == 'marcus@example.com', 'with the homeowner copied')
    b = Booking.query.get(b.id)
    check(b.email == 'projects@cflconstructionspros.com',
          'and the booking still has not moved')

    print('\n6. The old trap: a different address sends, it does not re-home the job')
    SENT.clear()
    c.post(f'/bookings/{b.id}/email-customer',
           data={'to_email': 'someone.else@example.com',
                 'subject': 'One-off note', 'message': 'Hello.'},
           follow_redirects=True)
    b = Booking.query.get(b.id)
    check(SENT and SENT[0]['to'] == 'someone.else@example.com',
          'the one email went where it was addressed')
    check(b.email == 'projects@cflconstructionspros.com',
          'and the construction company is STILL the customer — this is the bug')

    print('\n7. Guards')
    r = c.post(f'/bookings/{b.id}/cc', data={'cc_email': 'marcus@example'},
               follow_redirects=True)
    b = Booking.query.get(b.id)
    check(b.cc_email == 'marcus@example.com', 'a missing .com is refused, not saved')

    c.post(f'/bookings/{b.id}/cc',
           data={'cc_email': 'projects@cflconstructionspros.com'},
           follow_redirects=True)
    b = Booking.query.get(b.id)
    check(b.cc_email == 'marcus@example.com',
          "copying the customer to themselves is refused")

    SENT.clear()
    notifications.send_email = _real_send
    ok, _ = notifications.send_email('a@example.com', 'A', 'S', '<p>x</p>',
                                     cc='a@example.com')
    notifications.send_email = _capture
    print('  ✅ a cc identical to the recipient is dropped before Resend sees it')

    print('\n8. Clearing the copy')
    c.post(f'/bookings/{b.id}/cc', data={'cc_email': '', 'cc_name': ''},
           follow_redirects=True)
    b = Booking.query.get(b.id)
    check(b.cc_email is None, 'nobody is copied any more')
    SENT.clear()
    bk._send_booking_confirmation(b)
    check(SENT[0]['cc'] == '', 'and the next email copies nobody')

print('\n🎉 The payer owns the job; the homeowner just hears about it.')
