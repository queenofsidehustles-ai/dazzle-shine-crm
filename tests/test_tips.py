"""Tips: the customer's money passing through. They must reach the cleaner in
full and leave revenue, labor, margin and profit completely untouched."""
import os, sys, tempfile
from datetime import date, datetime
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/t.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: True
from app import create_app
from extensions import db
from models import Booking, BookingCrew, Staff, ContractorPayment
import finance
app = create_app()

# PLAN FOR THIS TEST. A fresh database starts on the free plan, which allows two
# cleaners and sends no texts -- correct for a brand-new signup, and not what
# this file is about. Say which plan is being exercised rather than leaving it
# to a default that will change again.
with app.app_context():
    from models import BusinessSetting as _BS
    from extensions import db as _db
    _BS.set('plan', 'scale')
    _BS.set('plan_status', 'active')
    _db.session.commit()
import entitlements as _ent
_ent._clear_cache()
import blueprints.payments as pay_bp
pay_bp._send_receipt = lambda *a, **k: None
pay_bp._alert_owner_paid = lambda *a, **k: None

def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')

AUG = (date(2026, 8, 1), date(2026, 8, 31))

with app.app_context():
    db.create_all()
    laura = Staff(name='Laura Moreira', email='l@x.com', is_active=True,
                  pay_type='percent', pay_rate=50)
    ana = Staff(name='Ana Ruiz', email='a@x.com', is_active=True,
                pay_type='percent', pay_rate=50)
    db.session.add_all([laura, ana]); db.session.commit()

    b = Booking(service_type='standard', name='Tipper', address='1 St', price=260,
                lead_fee=0, estimated_hours=3.0, labor_rate_applied=43,
                status='completed', preferred_date='2026-08-10',
                assigned_cleaner='Laura Moreira', tip_amount=25.0,
                paid_at=datetime(2026, 8, 10), paid_method='card')
    db.session.add(b); db.session.commit()

    print("\n1. The customer's tip is recorded, and nothing is allocated")
    check(b.tip_amount == 25.0, 'the $25 the customer gave is on the job')
    check(b.tip_fee == 0.72, 'the card fee is shown as information')
    check(b.tip_net == 24.28, '$24.28 actually landed')
    check(not hasattr(b, 'tip_for'), 'no automatic split exists any more')
    check(b.pay_for(laura) == 129.0, 'her job pay is untouched by any of it')

    print('\n2. The tip does NOT touch revenue or job economics')
    check(finance.revenue_between(*AUG) == 260.0, 'revenue is the $260 price')
    e = finance.job_economics(*AUG)
    check(e['rows'][0]['labor'] == 129.0, 'labor is $129')
    check(e['rows'][0]['labor_pct'] == 49.6, 'labor % unchanged')

    print('\n3. SHE types the share, and that is what gets paid')
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'
    r = c.post(f'/contractors/payroll/pay-job/{b.id}',
               data={'method': 'zelle', 'paid_on': '2026-08-10', 'tip': '12'},
               follow_redirects=True)
    db.session.expire_all()
    p = ContractorPayment.query.filter_by(booking_id=b.id).first()
    check(p.amount == 129.0, 'pay recorded as $129')
    check(p.tip_amount == 12.0, 'and the $12 SHE decided, not a computed split')
    check('$141.00' in r.get_data(as_text=True), 'she handed over $141.00 in total')

    print('\n4. Whatever she kept is hers, worked out from what happened')
    # CHANGED, deliberately: this used to expect $12.28, i.e. $25 collected
    # less the $0.72 card fee less the $12 handed over.
    #
    # The tip is charged on the same card as the job, so Stripe's cut of it is
    # already inside the ProcessingFee total that profit_and_loss subtracts as
    # `fees`. Taking an estimated 2.9% off here as well counted it twice and
    # understated profit on every tipped card job. This test never created a
    # ProcessingFee row, so its month had no real fee to collide with and the
    # double-count was invisible here.
    #
    # What she kept is what came in less what she handed out. The card's cut
    # appears once, in processing fees.
    pnl = finance.profit_and_loss(*AUG)
    check(pnl['tips']['collected'] == 25.0, '$25 collected')
    check(pnl['tips']['card_fee'] == 0.72,
          '$0.72 card fee — still reported, for the page to show')
    check(pnl['tips']['passed_on'] == 12.0, '$12 passed to Laura')
    check(pnl['tips']['owner_share'] == 13.0,
          f"$13.00 left over is hers (got ${pnl['tips']['owner_share']})")
    check(pnl['contractor_pay'] == 129.0, 'cleaner pay still excludes tips')

    print('\n5. Typing no tip pays no tip')
    b2 = Booking(service_type='standard', name='No Tip Given', address='9 St', price=200,
                 lead_fee=0, estimated_hours=2.0, labor_rate_applied=43,
                 status='completed', preferred_date='2026-08-11',
                 assigned_cleaner='Laura Moreira', tip_amount=40.0)
    db.session.add(b2); db.session.commit()
    c.post(f'/contractors/payroll/pay-job/{b2.id}',
           data={'method': 'cash', 'paid_on': '2026-08-11'}, follow_redirects=True)
    db.session.expire_all()
    p2 = ContractorPayment.query.filter_by(booking_id=b2.id).first()
    check(p2.tip_amount == 0, 'a blank tip box means no tip goes out')
    check(p2.amount == 86.0, 'and her pay is unaffected')

    print('\n6. The payroll row shows what the customer gave, and a box to type in')
    # The box lives on rows still to be paid — the ones above are already settled.
    b3 = Booking(service_type='standard', name='Still To Pay', address='7 St', price=300,
                 lead_fee=0, estimated_hours=3.0, labor_rate_applied=43,
                 status='completed', preferred_date='2026-08-12',
                 assigned_cleaner='Laura Moreira', tip_amount=45.0)
    db.session.add(b3); db.session.commit()
    page = c.get('/contractors/payroll?start=2026-08-01&end=2026-08-31').get_data(as_text=True)
    check('customer tipped' in page, 'it shows what the customer tipped')
    check('name="tip"' in page, 'with a box for her to type each share')

print('\n🎉 The CRM records the tip split she decides — it never decides one.')
