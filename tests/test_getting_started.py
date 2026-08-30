"""A new business being told what to do next, and being left alone once it is.

The configuration checklist that already existed is the right list and the wrong
first screen: somebody who signed up two minutes ago does not know what a Stripe
key is for, and eight equally-weighted items with no order is a shape people
close the tab on.

So this is about a different question. Has the software done its job once? A
business is only really using a CRM when a real job is on the calendar with a
real cleaner assigned to it, and that milestone -- not signups, not logins -- is
the number worth watching.

The two ways to get this wrong are opposite. Say nothing, and a new owner sits
on an empty dashboard wondering what they bought. Keep nagging after they are
working, and it becomes furniture they learn to ignore.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/gs.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['ADMIN_USER'] = 'owner'
os.environ['ADMIN_PASS'] = 'pw-for-the-test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import BusinessSetting, Staff, Client, Booking, BookingCrew
import onboarding

app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


def client():
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['role'] = 'owner'
    return c


with app.app_context():
    db.create_all()

print('\n1. A brand-new business is told one thing to do')
with app.app_context():
    p = onboarding.progress()
check(p['done'] == 0 and p['percent'] == 0, 'nothing done yet')
check(p['activated'] is False, 'and not activated')
check(p['next']['key'] == 'business', 'the first thing asked for is the business name')
# Counted from the journey rather than typed in. Adding a step is a product
# decision, not a regression, and this assertion existed to check that a fresh
# account has nothing done -- not to freeze the number at five.
with app.app_context():
    _total = len(onboarding.journey())
check(len([s for s in p['steps'] if not s['done']]) == _total,
      f'all {_total} steps are outstanding on a brand-new account')
check(_total >= 5, f'and the journey has not been quietly gutted ({_total} steps)')

c = client()
r = c.get('/settings/getting-started')
check(r.status_code == 200, 'the getting-started page loads')
check(b'Next' in r.data, 'and shows a single next action')
check(b'0%' in r.data or b'done' in r.data, 'with progress on it')

print('\n2. The dashboard says the same thing, without being asked')
r = c.get('/')
check(b'Getting started' in r.data, 'a new business sees it on the dashboard')
check(b'Tell us about your business' in r.data, 'naming the next step')

print('\n3. Each step done moves it along, in order')
# Read the order from the journey rather than restating it. What is being
# checked is that finishing a step advances to the *next* one, not that the
# list has a particular length -- adding a step is a product decision.
with app.app_context():
    expected = [s['key'] for s in onboarding.journey()]
    for i, key in enumerate(expected):
        p = onboarding.progress()
        check(p['next']['key'] == key,
              f'step {i + 1} of {len(expected)} asks for {key!r}')
        # Do that step the way a real owner would.
        if key == 'business':
            BusinessSetting.set('business_name', 'Sparkle Cleaning')
        elif key == 'pricing':
            BusinessSetting.set('pricing_reviewed', '1')
        elif key == 'booking_page':
            # Marked when somebody actually opens the page, not by clicking a
            # button that says "done".
            BusinessSetting.set('booking_page_seen', '1')
        elif key == 'team':
            db.session.add(Staff(name='Maria', is_active=True))
        elif key == 'client':
            db.session.add(Client(name='Mrs Johnson', email='j@x.test'))
        elif key == 'job':
            b = Booking(service_type='deep', name='Thursday deep clean',
                        status='confirmed', price=280.0)
            db.session.add(b)
            db.session.commit()
            db.session.add(BookingCrew(booking_id=b.id, staff_id=1, pay_amount=129.0))
        db.session.commit()

print('\n4. A job with nobody on it is not the finish line')
# Booking something and never assigning it is exactly the state a business gets
# stuck in, and calling that "done" would hide the one step that matters.
with app.app_context():
    BookingCrew.query.delete()
    db.session.commit()
    p = onboarding.progress()
check(p['activated'] is False, 'an unassigned job does not count as activated')
check(p['next']['key'] == 'job', 'and the remaining step is still the job')
with app.app_context():
    _n = len(onboarding.journey())
check(p['done'] == _n - 1,
      f'every step but the last is done ({p["done"]} of {_n})')
check(p['percent'] == round((_n - 1) / _n * 100),
      f'and the percentage matches ({p["percent"]}%)')

print('\n5. Assigning it is the moment it counts')
with app.app_context():
    b = Booking.query.first()
    db.session.add(BookingCrew(booking_id=b.id, staff_id=1, pay_amount=129.0))
    db.session.commit()
    p = onboarding.progress()
check(p['activated'] is True, 'a job with a cleaner on it activates the business')
check(p['percent'] == 100, '100%')
check(p['next'] is None, 'and there is nothing left to tell them to do')

print('\n6. And then it gets out of the way')
c = client()
r = c.get('/')
check(b'Getting started' not in r.data,
      'the dashboard banner disappears by itself — nothing to dismiss')
r = c.get('/settings/getting-started')
check(b'up and running' in r.data,
      'and the page itself says so rather than showing an empty list')

print('\n7. The older single-cleaner field counts too')
# Jobs created before crews existed name the cleaner on the booking instead.
# An established business must not be told to go and do its first job.
with app.app_context():
    BookingCrew.query.delete()
    b = Booking.query.first()
    b.assigned_cleaner = 'Maria'
    db.session.commit()
    p = onboarding.progress()
check(p['activated'] is True,
      'a job assigned the old way still counts as activated')

print('\n8. Nothing here can take a page down')
with app.app_context():
    import models as m
    real = m.Booking

    class Broken:
        @property
        def query(self):
            raise RuntimeError('database unreachable')

    m.Booking = Broken()
    try:
        c2 = client()
        r = c2.get('/settings/business')
        ok = r.status_code == 200
    finally:
        m.Booking = real
check(ok, 'a page still renders when the progress check cannot run')

print('\n\n✅ All getting-started tests passed.\n')
