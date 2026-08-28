"""What every money figure in this business comes out as, today.

This suite is not here to argue that the arithmetic is right. It is here to
write down what it currently produces so that the next person to touch it —
including the change from floating-point money to decimal money — has to prove
that nothing moved. Every expected number below was worked out by hand from the
code, not copied from a passing run, so a mismatch means one of us is wrong and
both are worth looking at.

The rule when a test here fails: do not adjust the number to make it pass.
Either the change was intended, in which case say so in the commit, or a
cleaner's pay just moved without anybody deciding it should.

Figures assume the shipped defaults (pricing.py):
    labor rate            $43 per person-hour
    contractor split      50% (legacy, only for jobs with no estimated hours)
    tip card fee          2.9%
    lead fee              $25
    sqft surcharge        $30 per 200 sqft over standard
    frequency discounts   one-time 0%, monthly 5%, biweekly 10%, weekly 15%
"""
import os, sys, tempfile
from datetime import datetime, date, timedelta
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/money.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import Booking, BookingCrew, Staff, Client, ContractorPayment, Expense
import pricing
import finance

app = create_app()

FAILURES = []


def eq(got, want, what):
    """Assert and keep going, so one wrong figure does not hide the rest."""
    ok = got == want
    if not ok:
        FAILURES.append(f'{what}: got {got!r}, expected {want!r}')
    print(f'  {"✅" if ok else "❌"} {what}'
          f'{"" if ok else f"  → got {got!r}, expected {want!r}"}')


with app.app_context():
    db.create_all()

    # ---------------------------------------------------------------- pricing
    print('\n1. What the customer is quoted')

    # 3 bed / 2 bath standard: matrix price 260, multiplier 1.0.
    j = pricing.calculate_job('standard', 3, 2)
    eq(j['base_price'], 260.0, '3bd/2ba standard is $260')
    eq(j['client_price'], 260.0, 'with nothing added, that is the price')

    # Deep clean multiplies by 1.6:  260 × 1.6 = 416
    j = pricing.calculate_job('deep', 3, 2)
    eq(j['base_price'], 416.0, 'a deep clean is 1.6× → $416')

    # Move-out multiplies by 1.9:  260 × 1.9 = 494
    j = pricing.calculate_job('moveout', 3, 2)
    eq(j['base_price'], 494.0, 'a move-out is 1.9× → $494')

    print('\n2. Square footage is charged per completed 200 sq ft over standard')
    # 3 bed standard is 1800 sqft. 2400 − 1800 = 600 over → 3 increments × $30.
    j = pricing.calculate_job('standard', 3, 2, sqft=2400)
    eq(j['sqft_surcharge'], 90, '2,400 sq ft on a 3-bed adds $90')
    eq(j['client_price'], 350.0, 'so the job is $350')
    # 1999 is 199 over — not a full increment, so nothing is added.
    j = pricing.calculate_job('standard', 3, 2, sqft=1999)
    eq(j['sqft_surcharge'], 0, '199 sq ft over standard adds nothing')
    # Under standard never produces a credit.
    j = pricing.calculate_job('standard', 3, 2, sqft=900)
    eq(j['sqft_surcharge'], 0, 'a smaller-than-standard home is not discounted')

    print('\n3. Frequency discounts come off the whole subtotal')
    base = pricing.calculate_job('standard', 3, 2)['client_price']
    eq(base, 260.0, 'one-time is the undiscounted price')
    eq(pricing.calculate_job('standard', 3, 2, frequency='monthly')['client_price'],
       247.0, 'monthly is 5% off → $247.00')
    eq(pricing.calculate_job('standard', 3, 2, frequency='biweekly')['client_price'],
       234.0, 'biweekly is 10% off → $234.00')
    eq(pricing.calculate_job('standard', 3, 2, frequency='weekly')['client_price'],
       221.0, 'weekly is 15% off → $221.00')
    # The discount applies AFTER extras and sqft, not just to the base.
    j = pricing.calculate_job('standard', 3, 2, sqft=2400, frequency='weekly')
    eq(j['client_price'], 297.5, 'the discount comes off extras and sqft too')

    print('\n4. A discount must not reach the cleaner')
    # Pay is hours × rate. The customer's discount changes the price and
    # nothing else — this is the whole point of the labour-rate model.
    full = pricing.calculate_job('standard', 3, 2)
    cut = pricing.calculate_job('standard', 3, 2, frequency='weekly')
    eq(full['hours'], cut['hours'], 'a discounted job is the same amount of work')
    eq(full['contractor_earnings'], cut['contractor_earnings'],
       'so the cleaner earns the same on it')
    eq(full['contractor_earnings'], 129.0, '3 hours × $43 = $129')

    print('\n5. Add-ons pay for the extra time they take')
    # 'Inside oven' is $35 and half an hour.
    j = pricing.calculate_job('standard', 3, 2, extras='Inside oven')
    eq(j['extras_total'], 35, 'the oven adds $35 to the price')
    eq(j['client_price'], 295.0, 'so the job is $295')
    eq(j['extras_hours'], 0.5, 'and half an hour of work')
    eq(j['hours'], 3.5, 'taking the job to 3.5 hours')
    eq(j['contractor_earnings'], 150.5, '3.5 × $43 = $150.50 — the cleaner is paid for it')

    # Two add-ons: oven $35 / 0.5h and cabinets $30 / 1.0h.
    j = pricing.calculate_job('standard', 3, 2, extras='Inside oven, Inside cabinets')
    eq(j['extras_total'], 65, 'two add-ons total $65')
    eq(j['hours'], 4.5, 'and 1.5 extra hours')
    eq(j['contractor_earnings'], 193.5, '4.5 × $43 = $193.50')

    print('\n6. An add-on nobody recognises is silently free')
    # Worth knowing rather than assuming: a name that is not in the price list
    # adds nothing and is charged nothing, with no complaint. The booking form
    # only offers the five real names, so this is not currently reachable — but
    # if a name is ever renamed or typed by hand, the customer is not billed and
    # the cleaner is not paid, and nothing anywhere says so.
    j = pricing.calculate_job('standard', 3, 2, extras='oven')       # wrong case
    eq(j['extras_total'], 0, 'a misspelt add-on costs the customer nothing')
    eq(j['extras_hours'], 0, 'and pays the cleaner nothing for the work')

    # ------------------------------------------------------------- crew pay
    print('\n7. One cleaner, paid a percentage (the legacy rule)')
    percent = Staff(name='Percent Cleaner', pay_type='percent', pay_rate=50.0)
    hourly = Staff(name='Hourly Cleaner', pay_type='hourly', pay_rate=25.0)
    db.session.add_all([percent, hourly])
    db.session.commit()
    eq(percent.calc_pay(job_price=300, hours_worked=0), 150.0, '50% of a $300 job is $150')
    eq(percent.calc_pay(job_price=0, hours_worked=8), 0.0,
       'a percentage cleaner earns nothing from hours alone')
    eq(hourly.calc_pay(job_price=300, hours_worked=4), 100.0, '4 hours at $25 is $100')
    eq(hourly.calc_pay(job_price=300, hours_worked=0), 0.0,
       'an hourly cleaner earns nothing from the price alone')

    print('\n8. The labour budget is hours × rate, and ignores the price')
    b = Booking(service_type='standard', name='Budget Job', status='confirmed',
                price=400.0, estimated_hours=4.0, labor_rate_applied=43.0)
    db.session.add(b)
    db.session.commit()
    eq(b.labor_budget, 172.0, '4 hours at $43 is a $172 pot')

    b.price = 250.0                 # the customer got a big discount
    db.session.commit()
    eq(b.labor_budget, 172.0, 'discounting the customer does not shrink the pot')

    # Hours the owner works herself are not paid, so they come out of the pot
    # first: labor_budget is payable_hours x rate, not estimated_hours x rate.
    # This is the term that can silently halve what a crew is paid.
    solo_owner = Booking(service_type='standard', name='Owner Helps',
                         status='confirmed', price=400.0, estimated_hours=4.0,
                         owner_hours=2.0, labor_rate_applied=43.0)
    db.session.add(solo_owner)
    db.session.commit()
    eq(solo_owner.payable_hours, 2.0, 'the owner\u2019s 2 hours are not payable')
    eq(solo_owner.labor_budget, 86.0,
       'so a 4-hour job she half-works pays $86, not $172')

    print('\n9. Two cleaners split the pot, and the hourly rate is unchanged')
    eq(b.default_crew_pay(percent, size=1), 172.0, 'one cleaner takes all $172')
    eq(b.default_crew_pay(percent, size=2), 86.0, 'two take $86 each')
    eq(b.default_crew_pay(percent, size=4), 43.0, 'four take $43 each')
    # Two cleaners finish a 4-hour job in 2 hours each: $86 / 2h = $43/h. Same.
    eq(round(b.default_crew_pay(percent, size=2) / (4.0 / 2), 2), 43.0,
       'each is still earning $43 an hour')

    print('\n10. A job with no estimated hours falls back to the old percentage')
    old = Booking(service_type='standard', name='Legacy Job', status='confirmed',
                  price=300.0)
    db.session.add(old)
    db.session.commit()
    eq(old.labor_budget, None, 'no estimated hours means no budget')
    eq(old.pay_for(percent), 150.0, 'so a 50% cleaner still gets half the job')

    print('\n11. A typed-in figure beats every rule')
    b.crew_pay_each = 95.0
    db.session.commit()
    eq(b.default_crew_pay(percent, size=2), 95.0,
       'a flat rate set on the job wins over the split')

    print('\n12. What one cleaner is owed is answered in exactly one place')
    # pay_for() is what the offer text, My Day, payroll and the payout all read.
    # If they could disagree, a cleaner gets a different number in a text than
    # on her pay statement, and that is the argument nobody wins.
    b2 = Booking(service_type='standard', name='Crew Job', status='confirmed',
                 price=500.0, estimated_hours=6.0, labor_rate_applied=43.0)
    db.session.add(b2)
    db.session.commit()
    db.session.add_all([
        BookingCrew(booking_id=b2.id, staff_id=percent.id, pay_amount=129.0),
        BookingCrew(booking_id=b2.id, staff_id=hourly.id, pay_amount=129.0),
    ])
    db.session.commit()
    eq(b2.pay_for(percent), 129.0, 'the crew row is what she is owed')
    eq(b2.crew_allocated, 258.0, 'and the two of them account for $258')
    eq(b2.labor_budget, 258.0, 'which is exactly the pot — nothing unallocated')

    stranger = Staff(name='Not On This Job', pay_type='percent', pay_rate=50.0)
    db.session.add(stranger)
    db.session.commit()
    eq(b2.pay_for(stranger), 0.0,
       'somebody not on the job is owed nothing, not a default share')

    # ---------------------------------------------------------------- tips
    print('\n13. Tips: the card fee comes off, and nothing is auto-allocated')
    t = Booking(service_type='standard', name='Tipped Job', status='completed',
                price=200.0, tip_amount=50.0)
    db.session.add(t)
    db.session.commit()
    eq(t.tip_fee, 1.45, '2.9% of a $50 tip is $1.45')
    eq(t.tip_net, 48.55, 'leaving $48.55 that actually landed')

    t.tip_amount = 0
    db.session.commit()
    eq(t.tip_fee, 0.0, 'no tip, no fee')
    eq(t.tip_net, 0.0, 'and nothing to hand on')

    # ------------------------------------------------------------- the P&L
    print('\n14. Revenue is cash basis — the day the money landed')
    today = date.today()
    start, end = finance.month_bounds(today.year, today.month)

    paid = Booking(service_type='standard', name='Paid Job', status='completed',
                   price=300.0, balance_due=300.0, balance_collected=True,
                   paid_at=datetime.utcnow())
    unpaid = Booking(service_type='standard', name='Unpaid Job', status='completed',
                     price=999.0, balance_due=999.0, balance_collected=False)
    db.session.add_all([paid, unpaid])
    db.session.commit()

    rev = finance.revenue_between(start, end)
    eq(rev >= 300.0, True, 'a paid job counts towards revenue')
    eq(rev < 999.0, True, 'a completed but unpaid job does not')

    print('\n15. The P&L adds up, on a month with real money in it')
    # This section used to assert the identities against a month where every
    # term except revenue was zero, and computed each expected value with the
    # same expression finance.py uses -- so it could not fail. Now it builds a
    # month by hand and checks the totals against figures worked out on paper.
    #
    #   revenue        $300.00   one paid job
    #   cleaner pay    $129.00   one payout, status 'paid'
    #   expenses        $95.50   $60.00 supplies + $35.50 fuel
    #   commissions       $0.00
    #   card fees         $0.00   (no ProcessingFee rows synced)
    #
    #   gross  = 300.00 - 129.00 - 0.00            = 171.00
    #   net    = 171.00 - 0.00 - 95.50 + 0.00      =  75.50
    #   out    = 129.00 + 0.00 + 0.00 + 95.50      = 224.50
    #   margin = 75.50 / 300.00                    =  25.2%
    paid_staff = Staff(name='Paid Cleaner', pay_type='percent', pay_rate=50.0)
    db.session.add(paid_staff)
    db.session.commit()
    db.session.add(ContractorPayment(staff_id=paid_staff.id, booking_id=paid.id,
                                     amount=129.0, status='paid', method='zelle',
                                     created_at=datetime.utcnow()))
    db.session.add_all([
        Expense(date=today.isoformat(), category='supplies', amount=60.0,
                vendor='Supply Co'),
        Expense(date=today.isoformat(), category='fuel', amount=35.5,
                vendor='Gas Station'),
    ])
    db.session.commit()

    pnl = finance.profit_and_loss(start, end)
    eq(pnl['revenue'], 300.0, 'revenue is the one paid job')
    eq(pnl['contractor_pay'], 129.0, 'cleaner pay is the one payout')
    eq(pnl['expense_total'], 95.5, 'expenses total $95.50')
    eq(pnl['commissions'], 0.0, 'no commissions this month')
    eq(pnl['gross_profit'], 171.0, 'gross profit is $171.00')
    eq(pnl['net_profit'], 75.5, 'net profit is $75.50')
    eq(pnl['total_out'], 224.5, 'total out is $224.50')
    eq(pnl['margin'], 25.2, 'margin is 25.2%')

    print('\n16. A tip is the customer\u2019s money, not the business\u2019s')
    # The one thing that must never happen: a tip counted as revenue.
    eq(pnl['revenue'], 300.0,
       'a $50 tip on another job did not inflate revenue')
    eq(any(c['key'] == 'contractor_pay' for c in pnl['categories']), False,
       'cleaner pay is never also an expense row -- that would double-count it')

    print('\n17. Zero revenue does not divide by zero')
    far = date(2000, 1, 1)
    empty = finance.profit_and_loss(far, date(2000, 1, 31))
    eq(empty['revenue'], 0.0, 'a month with no money has no revenue')
    eq(empty['margin'], 0.0, 'and a margin of zero rather than an error')

    print('\n18. Every bedroom/bathroom combination has a price')
    # Regression. The matrix holds ten of the twenty combinations and an
    # unlisted one used to fall through to $0 while the cleaner was still owed
    # her hours. A 3-bed-1-bath is an ordinary house, the admin form offers
    # bedrooms and bathrooms as two independent dropdowns, and /api/lead emails
    # the quote out without anyone reading it.
    for beds in (1, 2, 3, 4, 5):
        for baths in (1, 2, 3, 4):
            j = pricing.calculate_job('standard', beds, baths)
            if j['client_price'] <= 0:
                eq(j['client_price'] > 0, True,
                   f'{beds}bd/{baths}ba must not quote at $0')
    eq(True, True, 'no combination of 1-5 beds and 1-4 baths quotes at $0')
    # An unlisted combination snaps to the nearest priced one, and never
    # downwards on a tie -- a house with fewer bathrooms is still a whole house.
    eq(pricing.calculate_job('standard', 3, 1)['client_price'], 260.0,
       '3bd/1ba prices as the nearest real combination, $260')
    eq(pricing.calculate_job('standard', 5, 2)['client_price'], 410.0,
       '5bd/2ba prices as 5bd/3ba, $410')
    # And the ten combinations that were always priced are untouched.
    for beds, baths, want in [(1, 1, 170.0), (2, 2, 225.0), (3, 2, 260.0),
                              (4, 3, 360.0), (5, 4, 455.0)]:
        eq(pricing.calculate_job('standard', beds, baths)['client_price'], want,
           f'{beds}bd/{baths}ba is still ${want:.0f}')

    print('\n19. The offer and the payout can never disagree')
    # Regression, and the one that moved real money. pay_for() skipped
    # crew_pay_each and returned the whole labor budget, while the texted offer
    # came from default_crew_pay(), which reads it. The payout writes a
    # ContractorPayment, so the wrong number was the one that got paid.
    owed = Staff(name='Owed Cleaner', pay_type='percent', pay_rate=50.0)
    db.session.add(owed)
    db.session.commit()
    for label, kw in [
        ('a flat rate on a solo job',
         dict(estimated_hours=6.0, labor_rate_applied=43.0, crew_size=1, crew_pay_each=150.0)),
        ('a flat rate on a crew job',
         dict(estimated_hours=6.0, labor_rate_applied=43.0, crew_size=2, crew_pay_each=95.0)),
        ('no flat rate, solo',
         dict(estimated_hours=4.0, labor_rate_applied=43.0, crew_size=1)),
        ('no flat rate, crew of three',
         dict(estimated_hours=6.0, labor_rate_applied=43.0, crew_size=3)),
        ('a legacy job with no estimated hours', dict()),
    ]:
        job = Booking(service_type='standard', name=label, status='confirmed',
                      price=300.0, **kw)
        db.session.add(job)
        db.session.commit()
        eq(job.pay_for(owed), job.default_crew_pay(owed),
           f'offer and payout agree on {label}')

    # The specific figures, so a future change has to say which one it moved.
    flat = Booking(service_type='standard', name='Flat', status='confirmed',
                   price=300.0, estimated_hours=6.0, labor_rate_applied=43.0,
                   crew_size=1, crew_pay_each=150.0)
    db.session.add(flat)
    db.session.commit()
    eq(flat.pay_for(owed), 150.0,
       'a hand-typed $150 is what she is paid, not the $258 budget')

    # ------------------------------------------------- floating point money
    print('\n20. Where floating-point money already goes wrong')
    # These are not bugs being introduced — they are the state of things today,
    # written down so the move to decimal money can prove what it changed.
    # Nothing here is asserted as CORRECT. It is asserted as CURRENT.
    cents = [Booking(service_type='standard', name=f'Penny {i}', status='completed',
                     price=0.1, balance_due=0.1, balance_collected=True,
                     paid_at=datetime.utcnow()) for i in range(10)]
    db.session.add_all(cents)
    db.session.commit()
    raw = sum(c.price for c in cents)
    eq(raw == 1.0, False,
       'ten times $0.10 does not equal $1.00 in floating point (this is the bug)')
    eq(round(raw, 2), 1.0, 'rounding to cents hides it — which is why it survives')

    third = Booking(service_type='standard', name='Thirds', status='confirmed',
                    price=100.0, estimated_hours=1.0, labor_rate_applied=43.0)
    db.session.add(third)
    db.session.commit()
    # $43 split three ways is $14.333…; each is rounded, so the crew is paid
    # $42.99 and a cent of the pot is never handed out.
    each = third.default_crew_pay(percent, size=3)
    eq(each, 14.33, 'a three-way split of $43 rounds each share to $14.33')
    eq(round(each * 3, 2), 42.99,
       'so $0.01 of the pot goes unallocated — small, and it compounds')

print()
if FAILURES:
    print(f'❌ {len(FAILURES)} money figure(s) are not what the code produces:\n')
    for f in FAILURES:
        print(f'   {f}')
    print('\nDo not edit the expected number to make this pass. Work out which '
          'of the two is wrong.\n')
    sys.exit(1)

print('✅ All money figures are as recorded.\n')
