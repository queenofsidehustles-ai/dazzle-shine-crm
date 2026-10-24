"""Every fact on the booking page is edited in one place.

The money card carried a form with Status, Total price, Lead fee, Confirmed
Date, Confirmed Time, Assigned Cleaner, Hours Worked, two notes boxes and a
review tickbox under one "Save Changes". So the date could be edited from three
places, the cleaner from two (one of them by name, which payroll can't trust),
and the price from two. The page now has one home for each, and the save route
leaves alone whatever a form didn't send -- or saving a note wipes the price.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/oneplace.db'
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
from models import Booking, Staff

app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


with app.app_context():
    db.create_all()
    b = Booking(name='Pat Customer', phone='4075550100', address='9 Elm St',
                service_type='standard', bedrooms='3', bathrooms='2',
                preferred_date='2026-11-12', preferred_time='9:00 AM',
                price=240, lead_fee=25, status='confirmed', skip_review=True,
                access_notes='Gate 1234')
    db.session.add(b); db.session.commit()
    c = app.test_client()
    c.post('/login', data={'username': 'owner', 'password': 'pw-for-tests'})
    html = c.get(f'/bookings/{b.id}').get_data(as_text=True)

    print('\n1. One home for each fact')
    check(html.count('name="preferred_date"') == 1, 'the date is edited in one place')
    check(html.count('name="price"') == 1, 'the price is edited in one place')
    check('<select name="assigned_cleaner"' not in html,
          'there is no second, name-based cleaner picker')
    check('Confirmed Date' not in html and 'Requested Date' not in html,
          'and no two labels for the same date')
    check('Save Changes' not in html, 'the catch-all "Save Changes" form is gone')
    money = html[html.index('data-card-key="money"'):html.index('data-card-key="talk"')]
    check('name="status"' not in money and 'access_notes' not in money,
          'the money card holds no status or notes')
    check(money.index('Customer pays') < money.index('id="numbersBox"'),
          'it opens with what the customer pays; the owner\'s numbers are folded below')
    extras = html[html.index('data-card-key="extras"'):]
    check('Delete Booking' in extras and 'Delete Booking' not in money,
          'Delete sits in "Less often", not one tap from Save')

    print('\n2. Saving status and notes touches nothing else')
    c.post(f'/bookings/{b.id}', data={'status': 'confirmed', 'access_notes': 'Gate 9999',
                                      'internal_notes': 'Pays cash', 'skip_review_shown': '1',
                                      'skip_review': 'on'})
    b = Booking.query.get(b.id)
    check(b.price == 240 and b.lead_fee == 25, 'the price and lead fee are untouched')
    check(b.preferred_date == '2026-11-12', 'and so is the date')
    check(b.access_notes == 'Gate 9999' and b.internal_notes == 'Pays cash', 'the notes saved')
    c.post(f'/bookings/{b.id}', data={'skip_review_shown': '1'})
    check(Booking.query.get(b.id).skip_review is False, 'an unticked review box means "ask them"')

    print('\n3. Saving the price touches nothing else')
    c.post(f'/bookings/{b.id}', data={'price': '260', 'lead_fee': '25'})
    b = Booking.query.get(b.id)
    check(b.price == 260, 'the price saved')
    check(b.access_notes == 'Gate 9999' and b.status == 'confirmed', 'the notes and status did not move')
    c.post(f'/bookings/{b.id}', data={'price': '260'})
    check(Booking.query.get(b.id).skip_review is False, 'a form without the review box leaves it alone')

    print('\n4. A job filled the old way, by name, can still change hands')
    db.session.add(Staff(name='Rosa Cleaner', phone='4075559999', is_active=True))
    b.assigned_cleaner = 'Old Name'; db.session.commit()
    html = c.get(f'/bookings/{b.id}').get_data(as_text=True)
    check('Take off this job' in html, 'the name shows with a way to take it off')
    c.post(f'/bookings/{b.id}', data={'assigned_cleaner': ''})
    b = Booking.query.get(b.id)
    check(not b.assigned_cleaner and b.price == 260, 'taking it off clears the name and nothing else')
    check('Nobody yet' in c.get(f'/bookings/{b.id}').get_data(as_text=True),
          'and the page says nobody is on it')

    print('\n5. A phone booking\'s private note is private on the booking page')
    c.post('/bookings/new', data={'name': 'Phone Note', 'phone': '4075550111',
                                  'service_type': 'standard', 'bedrooms': '2', 'bathrooms': '1',
                                  'internal_notes': 'Prefers mornings'})
    n = Booking.query.filter_by(name='Phone Note').first()
    check(n.internal_notes == 'Prefers mornings' and not n.notes,
          'it lands in private notes, not "Customer Notes"')

print('\nAll checks passed.')
