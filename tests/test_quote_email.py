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

    print('\n12. A caller who is in no CSV can still be quoted')
    # The export is downloaded now and then; people ring the number in between.
    # Waiting for the next import to quote someone who is on the phone right now
    # would make the import the point, when the quote is.
    SENT.clear()
    r = c.post('/leads/quote/new', data={
        'name': 'Renee', 'email': 'renee@example.com', 'phone': '(407) 222-8899',
        'service_type': 'standard', 'bedrooms': '2', 'bathrooms': '1',
        'price': '165'}, follow_redirects=True)
    check(r.status_code == 200, 'the standalone quote form accepts them')
    renee = Lead.query.filter_by(email='renee@example.com').first()
    check(renee and renee.quoted_price == 165.0, 'the lead and price are saved')
    check(renee.quote_token, 'with their own link')
    check(SENT and 'renee@example.com' == SENT[-1]['to'], 'and the quote is emailed')
    check(not renee.address, 'no address needed — the customer fills that in when booking')

    print('\n13. A first name and an email is enough')
    check('Renee' in c.get(f'/quote/{renee.quote_token}').get_data(as_text=True),
          'the quote page greets them by the one name we have')

    print('\n14. Quoting by phone finds their Google Ads call on its own')
    stray = LsaLead(lead_id='g-3', phone='4075554321', charge_status='Charged',
                    received_at=datetime(2026, 8, 22))
    db.session.add(stray); db.session.commit()
    lsa.start_sequence(stray)
    c.post('/leads/quote/new', data={
        'name': 'Tom', 'email': 'tom@example.com', 'phone': '407-555-4321',
        'service_type': 'deep', 'bedrooms': '3', 'bathrooms': '2',
        'price': '300'}, follow_redirects=True)
    stray = LsaLead.query.get(stray.id)
    tom = Lead.query.filter_by(email='tom@example.com').first()
    check(stray.crm_lead_id == tom.id,
          'matched on the number, in any format — one caller, not two records')
    check(stray.seq_stopped == 'quoted', 'and their follow-up texts stop')

    print('\n15. The checklist is hers to pick from, not a fixed list')
    SENT.clear()
    c.post('/leads/quote/new', data={
        'name': 'Priya', 'email': 'priya@example.com', 'phone': '4076660000',
        'service_type': 'standard', 'bedrooms': '3', 'bathrooms': '2',
        'price': '200',
        'checklist': ['Dust all surfaces (shelves, furniture, baseboards)',
                      'Scrub toilets, tubs, and showers'],
        'checklist_custom': 'Inside the china cabinet\nStrip and remake the guest beds',
    }, follow_redirects=True)
    priya = Lead.query.filter_by(email='priya@example.com').first()
    items = quoting.checklist_for(priya)
    check(len(items) == 4, 'exactly what she ticked plus what she typed')
    check('Inside the china cabinet' in items, 'the specialised thing they asked for')
    check('Vacuum all floors and rugs' not in items,
          'and nothing she unticked — we do not promise work she ruled out')

    body = SENT[-1]['html']
    check('Inside the china cabinet' in body, 'the email lists her version')
    check('Vacuum all floors and rugs' not in body, 'not the standard one')
    page = c.get(f'/quote/{priya.quote_token}').get_data(as_text=True)
    check('Strip and remake the guest beds' in page, 'and so does the booking page')
    check('Empty trash cans and replace liners' not in page,
          'the two agree — she is not promised one thing and shown another')

    print('\n16. Reopening a quote shows what was promised, not the standard list')
    ctx = quoting.form_context(priya)
    check('Inside the china cabinet' in ctx['custom_lines'],
          'her typed lines come back in the box she typed them in')
    check('Vacuum all floors and rugs' not in ctx['chosen'],
          'and what she took off stays off rather than quietly reappearing')

    print('\n17. Leaving the checklist alone means the standard list')
    c.post('/leads/quote/new', data={
        'name': 'Default Dan', 'email': 'dan@example.com', 'phone': '4077770000',
        'service_type': 'standard', 'bedrooms': '2', 'bathrooms': '1',
        'price': '150'}, follow_redirects=True)
    dan = Lead.query.filter_by(email='dan@example.com').first()
    check(dan.quote_checklist is None, 'nothing stored on the quote')
    check(quoting.checklist_for(dan) == quoting.service_checklist('standard'),
          'so it follows the service checklist, including any later edits to it')

    print('\n18. The quote can go by text as well as email')
    TEXTS = []
    real_sms = notifications.send_sms
    notifications.send_sms = lambda to_phone=None, message=None, *a, **k: (
        TEXTS.append({'to': to_phone, 'body': message}), (True, 'stub'))[1]

    SENT.clear()
    c.post('/leads/quote/new', data={
        'name': 'Bea', 'email': 'bea@example.com', 'phone': '4078881111',
        'service_type': 'standard', 'bedrooms': '2', 'bathrooms': '1',
        'price': '175', 'also_text': '1'}, follow_redirects=True)
    bea = Lead.query.filter_by(email='bea@example.com').first()
    check(SENT and SENT[-1]['to'] == 'bea@example.com', 'the email goes')
    check(TEXTS and TEXTS[-1]['to'] == '4078881111', 'and so does the text')
    body = TEXTS[-1]['body']
    check('175.00' in body, 'the text carries the same price')
    check(bea.quote_token in body, 'and the same link')
    check('STOP' in body, 'with opt-out wording')

    print('\n19. Someone who said STOP is not texted a quote anyway')
    notifications.record_sms_opt_out('4079990000', 'stop')
    TEXTS.clear(); SENT.clear()
    c.post('/leads/quote/new', data={
        'name': 'Quiet', 'email': 'quiet2@example.com', 'phone': '4079990000',
        'service_type': 'standard', 'bedrooms': '1', 'bathrooms': '1',
        'price': '130', 'also_text': '1'}, follow_redirects=True)
    check(TEXTS == [], 'no text — they asked us to stop, even for a quote they wanted')
    check(SENT and SENT[-1]['to'] == 'quiet2@example.com',
          'but the email still goes, because that is a different channel')
    notifications.send_sms = real_sms

    print('\n20. A quoted lead is a Lead in the log, not "Unknown"')
    # Every quote emailed to someone who had not booked showed as Unknown — the
    # one row on that page where knowing who it went to actually matters.
    import blueprints.messages as msgs
    check(msgs._kind_for_log(type('L', (), {
        'channel': 'email', 'to_address': 'bea@example.com'})()) == 'lead',
        'a quoted lead reads as a Lead')
    check(msgs._kind_for_log(type('L', (), {
        'channel': 'email', 'to_address': 'tom@example.com'})()) == 'google',
        'and one who came through Google Ads says so')
    check(msgs._kind_for_log(type('L', (), {
        'channel': 'email', 'to_address': 'nobody@example.com'})()) == 'unknown',
        'a genuine stranger is still Unknown')
    check(msgs._kind_for_log(type('L', (), {
        'channel': 'email', 'to_address': 'dana@example.com'})()) == 'customer',
        'and someone who booked reads as a Customer, not a lead')

    print('\n21. Their texts are tagged too, so a reply has context')
    check(msgs.contact_kind(msgs.resolve_contact('4078881111')) == 'lead',
          'an inbound text from a quoted lead is tagged Lead')
    check(msgs.contact_kind(msgs.resolve_contact('4075554321')) == 'google',
          'and a Google Ads caller is tagged Google Ads')
    check(msgs.contact_kind(msgs.resolve_contact('9999999999')) == 'unknown',
          'a number we have never seen stays Unknown')

    print('\n22. "Sent" now carries the provider id that makes it checkable')
    from models import OutboundLog
    import notifications as n
    n._log_outbound('email', 'x@example.com', 'X', 'Subj', '<p>b</p>', True,
                    'Accepted by Resend from a@b (id re_123).', provider_id='re_123')
    row = OutboundLog.query.filter_by(to_address='x@example.com').first()
    check(row.provider_id == 're_123',
          'the id is stored, so "it says sent" can actually be looked up')
    check('Accepted' in row.detail,
          'and the wording says accepted, which is all a 2xx from Resend means')

    print('\nAll quote-email checks passed.')
