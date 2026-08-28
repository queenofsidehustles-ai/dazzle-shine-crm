"""What a recurring discount costs, and whether anything writes it down.

The Job Economics page exists to answer "what is discounting really costing
me". It answered $0.00, always -- because the pricing engine worked the
discount out, applied it to the price, and threw the figure away. The caller
stored the discounted total and left Booking.discount_amount at its default.

So an owner giving 15% off to every weekly customer could open the report built
to show her that, and read that she had discounted nothing.
"""
import os, sys, tempfile
from datetime import datetime, date
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/disc.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['ADMIN_USER'] = 'owner'
os.environ['ADMIN_PASS'] = 'pw-for-tests'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import Booking
import pricing
import finance

app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


with app.app_context():
    db.create_all()

    print('\n1. The pricing engine reports what it gave away')
    for freq, charged, given, pct in [('one_time', 260.0, 0.0, 0),
                                      ('monthly', 247.0, 13.0, 5),
                                      ('biweekly', 234.0, 26.0, 10),
                                      ('weekly', 221.0, 39.0, 15)]:
        j = pricing.calculate_job('standard', 3, 2, frequency=freq)
        check(j['list_price'] == 260.0, f'{freq}: list price is $260.00')
        check(j['client_price'] == charged, f'{freq}: charged ${charged:.2f}')
        check(j['discount_amount'] == given, f'{freq}: gave away ${given:.2f}')
        check(j['discount_pct'] == pct, f'{freq}: which is {pct}%')

    print('\n2. The discount survives extras and square footage')
    # The discount comes off the whole subtotal, so what was given away is
    # bigger on a bigger job -- and that is the number worth reporting.
    j = pricing.calculate_job('standard', 3, 2, sqft=2400,
                              extras='Inside oven', frequency='weekly')
    check(j['list_price'] == 385.0, 'a $385 job before the discount')
    check(j['client_price'] == 327.25, 'is charged $327.25')
    check(j['discount_amount'] == 57.75, 'so $57.75 was given away, not $39.00')

    print('\n3. Booking through the back office records it')
    c = app.test_client()
    c.post('/login', data={'username': 'owner', 'password': 'pw-for-tests'})
    r = c.post('/bookings/new', data={
        'name': 'Weekly Customer', 'email': 'weekly@example.com',
        'phone': '4075550123', 'address': '1 Repeat Lane',
        'service_type': 'standard', 'bedrooms': '3', 'bathrooms': '2',
        'frequency': 'weekly', 'preferred_date': '2026-04-10',
    }, follow_redirects=True)
    check(r.status_code == 200, 'the booking form accepts the job')
    b = Booking.query.filter_by(name='Weekly Customer').first()
    check(b is not None, 'and the job is created')
    check(b.discount_amount == 39.0,
          'with the $39.00 weekly discount written down, not zero')

    print('\n4. It is recorded even when she types the price herself')
    # Almost every job in this business is entered by hand. If the discount
    # were only captured on the auto-priced path, the report would still read
    # $0.00 for the owner it was built for.
    r = c.post('/bookings/new', data={
        'name': 'Typed By Hand', 'email': 'typed@example.com',
        'phone': '4075550124', 'address': '2 Manual Way',
        'service_type': 'standard', 'bedrooms': '3', 'bathrooms': '2',
        'frequency': 'biweekly', 'cleaning_price': '230',
        'preferred_date': '2026-04-11',
    }, follow_redirects=True)
    t = Booking.query.filter_by(name='Typed By Hand').first()
    check(t is not None, 'a hand-priced job is created')
    check(t.price == 230.0, 'at the price she typed')
    check(t.discount_amount == 26.0,
          'and still records the 10% the frequency gave away')

    print('\n5. A one-off job records no discount')
    r = c.post('/bookings/new', data={
        'name': 'One Off', 'email': 'once@example.com',
        'phone': '4075550125', 'address': '3 Single St',
        'service_type': 'standard', 'bedrooms': '3', 'bathrooms': '2',
        'frequency': 'one_time', 'preferred_date': '2026-04-12',
    }, follow_redirects=True)
    o = Booking.query.filter_by(name='One Off').first()
    check((o.discount_amount or 0) == 0.0, 'nothing given away, nothing recorded')

    print('\n6. Job Economics can finally answer the question it was built for')
    for b in Booking.query.all():
        b.status = 'completed'
        b.balance_collected = True
        b.balance_due = b.price
        b.paid_at = datetime(2026, 4, 15, 10, 0)
    db.session.commit()
    econ = finance.job_economics(date(2026, 4, 1), date(2026, 4, 30))
    check(econ['discount_total'] == 65.0,
          '$39.00 + $26.00 + nothing = $65.00 of discounting, where it used to say $0.00')
    row = next((r for r in econ['rows'] if r['discount'] == 39.0), None)
    check(row is not None, 'and the weekly job shows its own $39.00')
    check(row['baseline'] == row['price'] + 39.0,
          'against a baseline of what it would have cost at list')

print('\n\n✅ All discount-recording tests passed.\n')
