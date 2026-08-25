"""Quoting a phone caller, and letting them book at the price they were given.

Someone rings, asks what a clean would cost and leaves an email address. The
quote email already existed but only fired from the website form, so a caller
got nothing unless it was written out by hand.

The price is the point of all this. A generic booking link drops them on a
calculator, and a calculator will happily return a different number from the one
said on the phone — a custom price, a discount, a judgement call about a big
house. Their link carries their price.
"""
import os, sys, tempfile
from datetime import datetime
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/q.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SENT = []
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda to_email=None, to_name=None, subject='', html='', **k: (
    SENT.append({'to': to_email, 'subject': subject, 'html': html}), (True, 'stub'))[1]

from app import create_app
from extensions import db
from models import Lead, Booking, Client, LsaLead, BusinessSetting, ChecklistTemplate
import quoting, lsa
app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


with app.app_context():
    db.create_all()
    BusinessSetting.set('business_name', 'Dazzle & Shine Maids')
    BusinessSetting.set('crm_base', 'https://crm.example.com')
    BusinessSetting.set('booking_link', 'https://dazzle.example.com/book')
    db.session.commit()

    print('\n1. The caller is a phone number until she takes their details')
    caller = LsaLead(lead_id='g-1', phone='4079876543', charge_status='Charged',
                     location='Kissimmee', received_at=datetime(2026, 8, 24),
                     track=lsa.QUOTED)
    db.session.add(caller); db.session.commit()
    check(caller.crm_lead_id is None, 'no CRM lead behind them yet')

    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'
    check(c.get(f'/leads/lsa/{caller.id}/quote').status_code == 200,
          'the quote form opens on that caller')

    print('\n2. The price she typed is the price that goes out')
    r = c.post(f'/leads/lsa/{caller.id}/quote', data={
        'name': 'Dana Whitfield', 'email': 'dana@example.com',
        'service_type': 'deep', 'bedrooms': '4', 'bathrooms': '3',
        'price': '415.00', 'city': 'Kissimmee', 'zip_code': '34746',
        'notes': 'Big dog, friendly',
    }, follow_redirects=True)
    check(r.status_code == 200, 'the quote sends')
    lead = Lead.query.filter_by(email='dana@example.com').first()
    check(lead is not None, 'a CRM lead now exists for her')
    check(lead.quoted_price == 415.00,
          'at the figure typed, not one the calculator worked out')
    check(lead.quote_token, 'and she has her own quote link')
    check(lead.notes == 'Big dog, friendly', 'call notes are kept on the lead')

    caller = LsaLead.query.get(caller.id)
    check(caller.crm_lead_id == lead.id, 'the Google Ads caller is linked to it')

    print('\n3. The email carries the price, the link and what we actually do')
    body = SENT[-1]['html']
    check('415.00' in body, 'the quoted price is in the email')
    check(lead.quote_token in body, 'along with her own link, not the generic one')
    check('Scrub baseboards throughout' in body,
          'and the deep-clean checklist she was promised')
    check('Everything in Standard Cleaning' in body, 'in full, not a summary')
    check('Deep Cleaning' in body, 'naming the service in plain English')

    print('\n4. Quoting stops the texts written for people we never reached')
    caller2 = LsaLead(lead_id='g-2', phone='4071112222', charge_status='Not charged',
                      received_at=datetime(2026, 8, 20))
    db.session.add(caller2); db.session.commit()
    lsa.start_sequence(caller2)
    check(caller2.in_sequence, 'this one is mid-sequence')
    c.post(f'/leads/lsa/{caller2.id}/quote', data={
        'name': 'Sam Reed', 'email': 'sam@example.com', 'service_type': 'standard',
        'bedrooms': '2', 'bathrooms': '1', 'price': '150'}, follow_redirects=True)
    caller2 = LsaLead.query.get(caller2.id)
    check(caller2.seq_stopped == 'quoted',
          'quoting them ends it — we have spoken to them now')
    check(caller2.track == lsa.QUOTED, 'and they move to the quoted track')

    print('\n5. Her link opens, shows her price and cannot be re-priced')
    page = c.get(f'/quote/{lead.quote_token}').get_data(as_text=True)
    check('$415.00' in page, 'the page shows exactly what she was quoted')
    check('Dana' in page, 'addressed to her')
    check('Scrub baseboards throughout' in page, 'with everything included listed out')
    check('$50' in page and '$365.00' in page, 'the deposit and the balance both add up')
    check(c.get('/quote/not-a-real-token').status_code == 404,
          'a made-up token is a 404, not somebody else’s quote')

    print('\n6. Booking through it uses the quoted price, not the calculator')
    r = c.post(f'/quote/{lead.quote_token}/book', data={
        'preferred_date': '2026-09-03', 'preferred_time': '09:00',
        'address': '18 Cypress Way', 'city': 'Kissimmee', 'zip_code': '34746',
        'notes': 'Gate code 4412'}, follow_redirects=False)
    check(r.status_code == 302, 'booking redirects onward')
    booking = Booking.query.filter_by(email='dana@example.com').first()
    check(booking is not None, 'a booking exists')
    check(booking.price == 415.00,
          'priced at the quote — the whole reason this page exists')
    check(booking.balance_due == 365.00, 'with the deposit taken off the balance')
    check(booking.preferred_date == '2026-09-03', 'on the date she chose')
    check(booking.address == '18 Cypress Way', 'at the address she gave')
    check('/pay-deposit/' in r.headers['Location'],
          'and hands straight to the deposit page that already exists')
    check(Client.query.filter_by(email='dana@example.com').first() is not None,
          'she is now a client on file')

    print('\n7. Booking closes the chasing down')
    lead = Lead.query.get(lead.id)
    check(lead.status == 'converted', 'the lead is converted, so the email drip stops')
    caller = LsaLead.query.get(caller.id)
    check(caller.booked, 'and the Google Ads caller is marked as booked')

    print('\n8. The link cannot be used twice')
    before = Booking.query.count()
    c.post(f'/quote/{lead.quote_token}/book', data={
        'preferred_date': '2026-09-10', 'address': 'x', 'city': 'y', 'zip_code': 'z'},
        follow_redirects=True)
    check(Booking.query.count() == before,
          'a second submission does not make a second booking and a second deposit')
    page = c.get(f'/quote/{lead.quote_token}').get_data(as_text=True)
    check('already booked' in page.lower(), 'the page says so plainly')

    print('\n9. The follow-up emails now contain a link that works')
    # Both said "book here" and then printed an empty variable, so every one of
    # them went out with the invitation intact and nothing to click.
    import blueprints.api as api
    quiet = Lead(name='Quiet Caller', email='quiet@example.com', phone='4075550000',
                 service_type='standard', quoted_price=180.0, status='new',
                 drip_step=1, quote_token='tok-quiet')
    db.session.add(quiet); db.session.commit()

    SENT.clear()
    api._send_drip_followup(quiet)
    check(SENT, 'the day-2 email sends')
    check('tok-quiet' in SENT[-1]['html'],
          'and carries her quote link — it used to carry an empty string')

    SENT.clear()
    api._send_drip_lastchance(quiet)
    check('tok-quiet' in SENT[-1]['html'], 'so does the last-chance email')

    print('\n10. A lead with no quote of its own still gets somewhere real')
    walkin = Lead(name='No Token', email='nt@example.com', service_type='standard',
                  quoted_price=120.0, status='new', drip_step=1)
    db.session.add(walkin); db.session.commit()
    SENT.clear()
    api._send_drip_followup(walkin)
    check('dazzle.example.com/book' in SENT[-1]['html'],
          'falling back to the general booking link rather than nothing at all')

    print('\n11. Re-quoting the same person updates their quote, not their inbox count')
    n_leads = Lead.query.count()
    quoting.quote_lead(name='Dana Whitfield', email='dana@example.com',
                       phone='4079876543', service_type='deep', price=460)
    check(Lead.query.count() == n_leads,
          'no second lead for the same email — one of them would be the wrong price')
    check(Lead.query.filter_by(email='dana@example.com').first().quoted_price == 460,
          'the price is updated in place')

    print('\nAll quote-email checks passed.')
