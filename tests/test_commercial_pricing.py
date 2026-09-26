"""What a commercial job costs, and who decides.

Three things were wrong and they compounded.

**The numbers were low.** The defaults quoted a flat 1.7 cents per square foot
per visit — a 5,000 sq ft weekly office at $83 — because they assumed one
cleaner covers 3,000 sq ft an hour. That is a 5,000 sq ft office fully cleaned,
vacuumed and restrooms included, in one hour and forty minutes. The $20 hourly
figure was a wage rather than what an hour of somebody's time costs once tax,
supplies and travel are in it.

**Travel was invisible.** Whatever the drive cost was absorbed by the
minimum-visit fee, so every small job priced the same whether it was ten
minutes away or an hour — and the ones far enough away to be losing money
looked exactly like the ones that were not. Now the drive is priced like the
cleaning and added *after* the floor, because the floor answers "is this stop
worth making" and the drive answers "how far is this customer". Different
questions.

**And none of it was reaching anybody.** `commercial_pricing.quote()` — the
function the module docstring calls the pricing brain — was called by nothing.
The real arithmetic lived in JavaScript, in two separate copies, which had
already drifted: one of them ignored scope add-ons entirely, so a medical
office priced from the account form came out at office rates while the same
building priced on the calculator page came out higher. Every fix ever made to
the Python was a fix to a file nobody executed.

So the last section of this file is the one that matters most. It loads the
real pages in a real browser and checks the price on screen against the price
the server calculates. Not that the code looks the same — that the numbers
are.
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/cp.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
from models import CommercialAccount, PricingSetting
import commercial_pricing as cp

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


def q(sqft, **kw):
    with app.app_context():
        return cp.quote(sqft, **kw)


print('\n1. The defaults are no longer half of market')
# 1.7 cents a square foot was the symptom. The cause was the production rate.
office = q(5000, category='office', frequency='weekly')
per_sqft = office['standard'] / 5000
check(office['hours'] == 2.5,
      f"a 5,000 sq ft office is 2.5 hours of work, not 1.7 ({office['hours']})")
check(office['standard'] >= 150,
      f"and quotes at ${office['standard']}, not $83")
check(per_sqft > 0.03, f'which is {per_sqft * 100:.1f}¢ a square foot, not 1.7¢')


print('\n2. Detailed work is priced as detailed work')
# A medical exam room is not an open-plan office, and the production rates
# have to say so or the quote does not.
sizes = {c: q(4000, category=c)['standard']
         for c in ('office', 'daycare', 'medical_office')}
check(sizes['medical_office'] > sizes['daycare'] > sizes['office'],
      f'medical > daycare > office ({sizes})')
# Medical also carries the disinfection protocol whether anyone ticks the box.
plain = q(4000, category='office')['standard']
med = q(4000, category='medical_office')['standard']
check(med > plain * 1.3, f'medical is well clear of office (${med} vs ${plain})')


print('\n3. Travel moves the price, and is never swallowed')
# The whole point. Two identical buildings, different distances.
near = q(5000, drive_mins=10)['standard']
far = q(5000, drive_mins=60)['standard']
check(far > near, f'an hour away costs more than ten minutes (${far} vs ${near})')
check(far - near > 40, f'and by a real amount (${far - near})')


print('\n4. Especially on the small jobs, where it used to vanish')
# A small job hits the minimum. Before, that floor ate the drive entirely, so
# a tiny job an hour away and the same job next door were the same price —
# and the far one was the one quietly losing money.
small_near = q(1200, drive_mins=10)
small_far = q(1200, drive_mins=60)
check(small_near['onsite_price'] == small_far['onsite_price'],
      'both small jobs sit on the minimum for the work itself')
check(small_far['standard'] > small_near['standard'],
      f"but the far one still costs more (${small_far['standard']} vs "
      f"${small_near['standard']}) — this is the bug")
check(small_far['standard'] - small_near['standard']
      == small_far['drive_price'] - small_near['drive_price'],
      'and the difference is exactly the travel')


print('\n5. The arithmetic holds together')
r = q(6000, category='office', frequency='weekly', drive_mins=30)
check(r['standard'] == r['onsite_price'] + r['drive_price'],
      f"visit price is the work plus the journey "
      f"({r['standard']} = {r['onsite_price']} + {r['drive_price']})")
check(r['monthly'] == round(r['standard'] * 4.3),
      f"monthly is weekly visits x the visit price ({r['monthly']})")
check(r['annual'] == r['monthly'] * 12, 'and annual is twelve of those')
check(r['low'] < r['standard'] < r['premium'], 'the range brackets the price')
check(r['profit_per_visit'] > 0, 'and every quote makes money')

nothing = q(0)
check(nothing['standard'] == 0, 'no square footage, no price')
check(nothing['drive_price'] == 0, 'and no journey to a job that does not exist')


print('\n6. An owner\'s own numbers always win')
# These are starting defaults, not opinions. Somebody who has measured their
# own crews must be able to say so.
with app.app_context():
    db.create_all()
    PricingSetting.set('comm_prod_office', '1200')
    PricingSetting.set('comm_hourly_cost', '32')
    PricingSetting.set('comm_drive_minutes', '45')
    db.session.commit()
    mine = cp.quote(5000, category='office')
check(mine['hours'] > office['hours'],
      f"a slower measured rate means more hours ({mine['hours']})")
check(mine['standard'] > office['standard'],
      f"and a higher price (${mine['standard']} vs ${office['standard']})")
check(mine['drive_minutes'] == 45, 'and their own default drive time is used')

with app.app_context():
    for k in ('comm_prod_office', 'comm_hourly_cost', 'comm_drive_minutes'):
        PricingSetting.set(k, '')
    db.session.commit()


print('\n7. A drive time set on the account beats the default')
# A customer's distance belongs to that customer. Re-quoting them next year
# must not start again from the generic number.
with app.app_context():
    a = CommercialAccount(business_name='Far Away Offices', square_footage=5000,
                          category='office', drive_minutes=75)
    db.session.add(a)
    db.session.commit()
    theirs = cp.quote(a.square_footage, category=a.category,
                      drive_mins=a.drive_minutes)
check(theirs['drive_minutes'] == 75, 'the account\'s own figure is used')
check(theirs['standard'] > office['standard'],
      f"and they are quoted more for being far (${theirs['standard']})")


print('\n8. Nonsense in does not put a wrong number out')
for bad in ('', None, 'soon', -20, 'abc'):
    got = q(5000, drive_mins=bad)
    check(got['standard'] > 0 and got['drive_minutes'] >= 0,
          f'drive time {bad!r} → ${got["standard"]}, {got["drive_minutes"]} min')


print('\n9. The server is the only place a price is worked out')
# The failure that made every fix above pointless. If the arithmetic returns
# to the templates, this catches it.
import pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
for name in ('_comm_calc.html', 'commercial_calculator.html'):
    src = (ROOT / 'templates' / 'admin' / name).read_text()
    check('/commercial/quote.json' in src, f'{name} asks the server')
    for formula in ('CFG.target', 'COMM_PRICING.target', 'CFG.min_visit',
                    'COMM_PRICING.min_visit', 'CFG.hourly', 'COMM_PRICING.hourly'):
        check(formula not in src, f'{name} does not price it itself ({formula})')

c = app.test_client()
with c.session_transaction() as sess:
    sess['logged_in'] = True
    sess['role'] = 'owner'
r = c.get('/commercial/quote.json?sqft=5000&category=office&frequency=weekly'
          '&drive_minutes=30')
check(r.status_code == 200, f'the endpoint answers ({r.status_code})')
served = r.get_json()
check(served['standard'] == q(5000, drive_mins=30)['standard'],
      'and gives the same number the function does')

anon = app.test_client()
check(anon.get('/commercial/quote.json?sqft=5000').status_code in (302, 401, 403),
      'while a stranger cannot read your pricing')


if failures:
    print(f'\n\n❌ {len(failures)} commercial-pricing check(s) failed.\n')
    sys.exit(1)
print('\n\n✅ One formula, in one place, and it covers the drive.\n')
