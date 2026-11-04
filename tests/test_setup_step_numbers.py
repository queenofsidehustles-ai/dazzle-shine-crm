"""The card's "Step N of M" matches the meter, and terms can be edited.

Two small things the owner noticed:
- The card said "Step 4 of 9" while the sidebar meter said "4 of 4". The step
  counter must count the same required steps the meter does, not every step in
  the journey, or the two disagree on the same screen.
- Accepting the terms is one tap, but somebody who wants to change a line needs
  a way out of the card that is not the chat box.
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/steps.db'
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


def next_card(step_key):
    """The card for whichever step is next, with its step number."""
    with app.app_context(), app.test_request_context():
        from flask import session
        session['role'] = 'owner'
        _text, cards, key = setup_assistant.next_message()
        assert key == step_key, f'expected {step_key} next, got {key}'
        return [c for c in cards if c.get('kind') in ('form', 'confirm', 'choice', 'team')]


def all_cards(step_key):
    with app.app_context(), app.test_request_context():
        from flask import session
        session['role'] = 'owner'
        _text, cards, key = setup_assistant.next_message()
        assert key == step_key, f'expected {step_key} next, got {key}'
        return cards


with app.app_context():
    db.create_all()
    # Details and prices done, and the owner's own row made at signup (#158)
    # but not yet confirmed, so the next required step is the team -- step 2
    # of the four.
    from models import Staff
    db.session.add(Staff(name='Olivia Owner', is_active=True, is_owner=True, pay_rate=0))
    BusinessSetting.set('business_name', 'Sparkle Co')
    BusinessSetting.set('email', 'o@sparkle.test')
    BusinessSetting.set('phone', '(407) 555-0100')
    BusinessSetting.set('pricing_reviewed', '1')
    db.session.commit()

print('\n1. The required steps number 1..3, the same three the meter counts')
with app.app_context():
    prog = onboarding.progress()
    total = prog['total']
    req = [s['key'] for s in prog['steps'] if s.get('required')]
check(total == 3, f'the meter counts three required steps ({total})')
check(req == ['business', 'team', 'pricing'],
      f'and they are details, team, prices: {req}')

print('\n2. The team card says "Step 2 of 3", not "of 9"')
cards = next_card('team')
team = cards[0]
check(team.get('kind') == 'team', f"it is the team card ({team.get('kind')})")
check(team.get('step_total') == 3, f"denominator matches the meter: of {team.get('step_total')}")
check(team.get('step_no') == 2, f"and it is step {team.get('step_no')} of three")

print('\n3. Payments is not a numbered step: it waits for a first customer')
with app.app_context():
    # What the team card's Save leaves: the owner confirmed as a cleaner.
    BusinessSetting.set('team_confirmed', '1')
    db.session.commit()
    prog = onboarding.progress()
check(prog['complete'] is True, 'three of three is complete')
cards = all_cards('terms')
check(not [c for c in cards if c.get('step_no')], 'the next card (terms) carries no step number')
from_payments = None
with app.app_context(), app.test_request_context():
    from flask import session
    session['role'] = 'owner'
    for k in ('terms', 'balance', 'booking_page'):
        setup_assistant.skip(k)
    _t, pcards, pkey = setup_assistant.next_message()
check(pkey == 'payments', f'payments is offered after the booking page ({pkey})')
check(not [c for c in pcards if c.get('step_no')], 'and is not numbered')
check(any(c.get('kind') == 'skip' for c in pcards), 'and can be skipped')

print('\n4. Terms comes after, unnumbered, and offers an edit link, not only Accept')
with app.app_context():
    from models import BusinessSetting as _B
    _B.set(setup_assistant.SKIPPED_KEY, '')
    db.session.commit()
terms = next_card('terms')[0]
check(not terms.get('step_no') and not terms.get('step_total'),
      f"terms is a go-live check, not step N of 4 ({terms.get('step_no')}/{terms.get('step_total')})")
check(terms.get('secondary', {}).get('href') == '/settings/business',
      'a secondary link points at the terms editor')
check('edit' in (terms.get('secondary', {}).get('label') or '').lower(),
      f"labelled to edit: {terms.get('secondary', {}).get('label')!r}")

print('\n5. Balance follows terms and gets no number either')
with app.app_context(), app.test_request_context():
    from flask import session
    session['role'] = 'owner'
    setup_assistant.accept_terms({'accepted': '1'})
balance = next_card('balance')[0]
check(not balance.get('step_no') and not balance.get('step_total'),
      f"balance is not \"step five of four\" ({balance.get('step_no')}/{balance.get('step_total')})")
with app.app_context(), app.test_request_context():
    from flask import session
    session['role'] = 'owner'
    setup_assistant.set_balance_mode({'mode': 'ask'})
    _text, cards, key = setup_assistant.next_message()
check(key not in ('terms', 'balance'), f'answering it moves on ({key})')
numbered = [c for c in cards if c.get('step_no')]
check(not numbered, 'and nothing after the four claims a step number')

if failures:
    print(f'\n❌ {len(failures)} step-number check(s) failed')
    sys.exit(1)
print('\n✅ The card and the meter agree, and terms can be edited.')
