"""The balance step is one question on one card, and payments is asked once.

What an owner saw on the last required step: a chat bubble asking the
question, then two cards both titled "How balances get paid", both saying
"Step 4 of 4", one button each. It read as two steps. Then, on answering, the
closing "That's the four essentials done" came twice, and the page under the
chat offered Connect payments again in a bar on top, a Next card and a "more
things" line -- while a green box said payments were already set.

Since 2026-10-24 balance is no longer one of the four required steps: it is a
go-live check that comes after payments (and after terms), so it carries no
"Step N of 4" at all.

This holds:
  1. balance is ONE card: the question, two answers, and no step number;
  2. tapping an answer adds the next question once, not twice;
  3. on the getting-started page, payments (put off, so Nana has moved on to
     the booking page) is offered exactly once -- as the Next card, since it
     is the required step still waiting -- and nothing claims it is connected
     or that setup is finished.
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/balance.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-test'
sys.path.insert(0, ROOT)

from app import create_app
from extensions import db
from models import BusinessSetting
import setup_assistant

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


H = {'Origin': 'http://localhost'}
c = app.test_client()
with c.session_transaction() as s:
    s['logged_in'] = True
    s['role'] = 'owner'

with app.app_context():
    db.create_all()
    # Details, team and prices done, payments put off for tonight, terms
    # accepted -- so balance is next.
    from models import Staff
    BusinessSetting.set('business_name', 'Sparkle Co')
    BusinessSetting.set('email', 'o@sparkle.test')
    BusinessSetting.set('phone', '(407) 555-0100')
    BusinessSetting.set('pricing_reviewed', '1')
    db.session.add(Staff(name='Maria Lopez', is_active=True))
    db.session.commit()
with app.app_context(), app.test_request_context():
    from flask import session
    session['role'] = 'owner'
    setup_assistant.skip('payments')
    setup_assistant.accept_terms({'accepted': '1'})

print('\n1. Balance is one card with the question and both answers')
with app.app_context(), app.test_request_context():
    from flask import session
    session['role'] = 'owner'
    text, cards, key = setup_assistant.next_message()
check(key == 'balance', f'balance is next ({key})')
choices = [x for x in cards if x.get('kind') in ('form', 'confirm', 'choice')]
check(len(choices) == 1, f'one card, not two ({len(choices)})')
card = choices[0] if choices else {}
check(card.get('kind') == 'choice', f'it is a choice card ({card.get("kind")})')
check('card on file' in (card.get('title') or ''),
      'the question is on the card itself')
check(not text, f'and not repeated in a bubble above it ({text!r})')
opts = card.get('options') or []
check([o.get('label', '').split(' ')[0] for o in opts] == ['Yes', 'No'],
      'with a yes and a no')
check(all(o.get('token') and o.get('line') for o in opts),
      'each answer has its own token and its own one-line explanation')
check(not any(x.get('step_no') for x in cards),
      'no "Step N of 4" -- balance is a go-live check, not a required step')
check(sum(1 for x in cards if x.get('kind') == 'skip') == 1, 'one Skip link')

NEXT_Q = setup_assistant.STEP_PROMPTS['booking_page']

print('\n2. Answering adds the next question once')
r = c.get('/settings/getting-started', headers=H)
check(r.status_code == 200, 'the page opens')
with app.app_context(), app.test_request_context():
    # The page only rebuilds the opener until the owner speaks; record one
    # so the transcript is the saved one, as in real use after a few steps.
    chat = [{'role': 'user', 'content': '(I accepted the terms.)', 'hidden': True},
            {'role': 'assistant', 'content': '', 'cards': cards, 'step': 'balance'}]
    setup_assistant.save_chat(chat)
    db.session.commit()
r = c.post('/settings/getting-started/assistant/confirm',
           json={'token': opts[0]['token']}, headers=H)
body = r.get_json() or {}
check(body.get('ok') is True, f'the answer saves ({body.get("say")})')
with app.app_context(), app.test_request_context():
    saved = setup_assistant.load_chat()
said = [m.get('content') or '' for m in saved if m.get('role') == 'assistant']
check(body.get('follow') and NEXT_Q in body.get('follow'),
      f'it moves on to the booking page ({body.get("follow")!r})')
closing = [m for m in said if NEXT_Q in m]
check(len(closing) == 1, f'the next question is there once ({len(closing)})')
choice = [x for m in saved for x in (m.get('cards') or []) if x.get('kind') == 'choice']
check(choice and (choice[0].get('done') or '').startswith('✅'),
      'and the card remembers it was answered, for after a reload')

print('\n3. The page offers payments once, and does not say it is connected')
r = c.get('/settings/getting-started', headers=H)
html = r.get_data(as_text=True)
with app.app_context(), app.test_request_context():
    again = [m.get('content') or '' for m in setup_assistant.load_chat()
             if m.get('role') == 'assistant']
check(sum(NEXT_Q in m for m in again) == 1,
      'reloading the page does not add it a second time')
check("You can't take payments yet" not in html,
      'no payments bar on top of this page')
check('>Next</div>' in html and 'Connect payments →' in html,
      'the Next card is the required step still waiting: payments')
check(html.count('Connect payments →') == 1,
      'offered once, not in two places')
check('Show me my page →' not in html,
      'and the Next card does not repeat the booking page Nana is asking about')
check('connect payments,' not in html.lower() and 'connect payments.' not in html.lower(),
      'and payments is not in the "more things" line either')
check('payments and balances are all set' not in html,
      'nothing says payments is set when it is not')
check('id="gs-list"' in html,
      'the list the chat refreshes in place is on the page')
check('id="gs-ready"' not in html and 'You can take bookings' not in html,
      'and no "you can take bookings" box while payments, now required, is outstanding')

print('\n4. On the dashboard, the payments bar still shows')
with app.test_request_context():
    from flask import url_for
    dash = url_for('admin.dashboard')
r = c.get(dash, headers=H, follow_redirects=True)
check("You can't take payments yet" in r.get_data(as_text=True)
      or 'Still no way to take card payments' in r.get_data(as_text=True),
      'the dashboard still carries the reminder')

print()
if failures:
    print(f'RESULT: {len(failures)} check(s) failed')
    for f in failures:
        print('   -', f)
    sys.exit(1)
print('RESULT: every check passed')
