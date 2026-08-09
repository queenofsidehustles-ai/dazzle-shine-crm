"""Dragging a job to another day moves it — and never quietly leaves a cleaner
turning up on the old date."""
import os, sys, tempfile
from datetime import date, datetime
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/cal.db'
os.environ['SECRET_KEY'] = 'test'
os.environ.update({'TWILIO_ACCOUNT_SID': 'sid', 'TWILIO_AUTH_TOKEN': 'tok',
                   'TWILIO_PHONE': '+15550000'})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
TEXTS = []
notifications.send_sms = lambda to, msg: (TEXTS.append((to, msg)), (True, 'ok'))[1]
notifications.send_email = lambda *a, **k: (True, 'ok')
from app import create_app
from extensions import db
from models import Booking, BookingCrew, Staff
app = create_app()
import blueprints.bookings as bk
bk.send_sms = notifications.send_sms

def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')

with app.app_context():
    db.create_all()
    laura = Staff(name='Laura Moreira', email='l@x.com', phone='+14079841405',
                  is_active=True, pay_type='percent', pay_rate=50)
    db.session.add(laura); db.session.commit()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    b = Booking(service_type='deep', name='Ashley G', address='280 Ballow Dr',
                price=620, estimated_hours=10.25, labor_rate_applied=43,
                status='confirmed', preferred_date='2026-08-05', preferred_time='11 am')
    db.session.add(b); db.session.commit()

    print('\n1. The calendar makes jobs draggable')
    page = c.get('/bookings/calendar?year=2026&month=8').get_data(as_text=True)
    check('draggable="true"' in page, 'jobs are draggable')
    check('class="daycell"' in page, 'days are drop targets')
    check('data-date="2026-08-05"' in page, 'each day carries its date')
    check('Drag a job to another day' in page, 'and it says so')

    print('\n2. Dropping it on another day moves it')
    r = c.post(f'/bookings/{b.id}/reschedule', data={'date': '2026-08-12'})
    d = r.get_json()
    check(d['ok'] and d['moved'], 'the move succeeded')
    check(d['was'] == '2026-08-05' and d['now'] == '2026-08-12', 'from the 5th to the 12th')
    db.session.expire_all()
    check(Booking.query.get(b.id).preferred_date == '2026-08-12', 'and the job really moved')

    print('\n3. Nobody is texted automatically')
    check(TEXTS == [], 'no message fired on the drop — rearranging a week would spam the team')

    print('\n4. But it tells her who still thinks the old date')
    db.session.add(BookingCrew(booking_id=b.id, staff_id=laura.id, pay_amount=160))
    db.session.commit()
    r = c.post(f'/bookings/{b.id}/reschedule', data={'date': '2026-08-14'})
    d = r.get_json()
    check(d['crew'] == ['Laura Moreira'], 'names who is on the job')
    check(d['notify_url'] is not None, 'and hands back a way to tell her')

    print('\n5. One click tells her')
    r = c.post(d['notify_url'].replace('/bookings', '/bookings'), follow_redirects=True)
    check(len(TEXTS) == 1, 'exactly one text sent')
    to, msg = TEXTS[0]
    check('2026-08-14' in msg, f'with the new date: "{msg[:90]}..."')
    check('moved' in msg.lower(), 'and says it moved')
    check('Told Laura Moreira' in r.get_data(as_text=True), 'and confirms who was told')

    print('\n6. A completed job cannot be dragged')
    done = Booking(service_type='standard', name='Finished', address='1 St', price=200,
                   status='completed', preferred_date='2026-08-03')
    db.session.add(done); db.session.commit()
    r = c.post(f'/bookings/{done.id}/reschedule', data={'date': '2026-08-20'})
    check(r.get_json()['ok'] is False, 'the move is refused')
    check('completed' in r.get_json()['error'], 'and says why')
    db.session.expire_all()
    check(Booking.query.get(done.id).preferred_date == '2026-08-03', 'the date is untouched')
    page = c.get('/bookings/calendar?year=2026&month=8').get_data(as_text=True)
    import re
    chip = re.search(r'data-id="%d"' % done.id, page)
    check(chip is None, 'and it is not draggable on the page either')

    print('\n7. A nonsense date is refused')
    r = c.post(f'/bookings/{b.id}/reschedule', data={'date': 'next tuesday'})
    check(r.status_code == 400 and r.get_json()['ok'] is False, 'rejected')
    db.session.expire_all()
    check(Booking.query.get(b.id).preferred_date == '2026-08-14', 'and nothing moved')

    print('\n8. Dropping a job back where it started is a no-op')
    TEXTS.clear()
    r = c.post(f'/bookings/{b.id}/reschedule', data={'date': '2026-08-14'})
    check(r.get_json()['moved'] is False, 'reported as no move')
    check(TEXTS == [], 'and nobody is bothered')

print('\n🎉 Drag to reschedule, with nobody left on the wrong date.')
