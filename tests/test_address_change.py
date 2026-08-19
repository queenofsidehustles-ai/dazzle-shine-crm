"""A customer moves house and keeps her cleaning plan.

The address could not be edited anywhere — it was set once when the booking was
created and shown read-only ever after. Worse, every visit in a recurring series
holds its own copy of it, and the cleaner is texted the address of the visit she
claimed, so fixing one row would have sent somebody to the old house for the
rest of the plan.
"""
import os, sys, tempfile
from datetime import date, timedelta
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/ad.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import Booking, Client
import recurring
app = create_app()

OLD = '8472 Sperry St'
NEW = '104 Lakeshore Dr'


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


def iso(n):
    return (date.today() + timedelta(days=n)).isoformat()


with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n1. A client with a biweekly plan at the old address')
    client = Client(name='Miriam Uhle', email='m@example.com', phone='4075551212',
                    address=OLD, city='Orlando', zip_code='32827')
    db.session.add(client); db.session.commit()
    seed = Booking(client_id=client.id, service_type='standard', name='Miriam Uhle',
                   email='m@example.com', address=OLD, city='Orlando', zip_code='32827',
                   frequency='biweekly', preferred_date=iso(3), price=265.50,
                   status='confirmed')
    db.session.add(seed); db.session.commit()
    made = recurring.generate_series(seed)
    check(made >= 4, f'{made + 1} visits on the calendar')

    done = Booking(client_id=client.id, service_type='moveout', name='Miriam Uhle',
                   address=OLD, city='Orlando', zip_code='32827', price=350.50,
                   preferred_date=iso(-30), status='completed',
                   recurring_group=seed.recurring_group)
    db.session.add(done); db.session.commit()
    group = seed.recurring_group

    print('\n2. The booking page offers the move, and counts what would follow')
    html = c.get(f'/bookings/{seed.id}').get_data(as_text=True)
    check('change the address' in html, 'there is somewhere to change it')
    upcoming = Booking.query.filter(Booking.recurring_group == group,
                                    Booking.id != seed.id,
                                    Booking.preferred_date > date.today().isoformat(),
                                    Booking.status.in_(('pending', 'confirmed'))).count()
    check(f'<strong>{upcoming}</strong>' in html,
          f'and says how many visits move with it ({upcoming})')

    print('\n3. Moving her takes the whole plan along')
    c.post(f'/bookings/{seed.id}/address', follow_redirects=True, data={
        'address': NEW, 'city': 'Winter Park', 'zip_code': '32789',
        'apply_series': '1', 'apply_client': '1'})
    seed = Booking.query.get(seed.id)
    check(seed.address == NEW and seed.city == 'Winter Park', 'this visit moved')
    future = Booking.query.filter(Booking.recurring_group == group,
                                  Booking.preferred_date > date.today().isoformat()).all()
    check(future and all(b.address == NEW for b in future),
          f'and so did all {len(future)} upcoming visits')
    check(all(b.zip_code == '32789' for b in future), 'city and ZIP came with it')

    print('\n4. Work already done keeps the address it happened at')
    done = Booking.query.get(done.id)
    check(done.address == OLD,
          'the completed move-out still says where it was cleaned')

    print('\n5. Her client record follows her')
    client = Client.query.get(client.id)
    check(client.address == NEW and client.zip_code == '32789',
          'the Clients page shows the new house')

    print('\n6. The change is written into the job history')
    check(OLD in (seed.internal_notes or '') and NEW in (seed.internal_notes or ''),
          'internal notes record what it was and what it became')

    print('\n7. Leaving the box unticked moves only this one job')
    solo = Booking(client_id=client.id, service_type='standard', name='Solo Job',
                   address=OLD, city='Orlando', preferred_date=iso(10),
                   status='confirmed', recurring_group=group)
    db.session.add(solo); db.session.commit()
    c.post(f'/bookings/{solo.id}/address', follow_redirects=True,
           data={'address': '9 Nowhere Ln', 'city': 'Orlando'})
    solo = Booking.query.get(solo.id)
    others = Booking.query.filter(Booking.recurring_group == group,
                                  Booking.id != solo.id,
                                  Booking.preferred_date > date.today().isoformat()).all()
    check(solo.address == '9 Nowhere Ln', 'the one job moved')
    check(all(b.address == NEW for b in others), 'and nothing else was touched')

    print('\n8. An empty address is refused rather than wiping the record')
    c.post(f'/bookings/{solo.id}/address', follow_redirects=True, data={'address': '  '})
    solo = Booking.query.get(solo.id)
    check(solo.address == '9 Nowhere Ln', 'the address she had is still there')

print('\n🎉 Address-change checks passed.')
