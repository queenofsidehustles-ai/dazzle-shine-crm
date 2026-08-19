"""Pay set by hand, and a job offer that doesn't start a stopwatch.

There is one company hourly rate. It cannot be right for both a move-out and a
discounted biweekly maintenance clean, so a job whose real pay was $75 each was
being valued at 6 × $43 = $258 — 105% of a $245 price — and the floor warning
shouted about money that was never going to be spent. The team text also quoted
"hrs × $/hr", which invites clock-watching on work that is paid per job.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/fp.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
outbox = []
notifications.send_sms = lambda phone, msg: (outbox.append(msg) or (True, 'stub'))
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import Booking, Staff, BookingCrew
app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'
    elena = Staff(name='Elena K', phone='9374773090', is_active=True)
    tasha = Staff(name='Tasha M', phone='4075550111', is_active=True)
    db.session.add_all([elena, tasha])
    b = Booking(service_type='standard', name='Karen Doyle', address='55 Oak', city='Orlando',
                bedrooms='3', bathrooms='3.5', sqft=2100, price=245, frequency='biweekly',
                preferred_date='2026-08-22', preferred_time='Morning', status='confirmed')
    db.session.add(b); db.session.commit()

    print('\n1. The real job: 6 person-hours, 2 cleaners, $245 biweekly')
    c.post(f'/bookings/{b.id}/crew', follow_redirects=True,
           data={'estimated_hours': '6', 'crew_size': '2', 'owner_hours': ''})
    b = Booking.query.get(b.id)
    check(b.estimated_hours == 6, 'the hours are what she says they are')
    check(abs(b.labor_budget - 258) < 0.01, 'the hourly rate values that at $258')
    check(b.labor_percent > 100, f'which is {b.labor_percent}% of the price — flagged, correctly')

    print('\n2. Setting the pay makes it the fact, not the hours')
    c.post(f'/bookings/{b.id}/crew', follow_redirects=True,
           data={'estimated_hours': '6', 'crew_size': '2', 'crew_pay_each': '75'})
    b = Booking.query.get(b.id)
    check(b.crew_pay_each == 75, 'pay is $75 each')
    check(b.estimated_hours == 6, 'and the hours are still there for planning')
    check(b.default_crew_pay(elena) == 75, 'that is what a cleaner is offered')
    check(b.committed_labor == 150, 'the job commits $150, not $258')
    check(b.labor_percent == 61.2, f'labor reads {b.labor_percent}% of the price, not 105%')

    print('\n3. The floor warning now measures money she will actually spend')
    # Measured against the hours it claimed this job was $185 under its floor.
    # Against the $150 she is really paying it is $5 — which is true, and worth
    # knowing: $75 each on $245 is a whisker over her own 60% cap.
    check(b.floor_price == 250, f'floor is $150 ÷ 60% = ${b.floor_price:.2f}, not $430')
    check(b.below_floor_by == 5.0,
          f'${b.below_floor_by:.2f} under, where the hours claimed $185')

    print('\n4. The team text shows the house and a flat figure — no clock')
    outbox.clear()
    c.post(f'/bookings/{b.id}/broadcast', follow_redirects=True)
    check(outbox, 'the offer went out')
    msg = outbox[0]
    print('   ', msg.split(' 👉')[0])
    check('$75.00 each, flat for the job' in msg, 'it quotes $75.00 each, flat')
    check('3 bd / 3.5 ba' in msg and '2,100 sq ft' in msg, 'and describes the house')
    check('/hr' not in msg and 'hrs' not in msg, 'with no hourly rate and no hours')
    check('2 cleaners needed' in msg and '2 spots left' in msg, 'two cleaners, two spots')

    print('\n5. The claim page they land on says the same thing')
    b = Booking.query.get(b.id)
    html = c.get(f'/claim/{b.claim_token}/{elena.agreement_token}').get_data(as_text=True)
    check('$75.00' in html, 'the pay is $75.00')
    check('flat for the job' in html, 'described as flat for the job')
    check('hours ×' not in html, 'and the hours-times-rate line is gone')
    check('2,100 sq ft' in html, 'the house size is there instead')

    print('\n6. Claiming pays the figure that was advertised')
    c.post(f'/claim/{b.claim_token}/{elena.agreement_token}/claim', follow_redirects=True)
    c.post(f'/claim/{b.claim_token}/{tasha.agreement_token}/claim', follow_redirects=True)
    b = Booking.query.get(b.id)
    rows = BookingCrew.query.filter_by(booking_id=b.id).all()
    check(len(rows) == 2, 'both cleaners took a spot')
    check(all(r.pay_amount == 75 for r in rows), 'each is down for the $75 they were promised')
    check(b.crew_allocated == 150, 'the job has $150 committed')
    check(not b.open_for_claim, 'and the board closed itself')

    print('\n7. Clearing the pay hands it back to the hours')
    c.post(f'/bookings/{b.id}/crew', follow_redirects=True,
           data={'estimated_hours': '6', 'crew_size': '2', 'crew_pay_each': ''})
    b = Booking.query.get(b.id)
    check(b.crew_pay_each is None, 'the set pay is cleared')
    check(abs(b.labor_budget - 258) < 0.01, 'the hours decide again')

    print('\n8. A job with no set pay is untouched by any of this')
    other = Booking(service_type='moveout', name='Other Job', address='1 Elm',
                    price=400, bedrooms='4', bathrooms='2', status='confirmed')
    db.session.add(other); db.session.commit()
    c.post(f'/bookings/{other.id}/crew', follow_redirects=True,
           data={'estimated_hours': '5', 'crew_size': '1'})
    other = Booking.query.get(other.id)
    check(other.crew_pay_each is None, 'no pay set')
    check(other.default_crew_pay(elena) == 215, 'it still pays 5 hrs × $43 = $215')

print('\n🎉 Flat crew pay checks passed.')
