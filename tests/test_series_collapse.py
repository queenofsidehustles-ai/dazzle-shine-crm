"""Scheduling a year of a monthly client's visits creates a dozen bookings in the
same instant. Both lists are ordered by when a booking was created, so one
client buried everything else that had happened.

A recurring plan should read as one line with a count, not as twelve customers.
"""
import os, sys, tempfile
from datetime import date, timedelta
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/series.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'ok')
notifications.send_email = lambda **k: (True, 'ok')

from app import create_app
from extensions import db
from models import Booking, BusinessSetting
import recurring

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

    print('\n1. Three ordinary customers, then one monthly plan')
    for name in ('Alice Warner', 'Ben Okafor', 'Chloe Ruiz'):
        db.session.add(Booking(service_type='standard', name=name, address='1 St',
                               price=180, status='confirmed',
                               preferred_date=(date.today() + timedelta(days=3)).isoformat()))
    db.session.commit()

    seed = Booking(service_type='standard', name='Nanrah Shibly', address='9 Oak Ave',
                   email='nanrah@example.com', price=200, frequency='monthly',
                   preferred_date=(date.today() + timedelta(days=30)).isoformat(),
                   preferred_time='10:00 AM', status='pending')
    db.session.add(seed); db.session.commit()
    made = recurring.generate_series(seed)
    total = Booking.query.filter_by(recurring_group=seed.recurring_group).count()
    check(made >= 10, f'the plan generated a year of visits ({made} added)')
    check(total >= 11, f'{total} visits now exist for that one client')
    check(Booking.query.count() >= 14, 'alongside the three ordinary bookings')

    print('\n2. The dashboard shows the plan once, not twelve times')
    page = c.get('/', follow_redirects=True).get_data(as_text=True)
    check(page.count('Nanrah Shibly') == 1,
          f'Nanrah appears exactly once (was {total} times)')
    for name in ('Alice Warner', 'Ben Okafor', 'Chloe Ruiz'):
        check(name in page, f'{name} is visible again')
    check('of ' + str(total) + ' visits' in page or 'visits' in page,
          'and the row says it stands for a whole plan')

    print('\n3. The bookings list does the same')
    page = c.get('/bookings/', follow_redirects=True).get_data(as_text=True)
    check(page.count('>Nanrah Shibly<') <= 1, 'one row for the plan')
    check('visits in this plan' in page, 'with a link to see the rest')
    for name in ('Alice Warner', 'Ben Okafor', 'Chloe Ruiz'):
        check(name in page, f'{name} still listed')

    print('\n4. The kept row is the next visit, not a random one')
    today = date.today().isoformat()
    kept = recurring.collapse(Booking.query.order_by(Booking.created_at.desc()).all())
    plan_row = [b for b in kept if b.recurring_group == seed.recurring_group][0]
    upcoming = sorted([b.preferred_date for b in
                       Booking.query.filter_by(recurring_group=seed.recurring_group).all()
                       if b.preferred_date >= today])
    check(plan_row.preferred_date == upcoming[0],
          f'it shows the soonest visit ({plan_row.preferred_date}), the one worth acting on')
    check(plan_row.series_total == total, f'and reports the true count ({plan_row.series_total})')

    print('\n5. Opening the plan shows every visit, earliest first')
    page = c.get(f'/bookings/?series={seed.recurring_group}').get_data(as_text=True)
    check(page.count('Nanrah Shibly') >= total, f'all {total} visits are listed')
    check('Alice Warner' not in page, 'and only that plan')
    check('Back to all bookings' in page, 'with a way back out')

    print('\n6. Nothing was hidden — the counts still add up')
    counts_page = c.get('/bookings/').get_data(as_text=True)
    check(f'>{Booking.query.count()}<' in counts_page or str(Booking.query.count()) in counts_page,
          f'the tab still counts every booking ({Booking.query.count()})')
    check(Booking.query.filter_by(recurring_group=seed.recurring_group).count() == total,
          'and no visit was deleted to tidy the list')

print('\n🎉 A recurring plan reads as one line, and nothing else gets buried.')
