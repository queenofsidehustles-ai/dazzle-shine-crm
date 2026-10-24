"""The seam between the first three steps and connecting payments reads straight.

Since 2026-10-24 payments is the fourth and last required step (details,
team, prices, payments). With three done, the meter says "3 of 4 done", so
the chat must not say setup is finished or that the owner can already take
bookings -- that is what the old wording did, back when payments was an
optional extra. It also used to call payments "the last thing, and it needs
you" and, on a reload, prefixed it with a redundant "That step is done."

This holds that at that seam the chat agrees with the meter: it calls
payments the last step, says why (ready to be paid before the first booking),
keeps the reassurance about bank details, still lets the owner put it off,
and does not prepend the generic done line.
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/finish.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-test'
sys.path.insert(0, ROOT)

from app import create_app
from extensions import db
from models import BusinessSetting
import setup_assistant
import onboarding

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


with app.app_context():
    db.create_all()
    # Finish the first three required steps: business, team, pricing.
    from models import Staff
    BusinessSetting.set('business_name', 'Sparkle Co')
    BusinessSetting.set('email', 'o@sparkle.test')
    BusinessSetting.set('phone', '(407) 555-0100')
    BusinessSetting.set('pricing_reviewed', '1')
    db.session.add(Staff(name='Maria Lopez', is_active=True))
    db.session.commit()

print('\n1. With three of the four done, the next step is payments, the last required one')
with app.app_context():
    p = onboarding.progress()
    reqs = [s for s in p['steps'] if s.get('required')]
    check([s['key'] for s in reqs if not s['done']] == ['payments'],
          'business, team and prices are done; only payments is left')
    check((p['done'], p['total']) == (3, 4), f"the meter says {p['done']} of {p['total']}")
with app.app_context(), app.test_request_context():
    from flask import session
    session['role'] = 'owner'
    text, cards, key = setup_assistant.next_message()
check(key == 'payments', f'payments is next ({key})')

print('\n2. It says this is the last step, not that setup is already done')
low = text.lower()
check(low.startswith('last step'), f'it opens with "Last step" ({text[:40]!r})')
check('needs you' not in low,
      'it does not say payments "needs you"')
check('essentials done' not in low and 'take bookings right now' not in low,
      'and does not claim setup is finished while the meter says 3 of 4')
check('before your first customer books' in low,
      'it says why: be ready to be paid before the first booking')
check('bank details stay with you' in low,
      'and keeps the reassurance about bank details')
check('skip' in low and any(c.get('kind') == 'skip' for c in cards),
      'and it can still be put off for tonight, with a Skip button')

print('\n3. The redundant "That step is done." prefix is dropped at this seam')
with app.app_context(), app.test_request_context():
    from flask import session
    session['role'] = 'owner'
    prefixed, _c, _k = setup_assistant.next_message('That step is done.')
check(not prefixed.startswith('That step is done.'),
      'the catch-up does not stack a generic done line before "Last step"')

if failures:
    print(f'\n❌ {len(failures)} finish-wording check(s) failed')
    sys.exit(1)
print('\n✅ Reaching payments, the last step, reads as one straight line.')
