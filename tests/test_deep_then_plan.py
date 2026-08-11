"""The usual way a cleaning relationship starts: a deep clean first, then lighter
visits on a schedule. Different service, different price.

Turning the deep clean itself into a recurring job would repeat the deep clean,
at the deep-clean price, forever — so the ongoing plan is its own booking.
"""
import os, sys, tempfile
from datetime import date, timedelta
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/plan.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'ok')
notifications.send_email = lambda **k: (True, 'ok')

from app import create_app
from extensions import db
from models import Booking, Client, BusinessSetting

def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')

app = create_app()
with app.app_context():
    db.create_all()
    BusinessSetting.set('business_name', 'Test Cleaning Co'); db.session.commit()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    print('\n1. A deep clean is booked as a one-off')
    deep_day = (date.today() + timedelta(days=5)).isoformat()
    deep = Booking(service_type='deep', name='Tasha Bright', email='tasha@example.com',
                   phone='4075550166', address='12 Cedar Way', zip_code='32806',
                   bedrooms='3', bathrooms='2', price=395.0, frequency='one_time',
                   preferred_date=deep_day, preferred_time='9:00 AM', status='confirmed',
                   stripe_customer_id='cus_t', stripe_payment_method_id='pm_t')
    db.session.add(deep); db.session.commit()

    page = c.get(f'/bookings/{deep.id}').get_data(as_text=True)
    check('Ongoing Cleanings' in page, 'the booking page offers to set up ongoing cleanings')
    check('Every 2 weeks' in page, 'with fortnightly offered')
    check('Set up ongoing cleanings' in page, 'and a button to do it')

    print('\n2. The form opens with sensible numbers, not empty boxes')
    suggested_start = (date.fromisoformat(deep_day) + timedelta(days=14)).isoformat()
    check(suggested_start in page,
          f'the first ongoing visit is suggested two weeks after the deep clean ({suggested_start})')
    check('9:00 AM' in page, "and carries over the deep clean's arrival time")

    print('\n3. Setting it up creates a separate plan')
    r = c.post(f'/bookings/{deep.id}/start-plan', data={
        'frequency': 'biweekly', 'plan_service': 'standard',
        'start_date': suggested_start, 'plan_price': '165', 'plan_time': '9:00 AM'},
        follow_redirects=True)
    check(r.status_code == 200, 'the plan is created')

    db.session.expire_all()
    deep = Booking.query.get(deep.id)
    check(deep.service_type == 'deep', 'the deep clean is STILL a deep clean')
    check(deep.price == 395.0, 'still at $395')
    check(deep.frequency == 'one_time', 'and still a one-off — untouched')
    check(deep.recurring_group is None, 'it was not swept into the plan')

    plan = Booking.query.filter(Booking.recurring_group.isnot(None)).all()
    check(len(plan) >= 6, f'a fortnightly plan was generated ({len(plan)} visits)')
    check(all(b.service_type == 'standard' for b in plan),
          'every ongoing visit is a standard clean, not a deep clean')
    check(all(b.price == 165.0 for b in plan), 'every one at $165, not $395')
    check(all(b.name == 'Tasha Bright' for b in plan), 'all for the same customer')
    check(all(b.address == '12 Cedar Way' for b in plan), 'at the same address')

    print('\n4. Two weeks apart, starting when told')
    dates = sorted(b.preferred_date for b in plan)
    check(dates[0] == suggested_start, f'the first is {dates[0]}')
    gap = (date.fromisoformat(dates[1]) - date.fromisoformat(dates[0])).days
    check(gap == 14, f'and they are {gap} days apart')

    print('\n5. The customer is one client, not two')
    clients = Client.query.filter_by(email='tasha@example.com').all()
    check(len(clients) == 1, 'a single client record covers both')
    check(len(clients[0].bookings) >= 7, 'with the deep clean and every ongoing visit on it')

    print('\n6. A card on file carries across, so the plan can bill itself')
    check(all(b.stripe_customer_id == 'cus_t' for b in plan),
          'the saved card came over to every visit')

    print('\n7. The plan reads as one row, not seven customers')
    page = c.get('/bookings/').get_data(as_text=True)
    check(page.count('>Tasha Bright<') <= 2,
          'the list shows the deep clean and the plan — not every single visit')
    check('visits in this plan' in page, 'with the plan folded up behind a link')

print('\n🎉 Deep clean first, then a plan of its own — each at its own price.')
