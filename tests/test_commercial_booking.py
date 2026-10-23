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
    # $25/hr is what a cleaner costs (Commercial Pricing); the $43 in Settings
    # -> Pricing is the residential rate. The price is revenue and moves with
    # the job; the cost does not.
    import commercial_pricing
    from pricing import get_labor_rate
    check(b.labor_rate_applied == commercial_pricing.cleaner_rate() == 25,
          f'the cleaner is paid the commercial cost, $25/hr (not ${get_labor_rate():.0f})')
    check(b.labor_budget == 100, '4 hours x $25 = $100 of cleaner pay on a $275 visit')
    # The $100 is the job's pot, not one person's pay: it splits across the crew.
    check(b.default_crew_pay(None, size=1) == 100 and b.hours_each(size=1) == 4,
          'one cleaner: $100 for 4 hours')
    check(b.default_crew_pay(None, size=2) == 50 and b.hours_each(size=2) == 2,
          'two cleaners: $50 each for 2 hours each, still $100 in all')
    check(not b.rate_is_stale, 'and it is not offered a "re-rate" to the residential rate')
    b.labor_rate_applied = 0
    check(b.rate_applied == 0 and b.labor_budget == 0,
          'a rate locked at $0 stays $0, not "unset" and read from today\'s setting')
    check(b.rate_is_stale, 'and moving it is offered, not done silently')
    b.labor_rate_applied = 25; db.session.commit()
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

    print('\n7. A repeat made when a visit is finished keeps the whole job')
    from blueprints.bookings import _create_next_recurring
    b.frequency = 'weekly'; b.recurring_group = None; b.crew_size = 2
    b.stripe_customer_id = 'cus_test'; b.stripe_payment_method_id = 'pm_test'
    b.agent = 'Vee'; db.session.commit()
    _create_next_recurring(b); db.session.commit()
    nxt = Booking.query.filter_by(commercial_account_id=a.id,
                                  preferred_date='2026-11-09').one()
    check(nxt.sqft == 3200 and nxt.crew_size == 2, 'the building size and the crew')
    check(nxt.stripe_payment_method_id == 'pm_test', 'the card on file')
    check(nxt.source == 'commercial' and nxt.agent == 'Vee', 'and who it is credited to')
    check(nxt.scope_of_work == b.scope_of_work and nxt.status == 'pending', 'unstarted, same scope')

    print('\n8. A paid commercial visit is not also a residential commission')
    import va_commission
    from datetime import datetime
    b2.agent = 'Vee'; b2.paid_at = datetime.utcnow(); db.session.commit()
    now = datetime.utcnow()
    out = va_commission.commission_for_month('Vee', now.year, now.month)
    check(not [l for l in out['lines'] if l['type'].startswith('residential')]
          and out['new_closes'] == 0,
          f'no residential close or recurring line for it ({out["lines"]})')

    print('\n9. "Invoice the morning of the job" sends a real invoice')
    import scheduling, lifecycle
    today = scheduling.local_now().date().isoformat()
    c.post(f'/commercial/{a.id}/book', data={
        'email': 'dana@sunrise.example', 'price': '275', 'frequency': 'one_time',
        'preferred_date': today, 'preferred_time': '12:00 AM', 'payment_option': 'none'})
    b3 = Booking.query.filter_by(commercial_account_id=a.id).order_by(Booking.id.desc()).first()
    check(b3.preferred_date == today and not b3.invoice_number, 'booked for today, not invoiced yet')
    SENT.clear()
    lifecycle.run_lifecycle_emails()
    b3 = Booking.query.get(b3.id)
    check(b3.invoice_number and b3.invoice_due_date ==
          (date.today() + timedelta(days=14)).isoformat(),
          f'the morning run issued invoice {b3.invoice_number}, due in 14 days')
    check(any(m['subject'].startswith(f'Invoice {b3.invoice_number}') for m in SENT),
          'and emailed it')

    print('\n10. The cleaner sees the scope before claiming, and the owner can correct it')
    from models import Staff
    st = Staff(name='Maria Alvarez', email='m@example.com', phone='4075550111',
               is_active=True, pay_type='percent', pay_rate=50.0, worker_model='contractor',
               agreement_token='maria-token')
    db.session.add(st); b.claim_token = 'claim-token'; b.open_for_claim = True
    db.session.commit()
    page = c.get('/claim/claim-token/maria-token').data.decode()
    check('Vacuum carpets' in page and '2 classrooms' in page, 'the claim page lists the scope')
    page = c.get(f'/bookings/{b.id}').data.decode()
    check('Correct the scope of work' in page, 'the booking page has a scope correction')
    c.post(f'/bookings/{b.id}/scope', data={'scope_of_work': '• Vacuum carpets\n• Restrooms', 'sqft': '3400'})
    b = Booking.query.get(b.id)
    check(b.scope_items() == ['Vacuum carpets', 'Restrooms'] and b.sqft == 3400 and b.price == 275,
          'the scope and size change, the price does not')
    house = Booking(name='Pat', service_type='standard', bedrooms='3', bathrooms='2', price=150)
    db.session.add(house); db.session.commit()
    c.post(f'/bookings/{house.id}/scope', data={'scope_of_work': 'x', 'sqft': '9'})
    check(Booking.query.get(house.id).scope_of_work is None, 'and a house is not given one')

    print('\n11. A monthly account books from the agreement it signed')
    import json
    from decimal import Decimal
    from types import SimpleNamespace
    import blueprints.commercial as commercial
    m = CommercialAccount(business_name='Oak Offices', email='ops@oak.example', city='Orlando',
                          category='office', frequency='weekly', billing_type='monthly',
                          billing_amount=516, square_footage=1000, source='manual')
    db.session.add(m); db.session.commit()
    signed = SimpleNamespace(
        services='Office Cleaning, Restroom sanitation', price_per_visit=Decimal('120'),
        scope_notes='No kitchen', sqft='4,000',
        line_items=json.dumps({'first_visit_charge': 80,
                               'areas': [{'name': 'Lobby', 'lines': [{'label': 'Mop floors'}]}]}))
    old_terms = SimpleNamespace(services='Old work', price_per_visit=Decimal('99'),
                                scope_notes='', sqft='', line_items=None)
    real = commercial._agreements
    commercial._agreements = lambda acct: (
        [(SimpleNamespace(effective_on=date(2026, 10, 1)), signed, 'Ann', None),
         (SimpleNamespace(effective_on=date(2026, 9, 1)), old_terms, 'Ann', object())]
        if acct.id == m.id else [])
    try:
        page = c.get(f'/commercial/{m.id}/book').data.decode()
    finally:
        commercial._agreements = real
    check('200.00' in page and 'first-visit charge' in page,
          'the first job starts at the agreed $120 a visit plus the $80 first-visit charge')
    check('Restroom sanitation' in page and 'Lobby: Mop floors' in page and 'No kitchen' in page,
          'the scope is the work it signed for')
    check('Old work' not in page, 'not the terms an amendment replaced')
    check('value="4000"' in page, 'and the size it was quoted at')
    page = c.get(f'/commercial/{m.id}/book').data.decode()
    check('From the signed agreement' not in page and 'first-visit' not in page,
          'with no agreement, the account is all it has')

print('\nAll commercial booking checks passed.')
