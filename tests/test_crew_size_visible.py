"""Two cleaners on one job, decided where the decision is made.

"How many cleaners are you paying?" spent a release folded inside the
"How this pay is worked out" disclosure, because it looked like arithmetic.
It is not. It decides how many spots the team offer advertises, and how the
pot divides per person -- an assignment decision with a pay consequence.

Worse, the assign form hid itself once every spot was filled. So a job set to
one cleaner, with one cleaner on it, had NO visible way to become a two-cleaner
job: the control that would have raised the headcount was inside a closed
disclosure, and the form that would have added the second person was gone.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/crewsize.db'
os.environ['SECRET_KEY'] = 'test-secret-key'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
texts = []
notifications.send_email = lambda **k: (True, 'ok')
notifications.send_sms = lambda to, body: (texts.append((to, body)), (True, 'ok'))[1]

from app import create_app
from extensions import db
from models import Booking, Staff

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, 'templates/admin/booking_detail.html'), encoding='utf-8').read()


def a_booking(**kw):
    b = Booking(service_type='deep', name='Big House Barbara', email='bh@example.com',
                phone='+17165550100', status='confirmed', price=430.0,
                preferred_date='2026-11-02', address='1 Oak St', city='Huntsville',
                zip_code='35801', bedrooms=5, bathrooms=3, estimated_hours=6.0, **kw)
    db.session.add(b)
    db.session.commit()
    return b


with app.app_context():
    db.create_all()
    maya = Staff(name='Maya Johnson', is_active=True,
                 email='maya@example.com', phone='+12565550111')
    trina = Staff(name='Trina Edwards', is_active=True,
                  email='trina@example.com', phone='+12565550112')
    db.session.add_all([maya, trina])
    db.session.commit()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n1. The headcount is on screen, not inside the pay disclosure')
    b = a_booking()
    page = c.get(f'/bookings/{b.id}').get_data(as_text=True)
    check('id="crewSize"' in page, 'the headcount control is on the page')
    disclosure = SRC[SRC.index('How this pay is worked out'):]
    check('name="crew_size"' not in disclosure[:disclosure.index('</details>')],
          'and it is NOT buried in "How this pay is worked out"')
    assign_form = SRC[SRC.index("url_for('bookings.assign'"):]
    check('name="crew_size"' in assign_form[:assign_form.index('</form>')],
          'it sits in the same form as "Assign to", where the decision is made')

    print('\n2. Two cleaners splits the pay and advertises two spots')
    texts.clear()
    c.post(f'/bookings/{b.id}/assign',
           data={'crew_size': '2', 'assign_to': 'team'}, follow_redirects=True)
    db.session.refresh(b)
    check(b.crew_size == 2, 'the job is set to 2 paid cleaners')
    check(b.is_crew_job is True, 'and reads as a crew job')
    check(b.spots_left == 2, 'with 2 spots open')
    offer = ' '.join(t[1] for t in texts)
    check('2 cleaners needed' in offer, f'the team offer says so: {offer[:60]}…')
    check('2 spots left' in offer, 'and how many spots are going')
    check('1 Oak St' not in offer, 'and still never the street address')

    print('\n3. Each of the two is paid a half share, not the whole pot')
    solo = a_booking()
    whole = solo.default_crew_pay(maya)
    b.crew_size = 2
    db.session.commit()
    half = b.default_crew_pay(maya)
    check(abs(half * 2 - whole) < 0.01,
          f'${half:.2f} each on a two-cleaner job vs ${whole:.2f} for one')

    print('\n4. A full job can still become a bigger one')
    b2 = a_booking()
    c.post(f'/bookings/{b2.id}/assign', data={'crew_size': '1',
           'assign_to': str(maya.id)}, follow_redirects=True)
    db.session.refresh(b2)
    check(b2.spots_left == 0, 'one cleaner on a one-cleaner job fills it')
    page = c.get(f'/bookings/{b2.id}').get_data(as_text=True)
    check('id="crewSize"' in page and 'id="assignTo"' in page,
          'the controls are STILL on screen — this was the trap')
    check('Add another cleaner' in page, 'and the label says what they now do')
    c.post(f'/bookings/{b2.id}/assign', data={'crew_size': '2',
           'assign_to': str(trina.id)}, follow_redirects=True)
    db.session.refresh(b2)
    check(b2.crew_size == 2 and len(b2.crew) == 2, 'so both cleaners get on the job')

    print('\n5. The headcount never drops below the people already on it')
    c.post(f'/bookings/{b2.id}/assign', data={'crew_size': '1', 'assign_to': ''},
           follow_redirects=True)
    db.session.refresh(b2)
    check(b2.crew_size == 2 and len(b2.crew) == 2,
          'asking for 1 with 2 assigned strands nobody')

    print('\n6. Changing only the headcount is allowed on its own')
    b3 = a_booking()
    r = c.post(f'/bookings/{b3.id}/assign', data={'crew_size': '3', 'assign_to': ''},
               follow_redirects=True)
    db.session.refresh(b3)
    check(b3.crew_size == 3, 'the headcount took')
    check('3 paid cleaners' in r.get_data(as_text=True), 'and it says so rather than scolding')

if failures:
    print(f'\n❌ {len(failures)} failed')
    for f in failures:
        print('  -', f)
    raise SystemExit(1)
print('\n🎉 One or two cleaners, decided in the open.')
