"""Setting up a monthly client: same-date scheduling, a manual price that sticks
across the whole plan, and a welcome email the owner can see before it goes."""
import os, sys, tempfile
from datetime import date, timedelta
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/portal.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['CRM_BASE'] = 'https://crm.example.com'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
SENT = []
notifications.send_sms = lambda *a, **k: (True, 'ok')
def _capture(**kw):
    SENT.append(kw)
    return True, 'ok'
notifications.send_email = lambda to_email=None, to_name=None, subject=None, html=None, **k: _capture(
    to_email=to_email, to_name=to_name, subject=subject, html=html)

from app import create_app
from extensions import db
from models import Booking, Client, BusinessSetting
import recurring, portal_invite

def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')

app = create_app()
with app.app_context():
    db.create_all()
    BusinessSetting.set('business_name', 'Dazzle & Shine Maids')
    BusinessSetting.set('email', 'owner@example.com')
    BusinessSetting.set('city', 'Orlando'); BusinessSetting.set('state', 'FL')
    db.session.commit()

    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n1. A monthly client at a hand-set discounted price')
    client = Client(name='Renee Alvarez', email='renee@example.com',
                    phone='4075550188', zip_code='32801', address='14 Lake Ct')
    db.session.add(client); db.session.commit()
    seed = Booking(client_id=client.id, service_type='standard', name='Renee Alvarez',
                   email='renee@example.com', phone='4075550188', address='14 Lake Ct',
                   zip_code='32801', frequency='monthly', preferred_date='2026-09-09',
                   preferred_time='9:00 AM', price=185.0, status='confirmed')
    db.session.add(seed); db.session.commit()
    check(seed.price == 185.0, 'her price is whatever was typed, not the matrix figure')

    print('\n2. The plan lands on the same date every month')
    made = recurring.generate_series(seed)   # no window passed — same as the button
    check(made >= 10, f'a monthly plan fills a year by default, not 12 weeks ({made} added)')
    visits = Booking.query.filter_by(recurring_group=seed.recurring_group)\
                          .order_by(Booking.preferred_date).all()
    days = {date.fromisoformat(v.preferred_date).day for v in visits}
    check(days == {9}, f'every visit falls on the 9th — no drift (got {sorted(days)})')
    check(len({v.preferred_date for v in visits}) == len(visits), 'no duplicate dates')

    print('\n3. Her price and details carry to every visit')
    check(all(v.price == 185.0 for v in visits), 'the discounted price repeats on all of them')
    check(all(v.client_id == client.id for v in visits), 'all attached to her client record')
    check(all(v.preferred_time == '9:00 AM' for v in visits), 'and keep the same time')

    print('\n4. A top-up months later keeps the same day of the month')
    check(len(visits) >= 11, f'the plan is a year deep before the top-up ({len(visits)})')
    for v in visits[6:]:
        db.session.delete(v)
    db.session.commit()
    recurring.topup_all()
    after = Booking.query.filter_by(recurring_group=seed.recurring_group).all()
    days = {date.fromisoformat(v.preferred_date).day for v in after}
    check(days == {9}, f'still every visit on the 9th after a top-up (got {sorted(days)})')

    print('\n5. The owner can see the email before anybody else does')
    page = c.get(f'/bookings/clients/{client.id}/portal-invite/preview').get_data(as_text=True)
    check('Welcome, Renee!' in page, 'the preview greets her by first name')
    check('renee@example.com' in page, 'shows who it would go to')
    check('$185' in page, 'shows her actual price')
    check('Wednesday 9 September' in page, 'and her actual first date, written out')
    check('/portal/' in page, 'with her private portal link')
    check(client.portal_token in page, 'which is her own token')

    print('\n6. The welcome email mentions saving a card without asking for it')
    _, html, _ = __import__('blueprints.bookings', fromlist=['x'])._portal_email(client, 'welcome')
    check('If you' in html and 'save a card' in html, 'it is offered')
    check('Save a card →' not in html, 'but there is no call-to-action button pushing it')

    print('\n7. The follow-up email is the one that asks')
    nudge = c.get(f'/bookings/clients/{client.id}/portal-invite/preview?kind=nudge').get_data(as_text=True)
    check('Save a card →' in nudge, 'the nudge has the button')
    check('handle payment automatically' in nudge, 'and makes the actual request')
    check('never see the number' in nudge, 'while reassuring her about card safety')

    print('\n8. Sending a test goes to the owner, not the customer')
    SENT.clear()
    c.post(f'/bookings/clients/{client.id}/portal-invite/send',
           data={'kind': 'welcome', 'to': 'me'}, follow_redirects=True)
    check(len(SENT) == 1, 'one email sent')
    check(SENT[0]['to_email'] == 'owner@example.com', 'to the owner')
    check(SENT[0]['to_email'] != 'renee@example.com', 'NOT to the customer')
    check(SENT[0]['subject'].startswith('[TEST]'), 'and marked as a test in the subject')
    check(BusinessSetting.get(f'portal_invite_sent_{client.id}') == '',
          'a test does not count as having welcomed her')

    print('\n9. Sending for real goes to her, and is recorded')
    SENT.clear()
    c.post(f'/bookings/clients/{client.id}/portal-invite/send',
           data={'kind': 'welcome', 'to': 'customer'}, follow_redirects=True)
    check(SENT[0]['to_email'] == 'renee@example.com', 'it reaches the customer')
    check(not SENT[0]['subject'].startswith('[TEST]'), 'with a clean subject line')
    check(BusinessSetting.get(f'portal_invite_sent_{client.id}') == date.today().isoformat(),
          'and the client page now shows when she was welcomed')

    print('\n10. Her portal opens and shows the plan')
    pub = app.test_client()
    r = pub.get(f'/portal/{client.portal_token}')
    check(r.status_code == 200, 'the link works')
    check('ZIP' in r.get_data(as_text=True) or 'zip' in r.get_data(as_text=True).lower(),
          'and asks her to confirm who she is first')
    r = pub.post(f'/portal/{client.portal_token}/verify', data={'answer': '32801'},
                 follow_redirects=True)
    body = r.get_data(as_text=True)
    check('Renee' in body, 'once verified it is hers')
    check('$185' in body or '185' in body, 'showing her price')

    print('\n11. A wrong answer does not get in')
    stranger = app.test_client()
    r = stranger.post(f'/portal/{client.portal_token}/verify', data={'answer': '99999'},
                      follow_redirects=True)
    check('Upcoming cleanings' not in r.get_data(as_text=True), 'a wrong ZIP is refused')

print('\n🎉 Monthly plan holds its date, her price sticks, and nothing sends without a preview.')


# ── Some customers ask for a day of the week, not a date. ────────────────────
with app.app_context():
    print('\n12. A plan can repeat on a weekday instead of a date')
    c2 = Client(name='Marcus Bell', email='marcus@example.com', phone='4075550199',
                zip_code='32803', address='7 Oak Row')
    db.session.add(c2); db.session.commit()
    seed2 = Booking(client_id=c2.id, service_type='standard', name='Marcus Bell',
                    email='marcus@example.com', address='7 Oak Row', zip_code='32803',
                    frequency='monthly', preferred_date='2026-09-09',
                    price=210.0, status='confirmed')
    db.session.add(seed2); db.session.commit()
    check(recurring.describe_weekday(date(2026, 9, 9)) == '2nd Wednesday',
          'the 9th of September is correctly read as the 2nd Wednesday')

    r = c.post(f'/bookings/{seed2.id}/schedule-recurring',
               data={'monthly_mode': 'weekday'}, follow_redirects=True)
    check(r.status_code == 200, 'the plan schedules')
    v2 = Booking.query.filter_by(recurring_group=seed2.recurring_group)\
                      .order_by(Booking.preferred_date).all()
    dows = {date.fromisoformat(v.preferred_date).weekday() for v in v2}
    check(dows == {2}, f'every visit is a Wednesday (got {sorted(dows)})')
    positions = {recurring.weekday_position(date.fromisoformat(v.preferred_date))[1] for v in v2}
    check(positions == {2}, f'and every one is the 2nd Wednesday (got {sorted(positions)})')
    check(len({v.preferred_date for v in v2}) == len(v2), 'no duplicated visits')
    check(len(v2) >= 11, f'a year of them ({len(v2)})')

    print('\n13. Switching pattern moves future visits but never touches history')
    done = v2[1]
    done.status = 'completed'
    db.session.commit()
    before = len(v2)
    c.post(f'/bookings/{seed2.id}/schedule-recurring',
           data={'monthly_mode': 'date'}, follow_redirects=True)
    after = Booking.query.filter_by(recurring_group=seed2.recurring_group).all()
    kept = Booking.query.get(done.id)
    check(kept is not None, 'a completed visit survives the change')
    check(kept.status == 'completed', 'still marked completed')
    days = {date.fromisoformat(v.preferred_date).day for v in after
            if v.status == 'pending' and v.preferred_date > date.today().isoformat()}
    check(days == {9}, f'and the new future visits are all on the 9th (got {sorted(days)})')

print('\n🎉 Monthly plans repeat by date or by weekday, whichever the customer asked for.')


# ── The booking confirmation: safe by default, and visible before it sends. ──
with app.app_context():
    print('\n14. The confirmation can be previewed without sending')
    SENT.clear()
    page = c.get(f'/bookings/{seed.id}/confirmation/preview').get_data(as_text=True)
    check(SENT == [], 'previewing sends nothing at all')
    check("You're all set, Renee!" in page, 'it shows the real greeting')
    check('$185' in page, 'her real price')
    check('2026-09-09' in page, 'her real date')
    check('renee@example.com' in page, 'who the email would go to')
    check('4075550188' in page, 'and who the text would go to')
    check('Reply STOP to opt out' in page, 'including the text message itself, which never had a preview')

    print('\n15. The preview matches what actually sends')
    from blueprints.bookings import confirmation_content
    subject, html, sms = confirmation_content(seed)
    check(html in page, 'the previewed email is the very same HTML that would be sent')
    check(sms in page, 'and the previewed text is the same text')

    print('\n16. Sending asks for no money unless told to')
    SENT.clear()
    c.post(f'/bookings/{seed.id}/send-confirmation', data={'pay_kind': 'none'},
           follow_redirects=True)
    subjects = ' | '.join(s.get('subject') or '' for s in SENT)
    check(len(SENT) >= 1, f'the confirmation went ({len(SENT)} email(s))')
    check("You're booked" in subjects, 'it is the booking confirmation')
    check('invoice' not in subjects.lower() and 'pay' not in subjects.lower(),
          f'and no payment request rode along with it — sent: "{subjects}"')

print('\n🎉 Nothing reaches a customer that has not been seen first.')
