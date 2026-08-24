"""The day-before reminder, and the one bad row that silenced all of them.

Every visit a recurring series generates has balance_due unset. Formatting None
with :.2f raises, the request 500'd, and because the whole run was one try the
first such booking on the calendar cost everyone else their reminder too. From
outside it looked like the reminders had simply never been built: no error the
owner could see, no texts, nothing in the Sent log to explain it.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/rem.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['REMINDER_API_KEY'] = 'cron-secret'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
texts, emails = [], []
notifications.send_sms = lambda phone, msg: (texts.append((phone, msg)) or (True, 'stub'))
notifications.send_triggered_email = lambda **k: (emails.append(k) or True)
notifications.send_email = lambda *a, **k: (True, 'stub')

import scheduling
from app import create_app
from extensions import db
from models import Booking, BusinessSetting, CronRun

app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


def tomorrow():
    return (scheduling.local_today() + timedelta(days=1)).isoformat()


with app.app_context():
    db.create_all()
    BusinessSetting.set('phone', '(689) 999-0194')
    db.session.commit()

client = app.test_client()
AUTH = {'X-Api-Key': 'cron-secret'}


print('\n1. A recurring visit has no balance, and that used to be fatal')
with app.app_context():
    db.session.add(Booking(name='Recurring Rosa', phone='4075550199', email='rosa@example.com',
                           service_type='standard', bedrooms='3', bathrooms='2',
                           preferred_date=tomorrow(), preferred_time='10:00 AM',
                           address='9 Palm St', city='Orlando', status='confirmed',
                           balance_due=None, frequency='biweekly'))
    db.session.commit()
r = client.post('/api/reminders', headers=AUTH)
check(r.status_code == 200, 'the run completes instead of returning a 500')
check(r.get_json()['reminders_sent'] == 1, 'and the customer is reminded')
check('$0.00' not in texts[-1][1] and 'None' not in texts[-1][1],
      'with no balance line, rather than a confusing "Balance due: $0.00"')


print('\n2. One unsendable booking does not cost everyone else theirs')
with app.app_context():
    Booking.query.delete()
    db.session.commit()
    # A row with no name and no phone sits between two ordinary ones.
    for name, phone in [('Ada First', '4075550001'), (None, None), ('Zoe Last', '4075550003')]:
        db.session.add(Booking(name=name, phone=phone, email='x@example.com',
                               service_type='standard', bedrooms='2', bathrooms='1',
                               preferred_date=tomorrow(), preferred_time='9:00 AM',
                               address='1 Oak', city='Orlando', status='confirmed',
                               balance_due=None))
    db.session.commit()
texts.clear()
r = client.post('/api/reminders', headers=AUTH)
body = r.get_json()
check(r.status_code == 200, 'the run still completes')
sent_to = [t[0] for t in texts]
check('4075550001' in sent_to and '4075550003' in sent_to,
      'the bookings either side of the bad one are both reminded')


print('\n3. Nobody is reminded twice')
before = len(texts)
client.post('/api/reminders', headers=AUTH)
client.post('/api/reminders', headers=AUTH)
check(len(texts) == before, 'two more runs send nothing — the guard holds')
check(client.post('/api/reminders', headers=AUTH).get_json()['reminders_sent'] == 0,
      'and it reports honestly that it had nothing to do')


print('\n4. The text says something a person can act on')
with app.app_context():
    Booking.query.delete()
    db.session.commit()
    db.session.add(Booking(name='Sara Yamin', phone='4075550288', email='s@example.com',
                           service_type='deep', bedrooms='3', bathrooms='3',
                           preferred_date=tomorrow(), preferred_time='8:30 AM',
                           address='1382 Swinton Ct', city='Sanford', status='confirmed',
                           balance_due=245.0))
    db.session.commit()
texts.clear()
emails.clear()
client.post('/api/reminders', headers=AUTH)
msg = texts[-1][1]
check('{phone}' not in msg, 'no unreplaced {phone} placeholder reaches the customer')
check('(689) 999-0194' in msg, 'the real number is in it')
check('$245.00' in msg, 'and the balance they actually owe')
check(len(emails) == 1 and emails[0]['trigger'] == 'booking_reminder_24h',
      'the email goes out alongside the text')


print('\n5. A business with no phone number set does not say "Call ."')
with app.app_context():
    Booking.query.delete()
    BusinessSetting.set('phone', '')
    db.session.add(Booking(name='Wendy Chan', phone='4075550111', email='w@example.com',
                           service_type='standard', bedrooms='1', bathrooms='1',
                           preferred_date=tomorrow(), preferred_time='2:00 PM',
                           address='4 Elm', city='Orlando', status='confirmed', balance_due=0))
    db.session.commit()
texts.clear()
client.post('/api/reminders', headers=AUTH)
check('Call .' not in texts[-1][1] and '{phone}' not in texts[-1][1],
      'the sentence is dropped rather than left dangling')


print('\n6. The run is recorded, so the Automations page can tell')
with app.app_context():
    runs = CronRun.query.filter_by(job='reminders').all()
    check(len(runs) >= 1, 'every call writes a CronRun row')
    check(all(r.ok for r in runs[-2:]), 'a clean run is recorded as ok')

    import automations
    row = next(r for r in automations.overview() if r['key'] == 'reminders')
    check(row['state'] == 'ok', 'and the page reads it back as running')


print('\n7. Still nobody else can trigger it')
check(client.post('/api/reminders').status_code == 403, 'no key is refused')
check(client.post('/api/reminders', headers={'X-Api-Key': 'wrong'}).status_code == 403,
      'a wrong key is refused')


print('\n🎉 A recurring booking gets its reminder, and one bad row cannot silence the rest.')
