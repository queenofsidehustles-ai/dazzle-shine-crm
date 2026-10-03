"""A 100%-off discount code can only ever be permanent.

Checkout skips collecting a card whenever a promo code brings the invoice to
$0 due today (billing.checkout_session's payment_method_collection). That is
only safe for a code that stays 100% off forever -- a temporary one (once, or
repeating for a fixed number of months) lapses into a full-price renewal with
no card on file to charge it to, and the customer finds out when the
subscription silently goes unpaid.
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/promo.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import billing
from blueprints.console import _promo_form

failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


print('\n1. The console form refuses a temporary 100% discount')
form, problem = _promo_form({'code': 'FREEFOREVER', 'kind': 'percent',
                             'percent': '100', 'duration': 'once'})
check(form is None and problem and 'forever' in problem.lower(),
      f'once + 100% is refused ({problem!r})')

form, problem = _promo_form({'code': 'FREEFOREVER2', 'kind': 'percent',
                             'percent': '100', 'duration': 'repeating',
                             'months': '3'})
check(form is None and problem and 'forever' in problem.lower(),
      f'repeating + 100% is refused ({problem!r})')

print('\n2. But a permanent 100% discount, or any temporary partial one, is fine')
form, problem = _promo_form({'code': 'FREEFOREVER3', 'kind': 'percent',
                             'percent': '100', 'duration': 'forever'})
check(problem is None and form['percent_off'] == 100 and form['duration'] == 'forever',
      '100% forever is accepted')

form, problem = _promo_form({'code': 'HALFOFF', 'kind': 'percent',
                             'percent': '50', 'duration': 'once'})
check(problem is None and form['percent_off'] == 50,
      '50% once is accepted -- something is still due, so a card is still collected')

print('\n3. The same guard holds even calling Stripe directly, bypassing the form')
try:
    billing.create_promo_code('DIRECTCALL', percent_off=100, duration='once')
    check(False, 'a direct call with a temporary 100% discount should have been refused')
except RuntimeError:
    check(False, 'refused for the wrong reason -- Stripe is not configured, not the duration check')
except ValueError as e:
    check('forever' in str(e).lower(), f'refused for the right reason ({e})')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ A 100% discount can only ever be permanent.')
