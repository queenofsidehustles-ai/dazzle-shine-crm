"""Hours worked, per cleaner, from the clock — and what they are worth.

The clock already existed on a job's checklist. There is one checklist per
job, so a two-person job recorded a single shared clock: enough to know
somebody turned up, useless for paying anybody by the hour. A good number of
cleaning companies pay by the hour, and the marketing site said they could.

What this file holds still:

  * hours belong to a person, not to a job
  * "no record" and "worked nothing" stay different answers
  * a double-tap on a phone with a bad signal never opens two spells
  * the clock offers a figure and never applies one — money does not change
    itself between one look at a page and the next
  * pay that has already gone out cannot be rewritten
  * the page says, on the screen, that this is not payroll
"""
import os, sys, tempfile, secrets
from datetime import date, datetime, timedelta

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/ts.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
from models import Booking, Staff, BookingCrew, TimeEntry, BusinessSetting
import entitlements

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


MONDAY = date.today() - timedelta(days=date.today().weekday())


def setup():
    with app.app_context():
        db.drop_all()
        db.create_all()
        BusinessSetting.set('plan', 'scale')
        BusinessSetting.set('plan_status', 'active')
        maria = Staff(name='Maria Alvarez', email='m@x.com', phone='4075550101',
                      is_active=True, pay_type='hourly', pay_rate=22.0,
                      agreement_token=secrets.token_urlsafe(20))
        ana = Staff(name='Ana Reyes', email='a@x.com', phone='4075550102',
                    is_active=True, pay_type='hourly', pay_rate=19.5,
                    agreement_token=secrets.token_urlsafe(20))
        # Paid a percentage, so the clock is none of her business.
        jen = Staff(name='Jennifer Ward', email='j@x.com', phone='4075550103',
                    is_active=True, pay_type='percent', pay_rate=50.0,
                    agreement_token=secrets.token_urlsafe(20))
        db.session.add_all([maria, ana, jen])
        db.session.commit()
        b = Booking(name='Mrs Johnson', email='c@x.com', phone='4075559999',
                    address='118 Oak Street', city='Winter Park', zip_code='32789',
                    # Dated today, not Monday: My Day shows today onward, and a
                    # job in the past would not appear there at all. The
                    # timesheet reads clock times rather than the job's date,
                    # so this does not affect the week it lands in.
                    service_type='deep', preferred_date=date.today().isoformat(),
                    preferred_time='10:00 AM', status='confirmed',
                    price=280.0, estimated_hours=4.0)
        db.session.add(b)
        db.session.commit()
        crew = BookingCrew(booking_id=b.id, staff_id=maria.id, pay_amount=140.0)
        db.session.add(crew)
        db.session.commit()
        entitlements._clear_cache()
        return {'b': b.id, 'crew': crew.id, 'maria': maria.id, 'ana': ana.id,
                'jen': jen.id, 'mt': maria.agreement_token,
                'at': ana.agreement_token, 'jt': jen.agreement_token}


ids = setup()
c = app.test_client()


print('\n1. The clock belongs to a person, not to the job')
# The whole reason this exists. A checklist is per job; two people on one job
# shared one clock and could not be told apart.
r = c.get(f"/contractors/my-day/{ids['mt']}")
check(b'Clock in' in r.data, 'an hourly cleaner is offered a clock on her own day sheet')
r = c.get(f"/contractors/my-day/{ids['jt']}")
check(b'Clock in' not in r.data,
      'a cleaner on a percentage is not — a button that changes nothing '
      'teaches people to ignore buttons')


print('\n2. Clocking in and out')
c.post(f"/contractors/my-day/{ids['mt']}/clock-in/{ids['b']}", follow_redirects=True)
with app.app_context():
    e = TimeEntry.query.filter_by(staff_id=ids['maria']).first()
    check(e is not None and e.is_open, 'clocking in opens a spell')
r = c.get(f"/contractors/my-day/{ids['mt']}")
check(b'On the clock' in r.data, 'and the page says so')
check(b'Clock out' in r.data, 'and offers the way out')

print('\n3. A double tap does not buy an extra hour')
# One-bar signal, nothing happens, tap again. This must not become two spells.
c.post(f"/contractors/my-day/{ids['mt']}/clock-in/{ids['b']}")
c.post(f"/contractors/my-day/{ids['mt']}/clock-in/{ids['b']}")
with app.app_context():
    check(TimeEntry.query.filter_by(staff_id=ids['maria']).count() == 1,
          'still exactly one spell after three taps')

c.post(f"/contractors/my-day/{ids['mt']}/clock-out/{ids['b']}", follow_redirects=True)
with app.app_context():
    e = TimeEntry.query.filter_by(staff_id=ids['maria']).first()
    check(e.clock_out_at is not None, 'clocking out closes it')
c.post(f"/contractors/my-day/{ids['mt']}/clock-out/{ids['b']}")
with app.app_context():
    check(TimeEntry.query.filter_by(staff_id=ids['maria']).count() == 1,
          'and clocking out twice does not invent a second one')


print('\n4. "No record" is not the same as "worked nothing"')
# Only one of these two answers may be used to pay somebody.
ids = setup()
with app.app_context():
    maria = db.session.get(Staff, ids['maria'])
    b = db.session.get(Booking, ids['b'])
    check(maria.hours_on(b) is None, 'never clocked returns None, not 0')
    check(maria.hourly_pay_for(b) is None, 'and is worth nothing to work from')

    t0 = datetime.utcnow() - timedelta(hours=3, minutes=30)
    db.session.add(TimeEntry(booking_id=b.id, staff_id=maria.id,
                             clock_in_at=t0, clock_out_at=t0 + timedelta(hours=3, minutes=30)))
    db.session.commit()
    check(maria.hours_on(b) == 3.5, f'3h30m reads as 3.5 hours (got {maria.hours_on(b)})')
    check(maria.hourly_pay_for(b) == 77.0,
          f'worth $77.00 at $22/hr (got {maria.hourly_pay_for(b)})')


print('\n5. Two spells on one job add up')
with app.app_context():
    b = db.session.get(Booking, ids['b'])
    maria = db.session.get(Staff, ids['maria'])
    t1 = datetime.utcnow() - timedelta(hours=1)
    db.session.add(TimeEntry(booking_id=b.id, staff_id=maria.id,
                             clock_in_at=t1, clock_out_at=t1 + timedelta(minutes=30)))
    db.session.commit()
    check(maria.hours_on(b) == 4.0,
          f'somebody who left and came back is counted twice (got {maria.hours_on(b)})')


print('\n6. A clock-out before its clock-in is worth nothing, not less than nothing')
with app.app_context():
    t = datetime.utcnow()
    bad = TimeEntry(booking_id=ids['b'], staff_id=ids['ana'],
                    clock_in_at=t, clock_out_at=t - timedelta(hours=2))
    db.session.add(bad)
    db.session.commit()
    check(bad.hours == 0.0,
          f'a backwards entry reads 0, never negative (got {bad.hours})')
    ana = db.session.get(Staff, ids['ana'])
    check((ana.hourly_pay_for(db.session.get(Booking, ids['b'])) or 0) >= 0,
          'so nobody is ever owed a negative amount')


print('\n7. A cleaner on a percentage is untouched by any of it')
with app.app_context():
    jen = db.session.get(Staff, ids['jen'])
    b = db.session.get(Booking, ids['b'])
    check(jen.hourly_pay_for(b) is None,
          'hourly_pay_for returns None for somebody not paid by the hour')


print('\n8. The clock offers a figure. It never applies one.')
admin = app.test_client()
with admin.session_transaction() as sess:
    sess['logged_in'] = True
    sess['role'] = 'owner'
with app.app_context():
    before = float(db.session.get(BookingCrew, ids['crew']).pay_amount)
check(before == 140.0, f'pay starts at the ${before:.2f} the owner agreed')

page = admin.get(f"/bookings/{ids['b']}").data.decode('utf8', 'replace')
check('4.00 h actual' in page, 'the job page shows the clocked hours')
check('$88.00' in page, 'and what they are worth (4h at $22)')
check('Use this' in page, 'and offers to apply it')

with app.app_context():
    still = float(db.session.get(BookingCrew, ids['crew']).pay_amount)
check(still == 140.0,
      'but looking at the page has not changed anybody\'s pay')

admin.post(f"/bookings/{ids['b']}/crew/{ids['crew']}/use-clocked",
           follow_redirects=True)
with app.app_context():
    after = float(db.session.get(BookingCrew, ids['crew']).pay_amount)
check(after == 88.0, f'pressing it sets pay to ${after:.2f}')

page = admin.get(f"/bookings/{ids['b']}").data.decode('utf8', 'replace')
check('Use this' not in page, 'and the offer disappears once they agree')


print('\n9. Money already paid out is a record, not a draft')
with app.app_context():
    row = db.session.get(BookingCrew, ids['crew'])
    row.paid_at = datetime.utcnow()
    row.pay_amount = 99.0
    db.session.commit()
admin.post(f"/bookings/{ids['b']}/crew/{ids['crew']}/use-clocked",
           follow_redirects=True)
with app.app_context():
    check(float(db.session.get(BookingCrew, ids['crew']).pay_amount) == 99.0,
          'a paid-out figure cannot be rewritten from the clock')


print('\n10. The weekly timesheet')
ids = setup()
with app.app_context():
    for staff_key, day, hrs in (('maria', 0, 3.5), ('maria', 2, 2.0), ('ana', 0, 3.5)):
        t0 = datetime.combine(MONDAY + timedelta(days=day),
                              datetime.min.time()).replace(hour=9)
        db.session.add(TimeEntry(booking_id=ids['b'], staff_id=ids[staff_key],
                                 clock_in_at=t0, clock_out_at=t0 + timedelta(hours=hrs)))
    # Ana is still on the clock on Thursday.
    t0 = datetime.combine(MONDAY + timedelta(days=3), datetime.min.time()).replace(hour=9)
    db.session.add(TimeEntry(booking_id=ids['b'], staff_id=ids['ana'], clock_in_at=t0))
    db.session.commit()

r = admin.get('/contractors/timesheet')
sheet = r.data.decode('utf8', 'replace')
check(r.status_code == 200, f'the timesheet renders ({r.status_code})')
check('Maria Alvarez' in sheet and 'Ana Reyes' in sheet, 'both cleaners are listed')
check('5.50' in sheet, 'Maria totals 5.50 hours across two days')
check('3.50' in sheet, 'Ana totals 3.50')
check('9.00' in sheet, 'and the week totals 9.00')
check('still clocked in' in sheet,
      'somebody who never clocked out is flagged rather than counted')
check('Jennifer Ward' not in sheet,
      'the cleaner on a percentage does not appear — she has no hours')

print('\n11. It says on the screen that it is not payroll')
# A clause in a document nobody reads protects nobody. The moment this page
# starts looking like payroll, somebody assumes we did the parts we did not.
check('Hours, not payroll' in sheet, 'the page says so plainly')
for phrase in ('Overtime', 'vary by state', 'does not pay anybody',
               'contractor or an\n    employee'):
    flat = ' '.join(sheet.split())
    check(' '.join(phrase.split()) in flat, f'and mentions {phrase.split()[0].lower()}')


if failures:
    print(f'\n\n❌ {len(failures)} timesheet check(s) failed.\n')
    sys.exit(1)
print('\n\n✅ Hours are recorded per person, and only ever offered as pay.\n')
