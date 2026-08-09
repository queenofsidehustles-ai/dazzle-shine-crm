"""Reaching the whole team: a free-form blast, and a weekly availability ask
whose answers come back as data."""
import os, sys, tempfile
from datetime import date, timedelta
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/tm.db'
os.environ['SECRET_KEY'] = 'test'
os.environ.update({'TWILIO_ACCOUNT_SID': 'sid', 'TWILIO_AUTH_TOKEN': 'tok',
                   'TWILIO_PHONE': '+15550000', 'RESEND_API_KEY': 'key'})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
TEXTS, EMAILS = [], []
notifications.send_sms = lambda to, msg: (TEXTS.append((to, msg)), (True, 'ok'))[1]
notifications.send_email = lambda **kw: (EMAILS.append(kw), (True, 'ok'))[1]
from app import create_app
from extensions import db
from models import Staff, Availability
import blueprints.team as tm
tm.send_sms = notifications.send_sms
tm.send_email = notifications.send_email
tm.translate = lambda msg, target=None: '[ES] ' + msg
app = create_app()

def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')

with app.app_context():
    db.create_all()
    laura = Staff(name='Laura Moreira', email='l@x.com', phone='+14079841405',
                  is_active=True, pay_type='percent', pay_rate=50, agreement_token='tok-laura')
    ana = Staff(name='Ana Ruiz', email='a@x.com', phone='+14079842222',
                is_active=True, pay_type='percent', pay_rate=50,
                language='es', agreement_token='tok-ana')
    gone = Staff(name='Former Cleaner', email='g@x.com', phone='+1407', is_active=False,
                 pay_type='percent', pay_rate=50)
    db.session.add_all([laura, ana, gone]); db.session.commit()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n1. Broadcast a message to the whole team')
    TEXTS.clear()
    r = c.post('/team/broadcast', data={
        'message': 'Happy birthday {name}! 🎂 Thank you for everything.',
        'channel': 'sms'}, follow_redirects=True)
    check(len(TEXTS) == 2, f'texted both active cleaners, not the inactive one (got {len(TEXTS)})')
    bodies = {t[0]: t[1] for t in TEXTS}
    check('Happy birthday Laura!' in bodies['+14079841405'], 'Laura gets her own name in it')
    check('[ES]' in bodies['+14079842222'], 'Ana gets it in Spanish')
    check('Ana' in bodies['+14079842222'], 'with her name too')
    check('texted 2' in r.get_data(as_text=True), 'and it reports what it sent')

    print('\n2. Sending to just some of them')
    TEXTS.clear()
    c.post('/team/broadcast', data={'message': 'Just you', 'channel': 'sms',
                                    'staff_ids': [str(laura.id)]}, follow_redirects=True)
    check(len(TEXTS) == 1 and TEXTS[0][0] == '+14079841405', 'only Laura was texted')

    print('\n3. Email, and both')
    TEXTS.clear(); EMAILS.clear()
    c.post('/team/broadcast', data={'message': 'By email', 'channel': 'email',
                                    'subject': 'Team note'}, follow_redirects=True)
    check(len(EMAILS) == 2 and not TEXTS, 'emailed both, texted nobody')
    check(EMAILS[0]['subject'] == 'Team note', 'with the subject she typed')

    print('\n4. An empty message is refused')
    TEXTS.clear()
    r = c.post('/team/broadcast', data={'message': '   ', 'channel': 'sms'}, follow_redirects=True)
    check(TEXTS == [], 'nothing sent')
    check('Write a message first' in r.get_data(as_text=True), 'and it says why')

    print('\n5. Asking the team for next week\'s availability')
    TEXTS.clear()
    r = c.post('/team/availability/ask', data={'week': '1'}, follow_redirects=True)
    check(len(TEXTS) == 2, 'both cleaners asked')
    monday = tm.week_start(offset=1)
    # Recipients come back ordered by name, so look them up by number rather
    # than assuming who is first.
    by_phone = {t[0]: t[1] for t in TEXTS}
    check(f'/availability/tok-laura/{monday.isoformat()}' in by_phone['+14079841405'],
          'each gets a personal link for that exact week')
    check('[ES]' in by_phone['+14079842222'], 'and Ana is asked in Spanish')
    check('tok-ana' in by_phone['+14079842222'], "with Ana's own link, not Laura's")

    print('\n6. The cleaner taps her days')
    page = c.get(f'/availability/tok-laura/{monday.isoformat()}').get_data(as_text=True)
    check('which days can you work' in page.lower(), 'she sees the question')
    check(monday.strftime('%A') in page, 'with each day listed')
    days = [(monday + timedelta(days=i)).isoformat() for i in range(7)]
    r = c.post(f'/availability/tok-laura/{monday.isoformat()}',
               data={'days': [days[0], days[2], days[4]],
                     f'note_{days[2]}': 'after 2pm'}, follow_redirects=True)
    check('Got it — thank you' in r.get_data(as_text=True), 'and gets a thank-you')

    rows = Availability.query.filter_by(staff_id=laura.id).all()
    free = {a.day for a in rows if a.available}
    check(free == {days[0], days[2], days[4]}, f'her 3 days are stored (got {len(free)})')
    noted = [a for a in rows if a.note][0]
    check(noted.note == 'after 2pm', 'and her note came with it')

    print('\n7. The owner sees who she has')
    page = c.get('/team/availability?week=1').get_data(as_text=True)
    check('Laura Moreira' in page and 'Ana Ruiz' in page, 'both cleaners listed')
    check('Former Cleaner' not in page, 'the inactive one is not')
    check('no reply yet' in page, 'and it flags Ana has not answered')
    check("Still waiting on" in page and 'Ana Ruiz' in page, 'naming who she is waiting on')

    print('\n8. Changing her mind just updates it')
    c.post(f'/availability/tok-laura/{monday.isoformat()}',
           data={'days': [days[1]]}, follow_redirects=True)
    rows = Availability.query.filter_by(staff_id=laura.id).all()
    check(len(rows) == 7, 'still one row per day, not duplicates')
    free = {a.day for a in rows if a.available}
    check(free == {days[1]}, 'and only her new answer counts')

    print('\n9. Nudging only those who have not replied')
    TEXTS.clear()
    r = c.post('/team/availability/ask', data={'week': '1', 'only_waiting': '1'},
               follow_redirects=True)
    check(len(TEXTS) == 1, 'only Ana was nudged — Laura already answered')
    check('Asked 1 cleaner' in r.get_data(as_text=True), 'and it says so')

    print('\n10. A bad token gets nothing')
    check(c.get(f'/availability/not-a-real-token/{monday.isoformat()}').status_code == 404,
          'an unknown link 404s rather than leaking anything')

print('\n🎉 One message to everyone, and availability that comes back as data.')
