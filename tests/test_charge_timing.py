"""Nobody's card should be charged before somebody is due to arrive.

A single morning run only ever suited whoever was booked at that hour — a 1pm
customer charged at 9am is still being charged four hours before anyone knocks.
Charging now follows each booking's own appointment time, in the business's own
timezone rather than the server's.
"""
import os, sys, tempfile
from datetime import datetime, timezone, timedelta
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/timing.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['REMINDER_API_KEY'] = 'cron-key'
os.environ['STRIPE_SECRET_KEY'] = 'sk_' + 'test_notareal000004242'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'ok')
notifications.send_email = lambda **k: (True, 'ok')

from app import create_app
from extensions import db
from models import Booking, BusinessSetting
import scheduling

def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')

app = create_app()

CHARGED = []
import payment_service
payment_service.charge_balance = lambda b: (CHARGED.append(b.id), (True, ''))[1]
payment_service.autocharge = lambda b: (CHARGED.append(b.id), (True, ''))[1]

with app.app_context():
    db.create_all()
    BusinessSetting.set('business_name', 'Test Cleaning Co')
    BusinessSetting.set('timezone', 'America/New_York')
    BusinessSetting.set('charge_hour', '9')
    db.session.commit()

    print('\n1. The business timezone, not the server\'s')
    tz = scheduling.business_timezone()
    server = datetime.now(timezone.utc)
    local = server.astimezone(tz)
    check(str(tz) == 'America/New_York', 'the CRM knows where the business is')
    check(local.utcoffset() != timedelta(0), 'and that it is not on UTC')
    check(scheduling.local_today() == local.date(),
          f"'today' is the local date ({local.date()}), not the server's ({server.date()})")

    print('\n2. Free-text arrival times are read the way people write them')
    for text, expected in [('10:00 AM', (10, 0)), ('10am', (10, 0)), ('1:00 PM', (13, 0)),
                           ('2pm', (14, 0)), ('14:30', (14, 30)), ('morning', (9, 0)),
                           ('afternoon', (13, 0)), ('noon', (12, 0)),
                           ('between 9 and 11', (9, 0)), ('between 1 and 3', (13, 0))]:
        got = scheduling.parse_time(text)
        check(got == expected, f'{text!r} → {expected[0]}:{expected[1]:02d}')
    check(scheduling.parse_time('whenever') is None, "'whenever' is not guessed at")
    check(scheduling.parse_time('') is None, 'and neither is a blank')

    print('\n3. A job is not due before its own appointment time')
    today = scheduling.local_today().isoformat()
    def job(name, time_text):
        b = Booking(service_type='standard', name=name, address='1 St', price=200,
                    preferred_date=today, preferred_time=time_text, status='confirmed',
                    stripe_customer_id='cus_x', stripe_payment_method_id='pm_x')
        db.session.add(b); db.session.commit()
        return b

    morning, afternoon = job('Morning Job', '9:00 AM'), job('Afternoon Job', '1:00 PM')
    at_8 = datetime(2026, 8, 10, 8, 0, tzinfo=tz)
    at_10 = datetime(2026, 8, 10, 10, 0, tzinfo=tz)
    at_14 = datetime(2026, 8, 10, 14, 0, tzinfo=tz)
    # Line the bookings up with the day being tested.
    for b in (morning, afternoon):
        b.preferred_date = '2026-08-10'
    db.session.commit()

    check(not scheduling.due_for_charge(morning, at_8), '8am: the 9am job is not charged yet')
    check(not scheduling.due_for_charge(afternoon, at_8), '8am: nor the 1pm job')
    check(scheduling.due_for_charge(morning, at_10), '10am: the 9am job is now due')
    check(not scheduling.due_for_charge(afternoon, at_10),
          '10am: the 1pm job STILL waits — this is the whole point')
    check(scheduling.due_for_charge(afternoon, at_14), '2pm: the 1pm job is due')

    print('\n4. Yesterday and tomorrow are never swept up')
    tomorrow = job('Tomorrow', '9:00 AM')
    tomorrow.preferred_date = '2026-08-11'
    yesterday = job('Yesterday', '9:00 AM')
    yesterday.preferred_date = '2026-08-09'
    db.session.commit()
    check(not scheduling.due_for_charge(tomorrow, at_14), "tomorrow's job is not charged today")
    check(not scheduling.due_for_charge(yesterday, at_14), "nor is yesterday's")

    print('\n5. A booking with no readable time uses the fallback hour')
    vague = job('No Time Given', '')
    vague.preferred_date = '2026-08-10'
    db.session.commit()
    check(not scheduling.due_for_charge(vague, at_8), 'not at 8am')
    check(scheduling.due_for_charge(vague, at_10), 'but yes at 10am, past the 9am fallback')
    BusinessSetting.set('charge_hour', '11'); db.session.commit()
    check(not scheduling.due_for_charge(vague, at_10),
          'and the fallback hour is hers to change — now 11am, so 10am is too early')
    BusinessSetting.set('charge_hour', '9'); db.session.commit()

    print('\n6. The cron only charges what is actually due')
    for b in Booking.query.all():
        db.session.delete(b)
    db.session.commit()
    now_local = scheduling.local_now()
    early = Booking(service_type='standard', name='Later Today', address='2 St', price=150,
                    preferred_date=now_local.date().isoformat(), preferred_time='11:59 PM',
                    status='confirmed', stripe_customer_id='cus_a', stripe_payment_method_id='pm_a')
    due = Booking(service_type='standard', name='Already Started', address='3 St', price=150,
                  preferred_date=now_local.date().isoformat(), preferred_time='12:01 AM',
                  status='confirmed', stripe_customer_id='cus_b', stripe_payment_method_id='pm_b')
    db.session.add_all([early, due]); db.session.commit()

    CHARGED.clear()
    c = app.test_client()
    res = c.post('/api/charge-balances?api_key=cron-key')
    body = res.get_json()
    check(res.status_code == 200, 'the cron runs')
    check(due.id in CHARGED, 'the job whose time has passed was charged')
    check(early.id not in CHARGED, 'the late-evening job was NOT charged yet')
    waiting = [w['name'] for w in body.get('waiting_for_their_appointment', [])]
    check('Later Today' in waiting, 'and it is reported as waiting, not as failed')
    check(any('11:59 PM' in (w.get('due_at') or '')
              for w in body['waiting_for_their_appointment']),
          'with the time it will charge at')

print('\n🎉 Cards are charged when the appointment starts — never before you turn up.')
