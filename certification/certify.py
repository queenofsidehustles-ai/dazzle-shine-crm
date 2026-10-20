"""Walk a disposable Akye business through Nana's setup chat over real HTTP.

Everything talks to a running server the way a browser would. The only thing
standing in for the outside world is the Anthropic endpoint, and what the app
puts on the wire is recorded rather than assumed -- that is the seam the wrong
model name lived in, because the existing suite replaces setup_assistant._post
and so never builds a real request body at all.
"""
import json, os, pathlib, sys
import requests

BASE = os.environ['BASE']
WIRE = pathlib.Path(os.environ['WIRE_LOG'])
SCRIPT = pathlib.Path(os.environ['SCRIPT_FILE'])
MODE = pathlib.Path(os.environ['MODE_FILE'])
H = {'Origin': BASE}
failures, notes = [], []


def check(cond, m):
    print(f'  {"PASS" if cond else "FAIL"}  {m}')
    if not cond:
        failures.append(m)


def note(m):
    print(f'  NOTE  {m}')
    notes.append(m)


def script(items):
    SCRIPT.write_text(json.dumps(items))


def mode(m):
    MODE.write_text(m)


def wire():
    return [json.loads(l) for l in WIRE.read_text().splitlines() if l.strip()]


def tool_use(name, inp, tid='t1'):
    return {'content': [{'type': 'tool_use', 'id': tid, 'name': name, 'input': inp}],
            'stop_reason': 'tool_use'}


def say(t):
    return {'content': [{'type': 'text', 'text': t}], 'stop_reason': 'end_turn'}


USER = os.environ.get('ADMIN_USER', 'cert')
PASS = os.environ.get('ADMIN_PASS', 'certpass')


def owner():
    s = requests.Session()
    r = s.post(f'{BASE}/login', data={'username': USER, 'password': PASS}, timeout=20)
    if 'Set up with' not in r.text and '/login' in r.url:
        sys.exit(f'could not sign in as {USER} -- check ADMIN_USER/ADMIN_PASS')
    return s


def ask(s, q):
    return s.post(f'{BASE}/settings/getting-started/assistant/ask',
                  json={'q': q}, headers=H, timeout=30)


def confirm(s, token):
    return s.post(f'{BASE}/settings/getting-started/assistant/confirm',
                  json={'token': token}, headers=H, timeout=30)


def card(resp):
    cards = [c for c in (resp.json().get('cards') or []) if c.get('kind') == 'confirm']
    return cards[0] if cards else None


print('\n=== 1. Who can use the setup chat ===')
mode('ok')
s = owner()
r = s.get(f'{BASE}/settings/getting-started', timeout=20)
check(r.status_code == 200, 'the owner reaches getting-started')
check('Set up with' in r.text, 'and the chat is on the page')

anon = requests.Session()
for path, payload in (('ask', {'q': 'hi'}), ('confirm', {'token': 'x'})):
    rr = anon.post(f'{BASE}/settings/getting-started/assistant/{path}',
                   json=payload, headers=H, timeout=20, allow_redirects=False)
    check(rr.status_code in (302, 401, 403), f'signed out is refused on /{path} ({rr.status_code})')

print('\n=== 2. What the app puts on the wire ===')
WIRE.write_text('')
script([tool_use('offer_business_details',
                 {'phone': '(407) 555-0199', 'email': 'Hi@Certify.co'}),
        say('Check the card and tap Save.')])
r = ask(s, 'my phone is 407 555 0199, email hi@certify.co')
sent = wire()
check(bool(sent), 'a request actually reached the Anthropic endpoint')
PUBLISHED = {'claude-fable-5-1', 'claude-fable-5', 'claude-opus-5-5', 'claude-opus-5',
             'claude-opus-4-8', 'claude-opus-4-7', 'claude-opus-4-6', 'claude-sonnet-5-5',
             'claude-sonnet-5', 'claude-sonnet-4-6', 'claude-haiku-5-5', 'claude-haiku-4-5'}
models = {x['model'] for x in sent}
check(models and models <= PUBLISHED, f'every model id on the wire is published: {sorted(models)}')
check(all('x-api-key' in x['headers'] for x in sent), 'the key header is sent')
check(all('anthropic-version' in x['headers'] for x in sent), 'the version header is sent')
check(any(x['has_tools'] for x in sent), 'tools are declared')
note(f'{len(sent)} model call(s) for one owner message')

print('\n=== 3. An offer is only an offer ===')
c = card(r)
check(c is not None, 'a Save card came back')
biz = s.get(f'{BASE}/settings/business', timeout=20)
check('555-0199' not in biz.text, 'nothing is saved before the button is pressed')

print('\n=== 4. The button saves, exactly once ===')
res = confirm(s, c['token'])
check(res.json().get('ok') is True, 'pressing Save works')
biz = s.get(f'{BASE}/settings/business', timeout=20)
check('555-0199' in biz.text, 'and the value is really in the business record')
again = confirm(s, c['token'])
check(again.json().get('ok') is False, 'the same card cannot be saved twice')
check('already' in (again.json().get('say') or '').lower(), 'and it says so plainly')
res = confirm(s, 'never-issued')
check(res.json().get('ok') is False, 'a token that was never issued saves nothing')

print('\n=== 5. Pricing, a cleaner and a customer ===')
for label, tool, args, page, needle in (
        ('pricing', 'offer_prices', {'two_bed_two_bath_price': '180'},
         '/settings/pricing', '180'),
        ('cleaner', 'offer_add_cleaner',
         {'name': 'Ama Certify', 'phone': '(407) 555-0144'}, '/contractors/team', 'Ama Certify'),
        ('customer', 'offer_add_customer',
         {'name': 'Rita Certify', 'phone': '(407) 555-0122',
          'address': '9 Test Way', 'city': 'Orlando', 'zip_code': '32801'},
         '/bookings/clients', 'Rita Certify')):
    script([tool_use(tool, args), say('Tap Save.')])
    rr = ask(s, f'set up the {label}')
    cc = card(rr)
    check(cc is not None, f'{label}: a card was offered')
    if not cc:
        continue
    out = confirm(s, cc['token']).json()
    check(out.get('ok') is True, f'{label}: saved on the button')
    pg = s.get(f'{BASE}{page}', timeout=20, allow_redirects=True)
    check(needle in pg.text, f'{label}: visible afterwards on {page}')
    prog = out.get('progress') or {}
    note(f'{label}: setup progress {prog.get("done")}/{prog.get("total")}')

print('\n=== 6. What the owner sees when the provider fails ===')
for label, m in (('a model name that does not exist', 'not_found'),
                 ('the API unreachable', 'timeout')):
    mode(m)
    rr = ask(s, 'what should I do next?')
    body = rr.json()
    said = (body.get('say') or '').strip()
    check(rr.status_code == 200, f'{label}: the route still answers HTTP 200')
    note(f'{label}: owner is told "{said[:90]}"')
    check(bool(said), f'{label}: the owner is told something rather than nothing')
    cards = [x for x in (body.get('cards') or []) if x.get('kind') == 'confirm']
    check(not cards, f'{label}: no card is offered off a failed call')
mode('ok')

print('\n=== 7. Nothing was written by the failed calls ===')
pg = s.get(f'{BASE}/bookings/clients', timeout=20, allow_redirects=True)
check(pg.text.count('Rita Certify') >= 1, 'the customer added earlier is still there')

print()
if failures:
    print(f'RESULT: {len(failures)} check(s) failed')
    for f in failures:
        print('   -', f)
    sys.exit(1)
print('RESULT: every check passed')
