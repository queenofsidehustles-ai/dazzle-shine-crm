"""Whose money a tip is, and which month it belongs to.

A tip is the customer's money passing through. The only part that is income is
whatever the owner did not hand on. Three ways that went wrong, all of which
put somebody else's money into her reported profit or took her own out.
"""
import os, sys, tempfile
from datetime import datetime, date
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/tipacct.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import Booking, Staff, ContractorPayment
import finance

app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


with app.app_context():
    db.create_all()
    laura = Staff(name='Laura', pay_type='percent', pay_rate=50.0)
    db.session.add(laura)
    db.session.commit()

    print('\n1. A tip follows its own job across a month boundary')
    # The job is worked on the 31st and paid on the 2nd. Payouts are backdated
    # to the day of the job (contractors._paid_on), so the pass-through is
    # stamped January while the collection is stamped February. Comparing the
    # two by date used to report January at MINUS the whole tip and February at
    # PLUS the whole tip — a customer's $48.55 counted as the owner's income.
    b = Booking(service_type='standard', name='Month Boundary', status='completed',
                price=250.0, balance_due=250.0, balance_collected=True,
                tip_amount=50.0, preferred_date='2026-01-31',
                paid_at=datetime(2026, 2, 2, 10, 0))
    db.session.add(b)
    db.session.commit()
    db.session.add(ContractorPayment(
        staff_id=laura.id, booking_id=b.id, amount=129.0, tip_amount=48.55,
        status='paid', created_at=datetime(2026, 1, 31, 12, 0)))
    db.session.commit()

    jan = finance.tips_between(date(2026, 1, 1), date(2026, 1, 31))
    feb = finance.tips_between(date(2026, 2, 1), date(2026, 2, 28))
    check(jan['owner_share'] == 0.0,
          'January does not show a loss for a tip it never collected')
    check(jan['passed_on'] == 0.0,
          'and does not claim a pass-through with nothing to pass on')
    check(feb['collected'] == 50.0, 'February collected the $50')
    check(feb['passed_on'] == 48.55,
          'and counts the payout against it, whenever it was recorded')

    print('\n2. The card fee is taken off once, not twice')
    # The tip rides on the same card charge as the job, so Stripe's cut of it is
    # already inside the ProcessingFee total the P&L subtracts. Taking an
    # estimated 2.9% off again understated profit on every tipped card job.
    check(feb['owner_share'] == 1.45,
          'what she kept is $50.00 collected less $48.55 handed on = $1.45')
    check(feb['card_fee'] == 1.45,
          'the card fee is still reported, for the page to show')
    check(feb['owner_share'] == round(feb['collected'] - feb['passed_on'], 2),
          'and is not subtracted a second time')

    print('\n3. A tip never becomes revenue')
    feb_pnl = finance.profit_and_loss(date(2026, 2, 1), date(2026, 2, 28))
    jan_pnl = finance.profit_and_loss(date(2026, 1, 1), date(2026, 1, 31))
    check(feb_pnl['revenue'] == 250.0,
          'revenue is the job price — the $50 tip is not part of it')
    check(feb_pnl['contractor_pay'] == 0.0,
          'the $48.55 tip passed on is not counted as labour')

    print('\n4. Cost and revenue sit in the month the cash moved — that is cash basis')
    # This is NOT the bug that was fixed, and the difference matters.
    #
    # The cleaner was paid on the 31st of January; the customer paid on the 2nd
    # of February. On a cash-basis P&L the cost genuinely belongs to January and
    # the revenue genuinely belongs to February. Two months either side of a job
    # is how cash accounting looks, and it comes out right over the year.
    #
    # What was broken was different in kind: owner_share was computed as one
    # aggregate minus another aggregate scoped to a different set of records, so
    # it produced a figure that was not true in either month. A timing spread is
    # honest; an identity computed across mismatched sets is not.
    check(jan_pnl['contractor_pay'] == 129.0,
          'January carries the $129 labour, the month it was paid')
    check(jan_pnl['revenue'] == 0.0, 'and no revenue, because nothing was collected')
    check(jan_pnl['tips']['owner_share'] == 0.0,
          'and crucially, no phantom tip income or loss')
    check(feb_pnl['gross_profit'] == 250.0,
          'February gross is the $250 collected')
    check(feb_pnl['net_profit'] == 251.45,
          'and net is $251.45 — the job plus her $1.45 of the tip')

    print('\n5. Hours the owner works herself are not charged to the cleaner')
    # This is the figure used to judge whether somebody is underpaid, so
    # reading it low is the wrong way to be wrong.
    job = Booking(service_type='standard', name='Owner Helps', status='completed',
                  price=400.0, balance_due=400.0, balance_collected=True,
                  estimated_hours=6.0, owner_hours=2.0, labor_rate_applied=43.0,
                  assigned_cleaner='Laura', preferred_date='2026-03-10',
                  paid_at=datetime(2026, 3, 10, 10, 0))
    db.session.add(job)
    db.session.commit()
    check(job.payable_hours == 4.0, 'a 6-hour job the owner helps with for 2 pays 4')
    check(job.labor_budget == 172.0, 'so the pot is $172.00')

    econ = finance.job_economics(date(2026, 3, 1), date(2026, 3, 31))
    row = next((c for c in econ['by_cleaner'] if c['name'] == 'Laura'), None)
    check(row is not None, 'the cleaner appears in the per-cleaner figures')
    check(row['hours'] == 4.0, 'against 4 paid hours, not the 6 estimated')
    check(row['effective_hourly'] == 43.0,
          'so she reads at $43.00/hr — not the $28.67 that made her look underpaid')

    print('\n6. A crew job was already right, and stays right')
    from models import BookingCrew
    crew_job = Booking(service_type='standard', name='Two Up', status='completed',
                       price=500.0, balance_due=500.0, balance_collected=True,
                       estimated_hours=8.0, crew_size=2, labor_rate_applied=43.0,
                       preferred_date='2026-03-12',
                       paid_at=datetime(2026, 3, 12, 10, 0))
    db.session.add(crew_job)
    db.session.commit()
    mia = Staff(name='Mia', pay_type='percent', pay_rate=50.0)
    db.session.add(mia)
    db.session.commit()
    db.session.add_all([
        BookingCrew(booking_id=crew_job.id, staff_id=laura.id, pay_amount=172.0),
        BookingCrew(booking_id=crew_job.id, staff_id=mia.id, pay_amount=172.0),
    ])
    db.session.commit()
    econ = finance.job_economics(date(2026, 3, 1), date(2026, 3, 31))
    m = next((c for c in econ['by_cleaner'] if c['name'] == 'Mia'), None)
    check(m is not None and m['hours'] == 4.0,
          'each of two cleaners on an 8-hour job is credited 4 hours')
    check(m['effective_hourly'] == 43.0, 'and reads at $43.00/hr')

print('\n\n✅ All tip-accounting tests passed.\n')
