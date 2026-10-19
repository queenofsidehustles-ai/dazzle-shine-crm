"""The setup chat offers; only the owner's button saves.

What this holds:
- No key (or the demo) means no chat, and the getting-started list is unchanged.
- The model can put a card on screen but cannot save anything. Saving takes the
  card's token, once, and only for the four setup actions.
- A Nana proposal cannot be confirmed through the setup route, and is not used
  up by trying.
- Bad details are refused before a card is made.
- The monthly cap holds, and a broken reply from the API does not break the page.
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/setup.db'
os.environ['SECRET_KEY'] = 'test'
os.environ.pop('ANTHROPIC_API_KEY', None)
sys.path.insert(0, ROOT)

from app import create_app
from extensions import db
from models import BusinessSetting, Staff, Client, AssistantProposal
import setup_assistant
import onboarding
import pricing
import proposals

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


def owner():
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['role'] = 'owner'
    return c


H = {'Origin': 'http://localhost'}

# A scripted stand-in for the Claude API: each call pops the next reply.
SCRIPT, SENT = [], []


def fake_post(body, timeout=20):
    SENT.append(body)
    return SCRIPT.pop(0) if SCRIPT else {'type': 'error', 'error': {'message': 'empty'}}


setup_assistant._post = fake_post


def tool_use(name, inp, tid='t1'):
    return {'content': [{'type': 'tool_use', 'id': tid, 'name': name, 'input': inp}],
            'stop_reason': 'tool_use'}


def say(text):
    return {'content': [{'type': 'text', 'text': text}], 'stop_reason': 'end_turn'}


with app.app_context():
    db.create_all()
    BusinessSetting.set('business_name', 'Sparkle Co')
    db.session.commit()

print('\n1. Without a key there is no chat')
c = owner()
r = c.get('/settings/getting-started')
check(r.status_code == 200, 'getting-started page loads')
check(b'Set up with' not in r.data, 'and shows no chat')
with app.test_request_context():
    check(setup_assistant.ask('hi')['say'] == setup_assistant.TROUBLE['off'],
          'asking anyway gets a plain sentence, and no API call')
check(not SENT, 'nothing was sent to the API')

os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-test'

print('\n2. With a key the owner gets the chat, opening on the next step')
c = owner()
r = c.get('/settings/getting-started')
check(b'Set up with' in r.data, 'chat is on the page')
# The name comes from signup, but business details are not finished until
# there is a phone and an email on them too, so that is the first open step.
check(b'phone number and email' in r.data, 'and the opening asks about the next open step')

va = app.test_client()
with va.session_transaction() as s:
    s['logged_in'] = True
    s['role'] = 'va'
r = va.post('/settings/getting-started/assistant/ask', json={'q': 'hi'}, headers=H)
check(r.status_code in (302, 403), 'a non-owner cannot use it')

print('\n3. A card is offered; nothing is saved until the button')
SCRIPT[:] = [tool_use('offer_business_details',
                      {'phone': '(407) 555-0100', 'email': 'Hello@Sparkle.co'}),
             say('Check the card and tap Save.')]
r = c.post('/settings/getting-started/assistant/ask',
           json={'q': 'my number is 407 555 0100, email hello@sparkle.co'}, headers=H)
out = r.get_json()
cards = [x for x in out['cards'] if x['kind'] == 'confirm']
check(len(cards) == 1, 'one Save card came back')
check('Email: hello@sparkle.co' in cards[0]['lines'], 'email shown, tidied to lower case')
first = SENT[-2]
check(first['model'] == setup_assistant.MODEL and first['messages'][0]['role'] == 'user',
      'request uses the setup model and starts with the user')
check(SENT[-1]['messages'][-1]['content'][0]['type'] == 'tool_result',
      'the tool result was handed back to the model')
with app.app_context():
    check(not BusinessSetting.get('phone'), 'phone is NOT saved yet')

r = c.post('/settings/getting-started/assistant/confirm',
           json={'token': cards[0]['token']}, headers=H)
res = r.get_json()
check(res['ok'] is True, 'pressing Save works')
with app.app_context():
    check(BusinessSetting.get('phone') == '(407) 555-0100', 'phone saved as shown')
    check(BusinessSetting.get('email') == 'hello@sparkle.co', 'email saved as shown')
    check(onboarding.progress()['next']['key'] == 'timezone',
          'setup moved on to the timezone, which everything is scheduled against')
check('timezone' in (res.get('follow') or ''), 'and the follow-up asks about the timezone')
r = c.post('/settings/getting-started/assistant/confirm',
           json={'token': cards[0]['token']}, headers=H)
check(r.get_json()['ok'] is False and 'already' in r.get_json()['say'],
      'the same card cannot be saved twice')

print('\n4. Bad details never become a card')
with app.test_request_context():
    text, card = setup_assistant.tool_offer_business(email='hello@sparkle')
    check(card is None and 'email' in text, 'incomplete email refused')
    text, card = setup_assistant.tool_offer_business(phone='555')
    check(card is None, 'short phone refused')
    text, card = setup_assistant.tool_offer_prices('5')
    check(card is None, 'a $5 house clean refused')
    text, card = setup_assistant._run_tool('not_a_tool', {})
    check(card is None, 'unknown tool does nothing')

print('\n5. Prices from one number')
SCRIPT[:] = [tool_use('offer_prices', {'two_bed_two_bath_price': '$180'}),
             say('Tap the button to use these.')]
out = c.post('/settings/getting-started/assistant/ask', json={'q': '180'}, headers=H).get_json()
tok = [x for x in out['cards'] if x['kind'] == 'confirm'][0]['token']
with app.app_context():
    check(pricing.get_std_price(2, 2) != 180, 'not applied before the button')
c.post('/settings/getting-started/assistant/confirm', json={'token': tok}, headers=H)
with app.app_context():
    check(pricing.get_std_price(2, 2) == 180, '2/2 is exactly what they said')
    check(pricing.get_std_price(4, 3) > 180, 'bigger homes scaled up from it')
    check(BusinessSetting.get('pricing_reviewed') == '1', 'pricing step ticked')

print('\n6. A cleaner and a customer')
SCRIPT[:] = [tool_use('offer_add_cleaner', {'name': 'Ama Owusu', 'phone': '4075550111'}),
             say('Tap Add.')]
out = c.post('/settings/getting-started/assistant/ask', json={'q': 'Ama'}, headers=H).get_json()
tok = [x for x in out['cards'] if x['kind'] == 'confirm'][0]['token']
with app.app_context():
    check(Staff.query.count() == 0, 'no cleaner before the button')
c.post('/settings/getting-started/assistant/confirm', json={'token': tok}, headers=H)
with app.app_context():
    check(Staff.query.filter_by(name='Ama Owusu').count() == 1, 'cleaner added')
with app.test_request_context():
    text, card = setup_assistant.tool_offer_cleaner(name='ama owusu')
    check(card is None and 'already' in text, 'a duplicate name is refused up front')

SCRIPT[:] = [tool_use('offer_add_customer', {'name': 'Rita Vance', 'phone': '4079990000',
                                             'address': '1 Elm St', 'city': 'Orlando'}),
             say('Tap Add.')]
out = c.post('/settings/getting-started/assistant/ask', json={'q': 'Rita'}, headers=H).get_json()
tok = [x for x in out['cards'] if x['kind'] == 'confirm'][0]['token']
c.post('/settings/getting-started/assistant/confirm', json={'token': tok}, headers=H)
with app.app_context():
    check(Client.query.filter_by(name='Rita Vance').count() == 1, 'customer added')

print('\n7. Only setup actions run here')
with app.app_context():
    nana = proposals.offer('complete_booking', {'booking_id': 1}, summary='x')
r = c.post('/settings/getting-started/assistant/confirm', json={'token': nana}, headers=H)
check(r.get_json()['ok'] is False, 'a Nana proposal is refused')
with app.app_context():
    row = AssistantProposal.query.filter_by(token=nana).first()
    check(row.used_at is None, 'and is not used up by trying')
r = c.post('/settings/getting-started/assistant/confirm', json={'token': 'made-up'}, headers=H)
check(r.get_json()['ok'] is False, 'a made-up token is refused')

print('\n8. Links only point inside the app')
with app.test_request_context():
    text, card = setup_assistant.tool_show_page('payments')
    check(card['href'] == '/settings/connections', 'payments goes to Connections')
    text, card = setup_assistant.tool_show_page('https://evil.example')
    check(card is None, 'an unknown page gives no link')

print('\n9. A broken reply or a spent allowance does not break the page')
SCRIPT[:] = [{'type': 'error', 'error': {'message': 'overloaded'}}]
out = c.post('/settings/getting-started/assistant/ask', json={'q': 'hi'}, headers=H).get_json()
check(out['say'] == setup_assistant.TROUBLE['error'], 'API error gives a plain sentence')

with app.app_context():
    BusinessSetting.set(setup_assistant._month_key(), str(setup_assistant.MONTHLY_LIMIT))
    db.session.commit()
n = len(SENT)
out = c.post('/settings/getting-started/assistant/ask', json={'q': 'hi'}, headers=H).get_json()
check(out['say'] == setup_assistant.TROUBLE['limit'], 'over the cap says so')
check(len(SENT) == n, 'and does not call the API')

print('\n10. History sent to the model always starts with the owner and alternates')
msgs = setup_assistant._api_history([
    {'role': 'assistant', 'content': 'hello'},
    {'role': 'user', 'content': 'a'}, {'role': 'user', 'content': 'b'},
    {'role': 'assistant', 'content': 'c'}])
check(msgs[0]['role'] == 'user', 'starts with the owner')
check([m['role'] for m in msgs] == ['user', 'assistant'], 'repeated turns are merged')

print('\n11. The conversation lives in the database, not the login cookie')
with app.app_context():
    BusinessSetting.set(setup_assistant._month_key(), '0')
    db.session.commit()
with c.session_transaction() as s:
    check(not any('setup' in k for k in s.keys()), 'nothing chat-related in the cookie')
with app.test_request_context():
    chat = setup_assistant.load_chat()
check(any(m.get('role') == 'user' for m in chat), 'the chat was saved server-side')
done_cards = [x for m in chat for x in (m.get('cards') or [])
              if x.get('kind') == 'confirm' and x.get('done')]
check(done_cards and all(x['done'].startswith('✅') for x in done_cards),
      'a saved card remembers it was saved, even after a second press')
check(any(m.get('hidden') for m in chat), 'the button press is noted as hidden context')
r = c.get('/settings/getting-started')
check(b'pressed the button' in r.data and b'm.hidden' in r.data,
      'hidden turns are in the data but the page skips them')

print('\n12. Replies the API really sends')
# Text alongside the tool call, then an empty turn afterwards.
SCRIPT[:] = [{'content': [{'type': 'text', 'text': 'Here is the card.'},
                          {'type': 'tool_use', 'id': 'a', 'name': 'get_prices', 'input': {}}],
              'stop_reason': 'tool_use'},
             {'content': [], 'stop_reason': 'end_turn'}]
out = c.post('/settings/getting-started/assistant/ask', json={'q': 'prices?'}, headers=H).get_json()
check(out['say'] == 'Here is the card.', 'text written before the tool call is kept')

SCRIPT[:] = [{'content': [{'type': 'tool_use', 'id': f'u{i}', 'name': 'get_prices', 'input': {}}
                          for i in range(6)], 'stop_reason': 'tool_use'},
             say('ok')]
c.post('/settings/getting-started/assistant/ask', json={'q': 'x'}, headers=H)
results = SENT[-1]['messages'][-1]['content']
check(len(results) == 6 and {r['tool_use_id'] for r in results} == {f'u{i}' for i in range(6)},
      'every tool call gets an answer, even past the limit')
check(sum(1 for r in results if r.get('is_error')) == 2, 'the extras are marked not run')

SCRIPT[:] = [{'content': [{'type': 'tool_use', 'id': 'm', 'name': 'offer_add_customer',
                           'input': {'name': 'Ri'}}], 'stop_reason': 'max_tokens'}]
out = c.post('/settings/getting-started/assistant/ask', json={'q': 'x'}, headers=H).get_json()
check(not out['cards'], 'a reply cut off mid-tool-call runs nothing')

with app.test_request_context():
    text, card = setup_assistant.tool_offer_customer(name='Rita', zip_code='32827-12345678')
    check(card is None and 'too long' in text, 'a value too long for its column is refused')

print('\n13. Start over clears the chat')
c.post('/settings/getting-started/assistant/reset', headers=H)
with app.test_request_context():
    check(setup_assistant.load_chat() == [], 'conversation forgotten')

if failures:
    print(f'\n❌ {len(failures)} setup assistant check(s) failed')
    sys.exit(1)
print('\n✅ All setup assistant tests passed.')
