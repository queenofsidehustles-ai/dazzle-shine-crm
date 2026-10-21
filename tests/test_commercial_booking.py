"""Booking a job for a commercial account.

A commercial account was a record and nothing else: a business added by hand
could not be put on the calendar, sent a confirmation, or asked for money. The
only way to book one was to key it in as a house -- one bedroom, one bathroom.

A commercial job is now a Booking that names its account and carries a scope of
work in place of bedrooms and bathrooms, and it is paid the way the customer
prefers: a card link, or an invoice on net terms.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/cb.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SENT = []
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')


def _capture(to_email=None, to_name=None, subject='', html='', **k):
    SENT.append({'to': to_email, 'subject': subject, 'html': html})
    return True, 'stub'


notifications.send_email = _capture

from datetime import date, timedelta
from app import create_app
from extensions import db
from models import Booking, BusinessSetting, CommercialAccount
app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


with app.app_context():
    db.create_all()
    BusinessSetting.set('business_name', 'Dazzle & Shine Maids')
    db.session.commit()
    a = CommercialAccount(business_name='Sunrise Daycare', contact_name='Dana Ruiz',
                          email='dana@sunrise.example', phone='4075550100',
                          address='12 Oak St', city='Orlando', square_footage=3200,
                          category='daycare', frequency='weekly', billing_type='per_visit',
                          billing_amount=240, source='manual')
    db.session.add(a); db.session.commit()

    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n1. The account page offers to book a job, and the form is filled in from it')
    r = c.get(f'/commercial/{a.id}')
    check(r.status_code == 200 and f'/commercial/{a.id}/book'.encode() in r.data,
          'the account page links to Book a job')
    r = c.get(f'/commercial/{a.id}/book')
    page = r.data.decode()
    check(r.status_code == 200, 'the booking form opens')
    check('dana@sunrise.example' in page and '12 Oak St' in page, 'contact and address come from the account')
    check('240.00' in page, 'a per-visit account starts at its per-visit price')
    check('Bedrooms' not in page and 'Scope of work' in page, 'it asks for a scope of work, not bedrooms')

    print('\n2. Booked and invoiced on net terms')
    SENT.clear()
    r = c.post(f'/commercial/{a.id}/book', data={
        'contact_name': 'Dana Ruiz', 'email': 'dana@sunrise.example', 'phone': '4075550100',
        'address': '12 Oak St', 'city': 'Orlando', 'square_footage': '3200',
        'frequency': 'one_time', 'scope': ['Empty trash & replace liners', 'Vacuum carpets'],
        'scope_notes': '2 classrooms, 1 office', 'price': '$275.00', 'estimated_hours': '4',
        'preferred_date': '2026-11-02', 'preferred_time': '6:00 PM', 'status': 'confirmed',
        'payment_option': 'invoice_now', 'net_days': '14', 'notify_customer': '1',
    })
    check(r.status_code == 302 and '/bookings/' in r.headers['Location'], 'lands on the booking')
    b = Booking.query.filter_by(commercial_account_id=a.id).one()
    check(b.is_commercial and b.service_type == 'commercial', 'a commercial booking')
    check(b.name == 'Sunrise Daycare' and b.bedrooms is None, 'named for the business, no bedrooms')
    check(b.price == 275 and b.estimated_hours == 4, 'priced per visit, hours for the cleaner')
    check(b.scope_items() == ['Empty trash & replace liners', 'Vacuum carpets', '2 classrooms, 1 office'],
          'the scope is kept as a list')
    check(b.invoice_number and b.invoice_due_date == (date.today() + timedelta(days=14)).isoformat(),
          'invoiced, due in 14 days')
    subjects = [m['subject'] for m in SENT]
    check(any('booked' in s for s in subjects), 'the confirmation went')
    check(any(s.startswith('Invoice ') for s in subjects), 'the invoice went')
    conf = next(m['html'] for m in SENT if 'booked' in m['subject'])
    check('Vacuum carpets' in conf and '2 classrooms' in conf, 'the confirmation lists the scope')
    check('bedrooms' not in conf.lower(), 'and says nothing about bedrooms')

    print('\n3. Every page shows the business, not a house')
    r = c.get(f'/bookings/{b.id}')
    page = r.data.decode()
    check(r.status_code == 200 and 'Sunrise Daycare' in page and 'Scope of work' in page,
          'the booking page shows the account and scope')
    check('Correct what was booked' not in page, 'and not the bedroom correction form')
    r = c.post(f'/bookings/{b.id}/service', data={'service_type': 'standard', 'bedrooms': '1', 'bathrooms': '1'})
    b = Booking.query.get(b.id)
    check(b.service_type == 'commercial' and b.price == 275, 'the residential correction cannot rewrite it')
    r = c.get(f'/bookings/')
    check('None bed' not in r.data.decode(), 'the bookings list has no "None bed"')
    from blueprints.payments import payment_link_url
    with app.test_request_context():
        link = payment_link_url(b, 'full')
    from urllib.parse import urlparse
    r = c.get(urlparse(link).path)
    page = r.data.decode()
    check(r.status_code == 200 and 'Vacuum carpets' in page, 'the pay page shows the scope')
    check('None bed' not in page, 'and has no "None bed"')
    check(b.home_text() == '3,200 sq ft', 'its size is its square footage')

    print('\n4. Repeat visits stay commercial')
    import recurring
    b.frequency = 'weekly'; db.session.commit()
    nxt = recurring._copy_visit(b, date(2026, 11, 9), 'g1')
    check(nxt.commercial_account_id == a.id and nxt.scope_of_work == b.scope_of_work,
          'the next visit keeps the account and scope')
    check(nxt.estimated_hours == 4 and nxt.price == 275, 'and the hours and price')

    print('\n5. Card instead of invoice')
    SENT.clear()
    r = c.post(f'/commercial/{a.id}/book', data={
        'email': 'dana@sunrise.example', 'price': '275', 'frequency': 'one_time',
        'preferred_date': '2026-11-03', 'payment_option': 'full', 'notify_customer': '1',
    })
    b2 = Booking.query.filter_by(commercial_account_id=a.id).order_by(Booking.id.desc()).first()
    check(b2.id != b.id and not b2.invoice_number, 'booked without an invoice')
    check(len(SENT) >= 2, 'the confirmation and the payment link went')

    print('\n6. A price is required, and an account with jobs is not deleted')
    n = Booking.query.count()
    c.post(f'/commercial/{a.id}/book', data={'price': '', 'payment_option': 'none'})
    check(Booking.query.count() == n, 'no price, no job')
    c.post(f'/commercial/{a.id}/delete')
    check(CommercialAccount.query.get(a.id) is not None, 'the account with jobs is kept')

print('\nAll commercial booking checks passed.')
