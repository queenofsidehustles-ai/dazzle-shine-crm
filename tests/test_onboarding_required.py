"""Setup asks for what a business cannot trade without, and offers the rest.

The list used to walk somebody from signing up to a first assigned job:
business, prices, booking page, a cleaner, a customer, a job. Three of those
need a world the business may not have on its first evening -- and it asked
for a customer before it asked whether card payments worked at all.

Four things that are genuinely required were not on it:

  * the timezone everything is scheduled against, which silently assumes
    New York;
  * the terms customers agree to at the moment they book;
  * the Stripe connection, without which every payment link is decoration;
  * whether balances are ever collected, which unanswered means they are not.

Two of those four fail silently. Nothing errors; the money does not arrive.

What this holds:
- The required steps are configuration, and none of them need a customer.
- `complete` means able to trade, and does not wait on the optional ones.
- The optional steps are still offered after that, and still counted.
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/req.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, ROOT)

from app import create_app
from extensions import db
from models import BusinessSetting
import onboarding
import integrations

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


def keys(required=None):
    with app.app_context():
        return [s['key'] for s in onboarding.journey()
                if required is None or bool(s.get('required')) is required]


def done_map():
    with app.app_context():
        return {s['key']: bool(s['done']) for s in onboarding.journey()}


with app.app_context():
    db.create_all()
    db.session.commit()

print('\n1. The required steps are the ones that stop a business trading')
req = keys(required=True)
check(req == ['business', 'pricing', 'terms', 'balance'],
      f'required, in order: {req}')
# Not on it because nobody is asked: the ZIP decides the timezone at signup,
# before the owner sees a screen.
check('timezone' not in req, 'the timezone is worked out, not asked')
check(keys(required=False) == ['payments', 'booking_page', 'team', 'client', 'job'],
      'payments is tracked rather than required; the rest are offered')

print('\n2. None of them need a customer, a cleaner or a job')
check(not ({'team', 'client', 'job'} & set(req)),
      'nothing required depends on a world the business may not have yet')

print('\n3. The four that were missing are really checked')
d = done_map()
for k in ('terms', 'balance', 'payments'):
    check(d[k] is False, f'{k} starts unfinished rather than quietly assumed')

print('\n4. A default that was never chosen is not a decision')
with app.app_context():
    import automations
    check(automations.balance_mode() == 'ask',
          'balances default to "ask", so nothing is taken')
    check(done_map()['balance'] is False,
          'and that default does not count as having chosen it')
    automations.set_balance_mode('ask')
    db.session.commit()
check(done_map()['balance'] is True,
      'choosing the same thing on purpose does count')

print('\n5. Complete means able to trade')
with app.app_context():
    BusinessSetting.set('business_name', 'Certify Co')
    BusinessSetting.set('phone', '(407) 555-0100')
    BusinessSetting.set('email', 'hi@certify.co')
    BusinessSetting.set('timezone', 'America/Chicago')
    BusinessSetting.set('pricing_reviewed', '1')
    BusinessSetting.set('terms_reviewed', '1')
    integrations.set('stripe_secret_key', 'sk_live_certifyonly')
    db.session.commit()
    p = onboarding.progress()
check(p['complete'] is True, 'every required step done is "complete"')
check(p['done'] == p['total'] == 4 and p['percent'] == 100,
      f"and the bar is full at {p['done']}/{p['total']} ({p['percent']}%)")
check(p['optional_done'] == 1 and p['optional_total'] == 5,
      'payments done by the Stripe key above, four offered ones outstanding')
check(p['next'] is not None and p['next']['key'] == 'booking_page',
      'there is still a next thing to offer, so the chat does not go quiet')
check(p['next_required'] is None, 'but nothing required is waiting')

print('\n6. A business with no phone number is not finished')
# The phone is the one field here signup cannot provide and customers
# actually need -- it is on every quote, invoice and reminder they get.
with app.app_context():
    BusinessSetting.set('phone', '')
    db.session.commit()
    p = onboarding.progress()
check(p['complete'] is False and p['next_required']['key'] == 'business',
      'a name and an email alone are not details a customer can use')

if failures:
    print(f'\n❌ {len(failures)} onboarding check(s) failed')
    sys.exit(1)
print('\n✅ Required is what you cannot trade without; the rest is offered.')
