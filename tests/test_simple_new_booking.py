"""The New Booking form is for whoever answers the phone.

It used to ask them for the company's ad cost, show them what the cleaner
earns, make them choose between three ways of collecting money, and send them
to the next page to find out who does the job. Somebody taking a call from a
new customer should be asked who, what and when -- and the owner's questions
answered once, on Pricing.

  * "How did they find you?" carries the lead fee for an ad customer, from
    Pricing, and records where the job came from (it used to say 'website').
  * Pricing decides whether a phone booking's confirmation asks for a deposit.
  * The booking page puts "who's cleaning this one?" on top until someone is.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/simple.db'
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
from models import Booking, PricingSetting, Staff
import blueprints.bookings as bookings_mod

app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


BASE = {'phone': '4075550123', 'address': '1 Call Lane', 'service_type': 'standard',
        'bedrooms': '3', 'bathrooms': '2', 'frequency': 'one_time',
        'cleaning_price': '200', 'preferred_date': '2026-11-10'}

with app.app_context():
    db.create_all()
    PricingSetting.set('lead_fee', 30)
    PricingSetting.set('deposit_amount', 50)
    db.session.commit()
    c = app.test_client()
    c.post('/login', data={'username': 'owner', 'password': 'pw-for-tests'})

    print('\n1. The form asks who, what and when -- not the owner\'s questions')
    html = c.get('/bookings/new').get_data(as_text=True)
    check('name="source"' in html, 'it asks how they found you')
    check('name="lead_fee"' not in html, 'it no longer asks for the ad cost')
    check('name="payment_option"' not in html, 'or which of three ways to collect money')
    check('name="status"' not in html, 'or whether the booking is pending or confirmed')
    check("cleaner's pay" not in html.lower(), 'and says nothing about what the cleaner earns')
    check(html.count('type="submit"') - html[:html.index('id="booking-form"')].count('type="submit"') == 1,
          'it has one button')

    print('\n2. No lead fee, from any source -- the source is just recorded')
    c.post('/bookings/new', data=dict(BASE, name='From Google', source='google'))
    c.post('/bookings/new', data=dict(BASE, name='From A Friend', source='referral'))
    g = Booking.query.filter_by(name='From Google').first()
    f = Booking.query.filter_by(name='From A Friend').first()
    check(g.lead_fee == 0 and g.price == 200, 'Google: no lead fee, customer pays $200')
    check(f.lead_fee == 0 and f.price == 200, 'a referral: the same')
    check(g.source == 'google' and f.source == 'referral', 'and each records where it came from')
    r = c.get('/bookings/price-preview?service_type=standard&bedrooms=3&bathrooms=2'
              '&frequency=one_time&cleaning_price=200&source=facebook').get_json()
    check(r['total'] == 200, 'the live total on the form adds nothing either')

    print('\n3. A booking with no source is never called "website"')
    c.post('/bookings/new', data=dict(BASE, name='Old Form Post'))
    check(Booking.query.filter_by(name='Old Form Post').first().source == 'manual',
          'a hand-made booking is tagged manual')

    print('\n4. Pricing no longer asks for a lead fee')
    check('name="lead_fee"' not in c.get('/settings/pricing').get_data(as_text=True),
          'there is no lead fee box on Pricing')

    print('\n5. Pricing decides whether the confirmation asks for a deposit')
    asked = []
    real = bookings_mod._notify_customer
    bookings_mod._notify_customer = lambda b, confirmation=True, pay_kind='none': (asked.append(pay_kind) or '')
    try:
        c.post('/bookings/new', data=dict(BASE, name='No Deposit', notify_customer='1'))
        PricingSetting.set('phone_booking_deposit', '1'); db.session.commit()
        c.post('/bookings/new', data=dict(BASE, name='Deposit', notify_customer='1'))
        c.post('/bookings/new', data=dict(BASE, name='Quiet'))
    finally:
        bookings_mod._notify_customer = real
    check(asked == ['none', 'deposit', 'none'],
          f'off: no link; on: deposit link; nothing sent: no link either (got {asked})')
    check('and the $50 deposit link' in c.get('/bookings/new').get_data(as_text=True),
          'and the form says so on the confirmation tickbox')

    print('\n6. The deposit switch is set on Pricing')
    page = c.get('/settings/pricing').get_data(as_text=True)
    check('name="phone_booking_deposit"' in page, 'the deposit switch is on the Pricing page')
    form = {'deposit_amount': '50', 'phone_booking_deposit_shown': '1'}
    c.post('/settings/pricing', data=form)
    check(not bookings_mod._ask_deposit_on_phone_bookings(), 'an unticked box turns the deposit off')

    print('\n7. One card asks who is cleaning, and pay is asked once')
    db.session.add(Staff(name='Rosa Cleaner', phone='4075559999', is_active=True))
    db.session.commit()
    html = c.get(f'/bookings/{g.id}').get_data(as_text=True)
    who = html[html.index('data-card-key="who"'):html.index('data-card-key="money"')]
    check(html.index('data-card-key="who"') < html.index('data-card-key="money"'),
          '"Who\'s doing it" comes before the money')
    check('Nobody yet' in who, 'and says nobody is on the job yet')
    check(html.count('name="assign_to"') == 1, 'there is one cleaner picker on the page')
    check(who.index('name="assign_to"') < who.index('name="crew_pay_each"'),
          'the picker comes first; the pay workings are folded under it')
    check('Save pay</button>' not in who, 'no "Save pay" before anyone is on the job')
    s = Staff.query.filter_by(name='Rosa Cleaner').first()
    c.post(f'/bookings/{g.id}/assign', data={'assign_to': str(s.id), 'add_pay': '80'})
    html = c.get(f'/bookings/{g.id}').get_data(as_text=True)
    who = html[html.index('data-card-key="who"'):html.index('data-card-key="money"')]
    check('Rosa Cleaner' in who and 'name="pay_' in who, 'once assigned, the card shows her and her pay')
    check('+ Add another cleaner' in who and 'Nobody yet' not in who,
          'with "add another" folded away')

print('\nAll checks passed.')
