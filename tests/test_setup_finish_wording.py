"""The seam between finishing setup and connecting payments reads straight.

When the four required steps are done, the meter says "4 of 4 done" and the
page says the business can take bookings. The chat used to undercut that: it
called payments "the last thing, and it needs you" (as if setup were not
finished) and, on a reload, prefixed it with a redundant "That step is done."

This holds that at that seam the chat agrees with the meter: it acknowledges
the essentials are done, frames payments as the optional-but-recommended next
thing, and does not prepend the generic done line.
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
    # Finish the four required steps: business, pricing, terms, balance.
    BusinessSetting.set('business_name', 'Sparkle Co')
    BusinessSetting.set('email', 'o@sparkle.test')
    BusinessSetting.set('phone', '(407) 555-0100')
    BusinessSetting.set('pricing_reviewed', '1')
    db.session.commit()
with app.app_context(), app.test_request_context():
    from flask import session
    session['role'] = 'owner'
    setup_assistant.accept_terms({'accepted': '1'})
    setup_assistant.set_balance_mode({'mode': 'ask'})

print('\n1. With the four done, the next step is the optional payments one')
with app.app_context():
    reqs = [s for s in onboarding.progress()['steps'] if s.get('required')]
    check(all(s['done'] for s in reqs), 'all four required steps are done')
with app.app_context(), app.test_request_context():
    from flask import session
    session['role'] = 'owner'
    text, _cards, key = setup_assistant.next_message()
check(key == 'payments', f'payments is next ({key})')

print('\n2. It acknowledges setup is done, not "it needs you"')
check('needs you' not in text.lower(),
      'it no longer says payments "needs you" as if setup were unfinished')
check('bookings' in text.lower() and 'card' in text.lower(),
      'it says bookings work now and payments is about taking card')
check('bank details stay with you' in text.lower(),
      'and keeps the reassurance about bank details')

print('\n3. The redundant "That step is done." prefix is dropped at this seam')
with app.app_context(), app.test_request_context():
    from flask import session
    session['role'] = 'owner'
    prefixed, _c, _k = setup_assistant.next_message('That step is done.')
check(not prefixed.startswith('That step is done.'),
      'the catch-up does not stack a generic done line before the finish message')

if failures:
    print(f'\n❌ {len(failures)} finish-wording check(s) failed')
    sys.exit(1)
print('\n✅ Finishing setup and connecting payments reads as one straight line.')
