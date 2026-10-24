"""The setup chat keeps going: no dead ends between steps.

A beta tester shared her booking page, ticked it off, and came back to a chat
still asking about the booking page, with no way forward but the same button.
This holds the fixes:
- the booking page shows the way on once it is ticked;
- the chat notices a step finished elsewhere and asks the next question;
- every step can be skipped for now, and the list still keeps it.
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/flow.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-test'
sys.path.insert(0, ROOT)

from app import create_app
from extensions import db
from models import BusinessSetting
import setup_assistant, onboarding

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
    # Everything required, so this file is about what it says it is about:
    # the optional tail, and not having a dead end in it. The required steps
    # have their own coverage in test_onboarding_required.py.
    BusinessSetting.set('business_name', 'Sparkle Co')
    BusinessSetting.set('phone', '(407) 555-0100')
    BusinessSetting.set('email', 'hello@sparkle.co')
    BusinessSetting.set('timezone', 'America/New_York')
    BusinessSetting.set('pricing_reviewed', '1')
    BusinessSetting.set('terms_reviewed', '1')
    import integrations
    integrations.set('stripe_secret_key', 'sk_live_testonly')
    BusinessSetting.set('balance_collection', 'ask')
    db.session.commit()


def chat():
    with app.test_request_context():
        from flask import session
        session['role'] = 'owner'
        return setup_assistant.load_chat()


print('\n1. The chat starts on the booking page step, with a skip button')
r = c.get('/settings/getting-started')
check(b'booking page' in r.data, 'asks about the booking page')
check(b'"kind": "skip"' in r.data, 'and offers "Skip for now"')

# The owner talks to Nana once, so the chat is saved.
setup_assistant._post = lambda body, timeout=20: {
    'content': [{'type': 'text', 'text': 'Sure, open your booking page.'}], 'stop_reason': 'end_turn'}
c.post('/settings/getting-started/assistant/ask', json={'q': 'ok'}, headers=H)

print('\n2. Sharing it on the booking page moves the chat on')
r = c.get('/settings/booking-page')
check(b'id="nextstep"' in r.data and b'Continue with Nana' in r.data,
      'the booking page has a way back to Nana')
c.post('/settings/booking-page/shared', data={}, headers=H)
r = c.get('/settings/booking-page')
check(b'display:flex' in r.data.split(b'id="nextstep"')[1][:200], 'shown straight away once ticked')
r = c.get('/settings/getting-started?focus=1')
last = [m for m in chat() if m['role'] == 'assistant'][-1]
check(last.get('step') == 'team', 'the chat now asks about adding a cleaner')
check(last['content'].startswith('That step is done.'), 'and says the last one is done')
n = len(chat())
c.get('/settings/getting-started?focus=1')
check(len(chat()) == n, 'and does not say it twice on another visit')

print('\n3. Skip for now')
r = c.post('/settings/getting-started/assistant/skip', json={'step': 'team'}, headers=H).get_json()
check(r['ok'] and 'customer' in r['say'], 'skipping the cleaner step asks for a customer')
with app.app_context():
    keys = {s['key']: s['done'] for s in onboarding.progress()['steps']}
check(keys['team'] is False, 'the getting-started list still has the cleaner step')
r = c.post('/settings/getting-started/assistant/skip', json={'step': 'client'}, headers=H).get_json()
r = c.post('/settings/getting-started/assistant/skip', json={'step': 'job'}, headers=H).get_json()
check(r['ok'] and 'cleaner' in r['say'].lower(), 'skipping everything comes back round, not to a dead end')
bad = c.post('/settings/getting-started/assistant/skip', json={'step': 'nope'}, headers=H).get_json()
check(bad['ok'] is False, 'an unknown step cannot be skipped')

print('\n4. Start over brings skipped steps back')
c.post('/settings/getting-started/assistant/skip', json={'step': 'team'}, headers=H)
c.post('/settings/getting-started/assistant/reset', headers=H)
with app.app_context():
    check(setup_assistant.skipped() == [], 'skips cleared')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ All setup chat flow tests passed.')
