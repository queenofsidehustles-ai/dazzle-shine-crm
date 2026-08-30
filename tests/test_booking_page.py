"""The business's own booking page, on its own address, in its own colours.

Free on every plan. It is the same app and the same database, so it costs
nothing to run, and filling it in — services, prices, extras — is exactly the
setup that makes the rest of the software useful. Gate it and free accounts
never enter their prices and never see what they bought.

The things worth holding still:

  * a customer can get a price and book without an account
  * the price comes from the pricing engine, not a second copy of the sums
  * the booking lands in the CRM as a real job
  * the business's colours are on it, and the button text stays readable
    whatever colour they pick — this is the one somebody always gets wrong
  * our name is on a free page and off a paid one
"""
import os, sys, tempfile, json
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/book.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
from models import BusinessSetting, Booking
import brands
import entitlements

app = create_app()
HOST = {'Host': 'sparkle.akye.test'}

failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


def set_plan(plan):
    with app.app_context():
        BusinessSetting.set('plan', plan)
        BusinessSetting.set('plan_status', 'active' if plan != 'free' else '')
        db.session.commit()
    entitlements._clear_cache()


with app.app_context():
    BusinessSetting.set('business_name', 'Sparkle Cleaning Services')
    BusinessSetting.set('phone', '407 555 0100')
    db.session.commit()

c = app.test_client()


print('\n1. Anybody can open it — no account, no login')
r = c.get('/book', headers=HOST)
page = r.data.decode('utf8', 'replace')
check(r.status_code == 200, f'the page loads signed out (HTTP {r.status_code})')
check('Sparkle Cleaning Services' in page, 'and it is the business\'s own name on it')
check('407 555 0100' in page, 'with their phone number for anybody who would rather call')


print('\n2. It offers what the business actually sells')
from pricing import SERVICE_LABELS, FREQUENCY_LABELS
for label in SERVICE_LABELS.values():
    check(label in page, f'{label!r} is offered')
check(any(l in page for l in FREQUENCY_LABELS.values()),
      'and the recurring options, which is where the discount lives')


print('\n3. The price comes from the pricing engine, not a copy of the sums')
# A second implementation in JavaScript would eventually quote a number the
# business does not honour. The page asks the server.
check('/api/calculate' in page, 'the page asks the server for the price')
resp = c.post('/api/calculate', headers=HOST, json={
    'service_type': 'deep', 'bedrooms': 3, 'bathrooms': 2,
    'frequency': 'one_time', 'extras': ''})
quoted = resp.get_json() or {}
check(resp.status_code == 200 and isinstance(quoted.get('total'), (int, float)),
      f'and gets a real number back ({quoted.get("total")})')

from pricing import calculate_price
with app.app_context():
    engine = calculate_price(service_type='deep', bedrooms=3, bathrooms=2,
                             extras='', frequency='one_time')
check(abs(quoted.get('total', 0) - engine) < 0.01,
      f'which is the same figure the office would quote (${engine:.2f})')


print('\n4. Booking through it puts a real job in the CRM')
with app.app_context():
    before = Booking.query.count()
r = c.post('/api/booking', headers=HOST, json={
    'name': 'Mrs Johnson', 'email': 'j@example.com', 'phone': '4075559999',
    'address': '118 Oak Street', 'city': 'Winter Park', 'zip_code': '32789',
    'service_type': 'deep', 'bedrooms': 3, 'bathrooms': 2,
    'frequency': 'one_time', 'preferred_date': '2026-09-10',
    'preferred_time': '10:00 AM'})
check(r.status_code in (200, 201), f'the booking is accepted (HTTP {r.status_code})')
with app.app_context():
    check(Booking.query.count() == before + 1, 'and one new job exists')
    b = Booking.query.order_by(Booking.id.desc()).first()
    check(b.name == 'Mrs Johnson', 'under the customer\'s name')
    check(b.address == '118 Oak Street', 'with the address they typed')
    check(b.preferred_date == '2026-09-10', 'on the day they asked for')


print('\n5. Their colours, not ours')
with app.app_context():
    BusinessSetting.set('brand_dark', '#123a5f')
    BusinessSetting.set('brand_accent', '#2563eb')
    db.session.commit()
page = c.get('/book', headers=HOST).data.decode('utf8', 'replace')
check('#123a5f' in page, 'the header carries the colour they chose')
check('#2563eb' in page, 'and so do the buttons')
check('#f0a44b' not in page and '--amber)' not in page.split('<style>')[1].split('</style>')[0],
      'and our amber is nowhere in their stylesheet')
# The subtler version of the same leak: akye.css paints any *unclassed* submit
# button in our amber, and an attribute selector beats a class. The button that
# takes the booking must therefore carry a class of its own.
check('class="book-btn"' in page,
      'the booking button is classed, so it cannot inherit our amber')
check('.quote .book-btn {' in page,
      'and is styled from the business\'s own accent')


print('\n6. The button text stays readable whatever they pick')
# The failure this prevents: a business chooses a soft yellow, leaves the text
# white, and ships a page whose only button cannot be read. It is not asked
# for -- it is worked out.
cases = [('#f5e050', '#111827', 'a pale yellow'),
         ('#ffffff', '#111827', 'white'),
         ('#123a5f', '#ffffff', 'a deep navy'),
         ('#2563eb', '#ffffff', 'a mid blue')]
for accent, expected, described in cases:
    got = brands.readable_on(accent)
    check(got == expected,
          f'{described} ({accent}) gets {expected} text, not the other one')

with app.app_context():
    BusinessSetting.set('brand_accent', '#f5e050')
    BusinessSetting.set('brand_accent_text', '#ffffff')     # wrong on purpose
    db.session.commit()
page = c.get('/book', headers=HOST).data.decode('utf8', 'replace')
check('--b-on:     #111827' in page,
      'and a value saved wrong is corrected when the page renders, not trusted')


print('\n7. Saving colours in Settings tidies them and fixes the contrast')
admin = app.test_client()
with admin.session_transaction() as sess:
    sess['logged_in'] = True
    sess['role'] = 'owner'
# No tenant Host here: this SQLite database has no tenant schema, so a request
# on `sparkle.akye.test` is bounced to the sign-in before it reaches settings.
# What is under test is the saving, not the routing.
admin.post('/settings/business', data={
    'business_name': 'Sparkle Cleaning Services',
    'brand_dark': '123A5F',            # no hash, wrong case
    'brand_accent': '#F5E050',         # pale, and shouted
    'brand_accent_text': '#ffffff',    # what a person would leave it as
}, follow_redirects=True)
with app.app_context():
    check(BusinessSetting.get('brand_dark') == '#123a5f',
          'a hex typed without its hash is stored properly')
    check(BusinessSetting.get('brand_accent') == '#f5e050', 'and lower-cased')
    check(BusinessSetting.get('brand_accent_text') == '#111827',
          'and the text colour is recomputed rather than believed')


print('\n8. Our name is on a free page, and off a paid one')
set_plan('free')
free_page = c.get('/book', headers=HOST).data.decode('utf8', 'replace')
check('Booking powered by' in free_page, 'a free account carries our badge')
set_plan('pro')
paid_page = c.get('/book', headers=HOST).data.decode('utf8', 'replace')
check('Booking powered by' not in paid_page, 'a paying account does not')
check('Sparkle Cleaning Services' in paid_page, 'but it is still their page')
set_plan('free')


print('\n9. It is free — the free plan can still open it')
set_plan('free')
r = c.get('/book', headers=HOST)
check(r.status_code == 200,
      'a free account is not sent to the upgrade page for its own booking page')


if failures:
    print(f'\n\n❌ {len(failures)} booking-page check(s) failed.\n')
    sys.exit(1)
print('\n\n✅ The booking page works, in their colours, on every plan.\n')
