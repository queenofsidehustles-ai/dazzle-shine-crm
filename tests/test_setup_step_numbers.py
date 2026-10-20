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
        return [c for c in cards if c.get('kind') in ('form', 'confirm', 'choice')]


with app.app_context():
    db.create_all()
    # Enough of a business that the first two required steps are done, so the
    # next required step is terms.
    BusinessSetting.set('business_name', 'Sparkle Co')
    BusinessSetting.set('email', 'o@sparkle.test')
    BusinessSetting.set('phone', '(407) 555-0100')
    BusinessSetting.set('pricing_reviewed', '1')
    db.session.commit()

print('\n1. The required steps number 1..4, the same four the meter counts')
with app.app_context():
    total = onboarding.progress()['total']
check(total == 4, f'the meter counts four required steps ({total})')

print('\n2. The terms card says "Step 3 of 4", not "of 9"')
cards = next_card('terms')
terms = cards[0]
check(terms.get('step_total') == 4, f"denominator matches the meter: of {terms.get('step_total')}")
check(terms.get('step_no') == 3, f"and it is step {terms.get('step_no')} of four")

print('\n3. The terms card offers an edit link, not only Accept')
check(terms.get('secondary', {}).get('href') == '/settings/business',
      'a secondary link points at the terms editor')
check('edit' in (terms.get('secondary', {}).get('label') or '').lower(),
      f"labelled to edit: {terms.get('secondary', {}).get('label')!r}")

print('\n4. Balance is "Step 4 of 4"; the optional payments step gets no number')
with app.app_context(), app.test_request_context():
    from flask import session
    session['role'] = 'owner'
    setup_assistant.accept_terms({'accepted': '1'})
balance = next_card('balance')[0]
check(balance.get('step_no') == 4 and balance.get('step_total') == 4,
      f"balance is step {balance.get('step_no')} of {balance.get('step_total')}")
with app.app_context(), app.test_request_context():
    from flask import session
    session['role'] = 'owner'
    setup_assistant.set_balance_mode({'mode': 'ask'})
    _text, cards, key = setup_assistant.next_message()
check(key == 'payments', f'the next step is the optional payments one ({key})')
numbered = [c for c in cards if c.get('step_no')]
check(not numbered, 'and nothing on it claims to be "step five of four"')

if failures:
    print(f'\n❌ {len(failures)} step-number check(s) failed')
    sys.exit(1)
print('\n✅ The card and the meter agree, and terms can be edited.')
