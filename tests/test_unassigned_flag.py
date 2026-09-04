"""A job with nobody on it says so, on the list and on the calendar.

The bookings list flagged a job only when a cleaner had actively DECLINED. A job
nobody was ever offered looked exactly like a covered one — no badge, no colour,
nothing — so the jobs most likely to be forgotten were the ones the screen said
least about.
"""
import os, sys, tempfile
from datetime import date, timedelta
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/un.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import Booking, BookingCrew, Staff
app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


TOMORROW = (date.today() + timedelta(days=1)).isoformat()

with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'
    ana = Staff(name='Ana Ruiz', is_active=True)
    db.session.add(ana); db.session.commit()

    print('\n1. A job nobody was ever offered counts as needing a cleaner')
    naked = Booking(service_type='standard', name='Nobody On It', address='1 St',
                    price=200, status='confirmed', preferred_date=TOMORROW)
    covered = Booking(service_type='standard', name='Has A Cleaner', address='2 St',
                      price=200, status='confirmed', preferred_date=TOMORROW,
                      assigned_cleaner='Ana Ruiz')
    db.session.add_all([naked, covered]); db.session.commit()
    check(naked.needs_cleaner is True, 'the empty one is flagged')
    check(covered.needs_cleaner is False, 'the assigned one is not')

    print('\n2. Finished and cancelled work needs nobody')
    for st in ('completed', 'cancelled'):
        b = Booking(service_type='standard', name=f'Old {st}', address='3 St',
                    price=200, status=st, preferred_date='2026-01-01')
        db.session.add(b); db.session.commit()
        check(b.needs_cleaner is False, f'a {st} job is not chased')

    print('\n3. A crew job counts as covered only when somebody is on it')
    crewed = Booking(service_type='standard', name='Crew Job', address='4 St',
                     price=400, status='confirmed', preferred_date=TOMORROW)
    db.session.add(crewed); db.session.commit()
    db.session.add(BookingCrew(booking_id=crewed.id, staff_id=ana.id, pay_amount=120))
    db.session.commit()
    db.session.expire_all()
    check(Booking.query.get(crewed.id).needs_cleaner is False, 'a filled crew spot covers it')

    print('\n4. The bookings list says so, in words')
    page = c.get('/bookings/').get_data(as_text=True)
    check('Nobody assigned' in page, 'the badge appears on the list')

    print('\n5. And it is not only about a decline any more')
    declined = Booking(service_type='standard', name='They Said No', address='5 St',
                       price=200, status='confirmed', preferred_date=TOMORROW,
                       cleaner_response='declined')
    db.session.add(declined); db.session.commit()
    page = c.get('/bookings/').get_data(as_text=True)
    check('Cleaner declined' in page, 'a decline still reads as a decline')
    check('Nobody assigned' in page, 'and a never-offered job reads differently')

    print('\n6. The calendar marks it too')
    page = c.get('/bookings/calendar').get_data(as_text=True)
    check('NOBODY ASSIGNED' in page, 'the chip says so on hover')
    check('⚠️ Nobody On It' in page or '⚠️ Nobody' in page, 'and carries a warning in the chip itself')

print('\n🎉 A job with nobody on it is visible on the list and the calendar.')
