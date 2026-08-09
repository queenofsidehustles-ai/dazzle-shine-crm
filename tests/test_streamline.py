"""The floor should measure what she actually pays, and a lead fee shouldn't
have to be typed twice."""
import os, sys, tempfile
from datetime import date
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/st.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import Booking, BookingCrew, Staff, Expense
import finance
app = create_app()

def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')

with app.app_context():
    db.create_all()
    laura = Staff(name='Laura Moreira', email='l@x.com', is_active=True,
                  pay_type='percent', pay_rate=50)
    db.session.add(laura); db.session.commit()

    print("\n1. Ashley G's job — the warning that was wrong")
    b = Booking(service_type='deep', name='Ashley G', address='280 Ballow Dr',
                price=620, lead_fee=0, estimated_hours=10.25, labor_rate_applied=43,
                crew_size=1, status='confirmed', preferred_date='2026-08-05')
    db.session.add(b); db.session.commit()
    check(b.labor_budget == 440.75, 'the hours are worth $440.75')
    check(b.below_floor_by is not None, 'with nobody assigned it flags — fair, nothing is committed yet')

    db.session.add(BookingCrew(booking_id=b.id, staff_id=laura.id, pay_amount=160))
    db.session.commit(); db.session.expire_all()
    b = Booking.query.get(b.id)
    check(b.committed_labor == 160.0, 'once Laura is on it at $160, THAT is the cost')
    check(b.floor_price == 266.67, f'floor is $160 ÷ 60% = $266.67 (got ${b.floor_price})')
    check(b.below_floor_by is None, '$620 is comfortably above it — the red warning is gone')
    check(b.labor_percent == 25.8, f'labor reads 25.8% of price, not 71% (got {b.labor_percent}%)')

    print('\n2. A job that IS genuinely underpriced still flags')
    bad = Booking(service_type='standard', name='Too Cheap', address='1 St', price=180,
                  lead_fee=0, estimated_hours=3.0, labor_rate_applied=43,
                  crew_size=1, status='confirmed', preferred_date='2026-08-06')
    db.session.add(bad); db.session.commit()
    db.session.add(BookingCrew(booking_id=bad.id, staff_id=laura.id, pay_amount=129))
    db.session.commit(); db.session.expire_all()
    bad = Booking.query.get(bad.id)
    check(bad.committed_labor == 129.0, 'paying $129')
    check(bad.floor_price == 215.0, 'floor $215')
    check(bad.below_floor_by == 35.0, 'still flagged $35 under — a real problem still shows')

    print('\n3. The report agrees with the booking page')
    e = finance.job_economics(date(2026, 8, 1), date(2026, 8, 31))
    row = [r for r in e['rows'] if r['booking'].name == 'Ashley G'][0]
    check(row['labor'] == 160.0, 'Job Economics costs Ashley at the $160 actually paid')
    check(row['margin'] == 460.0, f"margin $460, not $179 (got ${row['margin']})")
    check(len(e['below_floor']) == 1, 'only the genuinely underpriced job is listed')

    print('\n4. Lead fee → ad expense, in one click')
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'
    b.lead_fee = 60.0
    db.session.commit()
    page = c.get(f'/bookings/{b.id}').get_data(as_text=True)
    check('Did you actually pay $60.00 for this lead?' in page, 'the booking offers to log it')

    check(Expense.query.count() == 0, 'no expense yet')
    r = c.post(f'/bookings/{b.id}/log-ad-cost',
               data={'category': 'ads_google', 'amount': '60'}, follow_redirects=True)
    check(Expense.query.count() == 1, 'one click created the expense')
    ex = Expense.query.first()
    check(ex.amount == 60.0 and ex.category == 'ads_google', '$60 under Google leads')
    check(ex.booking_id == b.id, 'linked to the job it bought')
    check('Ashley G' in (ex.note or ''), f'and says which lead: "{ex.note}"')

    print('\n5. It cannot be logged twice')
    r = c.post(f'/bookings/{b.id}/log-ad-cost', data={'amount': '60'}, follow_redirects=True)
    check(Expense.query.count() == 1, 'a second attempt creates nothing')
    check('already in your expenses' in r.get_data(as_text=True), 'and says so')
    page = c.get(f'/bookings/{b.id}').get_data(as_text=True)
    check('$60.00 of ad cost logged for this job' in page, 'the booking now shows it as done')
    check('Did you actually pay' not in page, 'and stops asking')

    print('\n6. It reaches the P&L as real ad spend')
    b.paid_at = __import__('datetime').datetime(2026, 8, 5)
    db.session.commit()
    p = finance.profit_and_loss(date(2026, 8, 1), date(2026, 8, 31))
    ads = [cat for cat in p['categories'] if cat['key'] == 'ads_google']
    check(ads and ads[0]['amount'] == 60.0, 'shows as $60 of Google advertising')
    check(p['ad_spend'] == 60.0, 'and counts in the lead-fee-vs-ad-spend check')
    check(p['lead_fees_collected'] == 60.0, 'against the $60 lead fee collected')
    check(p['lead_fee_delta'] == 0.0, 'which nets to zero — the fee exactly covered the ad')

print('\n🎉 The floor measures real money, and the lead fee is entered once.')
