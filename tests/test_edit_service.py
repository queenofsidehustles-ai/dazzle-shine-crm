"""What was booked can be corrected without cancelling the job.

Service, size, add-ons, how often it repeats and when it was asked for were all
fixed at the moment a booking was created. A customer who said two bedrooms and
meant three could only be fixed by cancelling and re-keying the job, which
loses its history, its notes and its place in a recurring plan.

The part worth protecting is the money. Every one of these fields feeds the
quote, so saving a change must not re-price work the customer has already been
told the cost of — least of all a job with a deposit against it.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/svc.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
from models import Booking
from pricing import calculate_price
app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


def svc(**over):
    d = {'service_type': 'moveout', 'bedrooms': '2', 'bathrooms': '1',
         'frequency': 'one_time', 'sqft': '', 'preferred_date': '',
         'preferred_time': '8:30-9:30 AM'}
    d.update(over)
    return d


with app.app_context():
    db.create_all()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'

    b = Booking(service_type='moveout', name='Duffy Tyler', email='duffy@tyler.com',
                address='3320 Lila drive', bedrooms='2', bathrooms='1',
                price=290.0, preferred_time='8:30-9:30 AM', status='confirmed')
    db.session.add(b); db.session.commit()
    bid = b.id

    print('\n1. The card offers a way to correct what was booked')
    page = c.get(f'/bookings/{bid}').get_data(as_text=True)
    check('Correct what was booked' in page, 'the edit form is on the page')
    check('Inside oven' in page, 'with this business\'s add-ons listed')

    print('\n2. A corrected bedroom count saves — and the price does NOT move')
    c.post(f'/bookings/{bid}/service', data=svc(bedrooms='3', bathrooms='2'),
           follow_redirects=True)
    db.session.expire_all()
    b = Booking.query.get(bid)
    check(b.bedrooms == '3' and b.bathrooms == '2', 'the size was corrected')
    check(b.price == 290.0, 'the price the customer was quoted is untouched')
    check('Service details corrected' in (b.internal_notes or ''), 'and it is written down')

    print('\n3. Re-pricing happens only when she asks for it')
    expected = round(calculate_price(service_type='moveout', bedrooms='3', bathrooms='2',
                                     extras='', frequency='one_time', sqft=None), 2)
    c.post(f'/bookings/{bid}/service', data=svc(bedrooms='3', bathrooms='2', reprice='1'),
           follow_redirects=True)
    db.session.expire_all()
    b = Booking.query.get(bid)
    check(b.price == expected, f'the price moved to the real quote (${expected:.2f})')
    check('Price $290.00' in (b.internal_notes or ''), 'the old price is recorded')

    print('\n4. Add-ons save, and only ones this business prices')
    c.post(f'/bookings/{bid}/service', data=svc(
        bedrooms='3', bathrooms='2', extras=['Inside oven', 'Laundry', 'Gold plating']),
        follow_redirects=True)
    db.session.expire_all()
    b = Booking.query.get(bid)
    check('Inside oven' in b.extras and 'Laundry' in b.extras, 'the real add-ons stuck')
    check('Gold plating' not in b.extras, 'an invented one was dropped, not priced')

    print('\n5. An add-on raises what the job quotes')
    priced = round(calculate_price(service_type='moveout', bedrooms='3', bathrooms='2',
                                   extras='Inside oven,Laundry', frequency='one_time',
                                   sqft=None), 2)
    check(priced > expected, 'the quote with add-ons is higher than without')

    print('\n6. A service that does not exist is refused')
    c.post(f'/bookings/{bid}/service', data=svc(service_type='gold_service'),
           follow_redirects=True)
    db.session.expire_all()
    check(Booking.query.get(bid).service_type == 'moveout', 'the booking kept its real service')

    print('\n7. Date, time and how it repeats are editable')
    c.post(f'/bookings/{bid}/service', data=svc(
        bedrooms='3', bathrooms='2', extras=['Inside oven', 'Laundry'],
        preferred_date='2026-09-14', preferred_time='1:00 PM', frequency='biweekly'),
        follow_redirects=True)
    db.session.expire_all()
    b = Booking.query.get(bid)
    check(b.preferred_date == '2026-09-14', 'the date was corrected')
    check(b.preferred_time == '1:00 PM', 'and the time')
    check(b.frequency == 'biweekly', 'and it now repeats fortnightly')

    print('\n8. A job with a deposit against it is warned about, not silently re-priced')
    d = Booking(service_type='standard', name='Paid Up', address='1 St', bedrooms='2',
                bathrooms='1', price=200.0, deposit_paid=True, deposit_amount_paid=50.0)
    db.session.add(d); db.session.commit()
    page = c.get(f'/bookings/{d.id}').get_data(as_text=True)
    check('already paid against the old price' in page,
          'the form says so, and points at the flow that tells the customer')
    c.post(f'/bookings/{d.id}/service',
           data=svc(service_type='standard', bedrooms='4', bathrooms='2'),
           follow_redirects=True)
    db.session.expire_all()
    check(Booking.query.get(d.id).price == 200.0, 'and her price did not move on its own')

    print('\n9. The balance owed keeps up with a price that did move')
    c.post(f'/bookings/{d.id}/service',
           data=svc(service_type='standard', bedrooms='4', bathrooms='2', reprice='1'),
           follow_redirects=True)
    db.session.expire_all()
    d = Booking.query.get(d.id)
    check(d.balance_due == round(d.price - 50.0, 2),
          'balance = new price less the deposit actually paid')

print('\n🎉 What was booked is correctable, and no price moves without being asked.')
