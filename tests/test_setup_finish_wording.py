"""Payments is offered after setup, not as its last step, and says so.

Until 2026-11-03 payments was the fourth and last required step, and the chat
said "Last step". Sign-ups stopped, and asking for a bank account on the first
evening was the likeliest reason. With business, team and prices done the meter
now says 3 of 3 and setup is complete; payments is offered later in the chat,
without a step number, in words that tie it to the first customer paying, with
the reassurance about bank details and a way to put it off.
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
    # The team step as it is finished now: the owner's row from signup (#158),
    # confirmed with the team card's Save.
    db.session.add(Staff(name='Olivia Owner', is_active=True, is_owner=True, pay_rate=0))
    BusinessSetting.set('team_confirmed', '1')
    db.session.commit()

print('\n1. With three of three done, setup is complete and payments is not required')
with app.app_context():
    p = onboarding.progress()
    check((p['done'], p['total']) == (3, 3), f"the meter says {p['done']} of {p['total']}")
    check(p['complete'] is True, 'setup is complete')
    check(p['payments'] == '', 'and nothing nags about payments before a first booking')
with app.app_context(), app.test_request_context():
    from flask import session
    session['role'] = 'owner'
    for k in ('terms', 'balance', 'booking_page'):
        setup_assistant.skip(k)
    text, cards, key = setup_assistant.next_message()
check(key == 'payments', f'payments is offered once the go-live checks are passed over ({key})')

print('\n2. It ties payments to the first customer paying')
low = text.lower()
check('last step' not in low, 'it is not called the last step')
check('before your first customer pays' in low, 'it says why')
check('bank details stay with you' in low, 'it keeps the reassurance about bank details')
check('skip' in low and any(c.get('kind') == 'skip' for c in cards),
      'and it can be put off, with a Skip button')
check('first booking comes in' in low, 'and says when the reminder comes')

print('\n3. A first booking starts the reminder')
with app.app_context():
    from models import Booking
    db.session.add(Booking(service_type='deep', name='First Customer', email='f@x.test',
                           phone='4075550101', address='1 Main', price=100.0, status='confirmed',
                           preferred_date='2030-01-01', preferred_time='9:00 AM'))
    db.session.commit()
    check(onboarding.payments_state() == 'amber', 'amber once a booking exists')
    BusinessSetting.set('payments_asked_at', '2000-01-01T00:00:00')
    db.session.commit()
    check(onboarding.payments_state() == 'red', 'red once it has been put off for three days')

if failures:
    print(f'\n❌ {len(failures)} finish-wording check(s) failed')
    sys.exit(1)
print('\n✅ Payments waits for the first customer, and says so.')
