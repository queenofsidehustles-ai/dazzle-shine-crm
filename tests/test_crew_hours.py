"""The hours box saved nothing when you pressed the button beneath it.

"Work in this job" sits in the crew card, but the input belonged to the job-edit
form two cards above (`form="jobEditForm"`). Pressing Save pay — the button
directly under the field — submitted a form that did not contain the hours, so
they were dropped without a word and the box came back empty, still saying "no
estimate yet". The pay summary then showed the old percentage pot, which is a
different number from the one the hours would have produced.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/ch.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
outbox = []
notifications.send_sms = lambda phone, msg: (outbox.append(msg) or (True, 'stub'))
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import Booking, Staff
app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'
    for n, p in [('Elena K', '9374773090'), ('Tasha M', '4075550111')]:
        db.session.add(Staff(name=n, phone=p, is_active=True))
    b = Booking(service_type='deep', name='Karen Doyle', address='55 Oak', city='Orlando',
                price=245, preferred_date='2026-08-22', preferred_time='Morning',
                status='confirmed')
    db.session.add(b); db.session.commit()

    print('\n1. Save pay — the button under the hours box — saves the hours')
    c.post(f'/bookings/{b.id}/crew', follow_redirects=True,
           data={'estimated_hours': '3.46', 'crew_size': '2', 'owner_hours': ''})
    b = Booking.query.get(b.id)
    check(b.estimated_hours == 3.46, f'the hours stuck (got {b.estimated_hours})')
    check(b.crew_size == 2, 'and so did the two cleaners')
    check(b.labor_rate_applied, 'the hourly rate was stamped on the job')

    print('\n2. The pot is the hours, and it splits evenly')
    check(abs(b.labor_budget - round(3.46 * b.rate_applied, 2)) < 0.01,
          f'pot = 3.46 hrs × ${b.rate_applied:.0f} = ${b.labor_budget:.2f}')
    each = b.labor_budget / 2
    check(abs(each - 74.39) < 0.75, f'${each:.2f} each — the figure she was aiming at')
    check(b.hours_each() == 1.73, f'{b.hours_each()} hrs each')

    print('\n3. The page shows her that number, not the old 50% pot')
    html = c.get(f'/bookings/{b.id}').get_data(as_text=True)
    check(f'${each:.2f} each' in html, 'the per-cleaner figure is printed on the job')
    check('Pot to divide (job minus lead fee)' not in html,
          'and the price-based pot is gone now that hours decide the pay')
    check('No estimate yet' not in html, 'no longer claims there is no estimate')

    print('\n4. The team text quotes the same figure')
    outbox.clear()
    c.post(f'/bookings/{b.id}/broadcast', follow_redirects=True)
    check(outbox, 'the job went out to the team')
    msg = outbox[0]
    check('2 cleaners needed' in msg, 'it says two cleaners are needed')
    check(f'${each:.2f} each' in msg, f'and quotes ${each:.2f} each — the same number')
    # The hours drive the pay but are never quoted: this work is paid per job,
    # and an hourly figure in the offer invites clock-watching.
    check('hrs' not in msg and '/hr' not in msg, 'without putting a clock in front of them')
    check('2 spots left' in msg, 'and two spots to claim')

    print('\n5. Save Changes still saves them too — either button works')
    c.post(f'/bookings/{b.id}', follow_redirects=True,
           data={'status': 'confirmed', 'price': '245', 'estimated_hours': '6',
                 'owner_hours': '0'})
    b = Booking.query.get(b.id)
    check(b.estimated_hours == 6, 'the job-edit form saves the hours as well')

    print('\n6. Owner hours come out of the pot')
    c.post(f'/bookings/{b.id}/crew', follow_redirects=True,
           data={'estimated_hours': '6', 'owner_hours': '2', 'crew_size': '2'})
    b = Booking.query.get(b.id)
    check(b.payable_hours == 4, 'she works 2 of the 6, so 4 are paid')
    check(abs(b.labor_budget - round(4 * b.rate_applied, 2)) < 0.01,
          f'the pot is the 4 paid hours, not 6 (${b.labor_budget:.2f})')

    print('\n7. Clearing the box on purpose still works')
    c.post(f'/bookings/{b.id}/crew', follow_redirects=True,
           data={'estimated_hours': '', 'crew_size': '2'})
    b = Booking.query.get(b.id)
    check(b.estimated_hours is None, 'emptying the field clears the estimate')
    check(b.labor_budget is None, 'and the job falls back to the old percentage')

print('\n🎉 Crew hours checks passed.')
