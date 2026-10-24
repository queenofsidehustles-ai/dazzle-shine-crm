"""Step 2 of setup: the team -- the owner first, then anyone she already has.

Agreed 2026-10-24 (Monica and William): the first thing setup gives back is a
team on screen, because most owners have no customer in their first five
minutes but everybody has themselves.

What this holds:
- Team is the second required step, and arrives as one 'team' card with the
  owner's own row filled in and "I clean jobs myself" ticked.
- One Save writes the owner and every other cleaner, typed or pasted.
- One bad row saves nobody, so fixing it and pressing Save again works.
- Names must be distinct -- a solo job pays the cleaner it names.
- The owner's row is linked to her own login and never invited.
- Saving emails nobody. Inviting is a separate card, and "send" invites only
  the people that card named.
- The plan's cleaner limit is checked before anything is written.
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/team.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-test'
sys.path.insert(0, ROOT)

from app import create_app
from extensions import db
from models import BusinessSetting, Staff, User
import setup_assistant
import onboarding
import auth

app = create_app()
failures = []
H = {'Origin': 'http://localhost'}


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


with app.app_context():
    db.create_all()
    BusinessSetting.set('business_name', 'Sparkle Co')
    BusinessSetting.set('email', 'mo@sparkle.test')
    BusinessSetting.set('phone', '(407) 555-0100')
    BusinessSetting.set('zip_code', '32801')
    BusinessSetting.set('timezone', 'America/New_York')
    u = User(name='Mo Lewis', username='mo', role='owner')
    u.password_hash = 'x'
    db.session.add(u)
    db.session.commit()
    OWNER_ID = u.id


def owner():
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['role'] = 'owner'
        s['user_id'] = OWNER_ID
        s['user_name'] = 'Mo Lewis'
        s['auth_fingerprint'] = auth._auth_fingerprint('x')
    return c


def save(client, fields):
    return client.post('/settings/getting-started/assistant/save',
                       json={'step': 'team', 'fields': fields}, headers=H)


print('\n1. Team is required, and second')
with app.app_context():
    keys = [s['key'] for s in onboarding.journey() if s.get('required')]
check(keys[:2] == ['business', 'team'], f'business then team: {keys}')

print('\n2. It arrives as one team card, the owner already on it')
with app.app_context(), app.test_request_context():
    from flask import session
    session['user_id'] = OWNER_ID
    _text, cards, key = setup_assistant.next_message()
team = next((c for c in cards if c.get('kind') == 'team'), None)
check(key == 'team', f'the chat is on the team step ({key})')
check(team is not None, 'there is a team card')
check(team and team['me']['name'] == 'Mo Lewis', 'her name is filled in')
check(team and team['me']['email'] == 'mo@sparkle.test', 'her email is filled in')
check(team and team['me']['cleans'] is True, '"I clean jobs myself" is ticked')
check(team and team.get('step_no') == 2, 'it says step 2')

print('\n3. One bad row saves nobody')
c = owner()
r = save(c, {'me_cleans': '1', 'me_name': 'Mo Lewis', 'me_email': 'mo@sparkle.test',
             'others': [{'name': 'Ana Ruiz', 'email': 'ana@x'}]})
j = r.get_json()
check(not j['ok'], 'refused')
check('Ana Ruiz' in j['say'], f'and says which row: {j["say"]}')
with app.app_context():
    check(Staff.query.count() == 0, 'nobody was written, Mo included')

print('\n4. The same name twice is refused')
r = save(c, {'me_cleans': '1', 'me_name': 'Mo Lewis',
             'others': [{'name': 'mo lewis'}]})
check(not r.get_json()['ok'], 'refused')
with app.app_context():
    check(Staff.query.count() == 0, 'still nobody written')

print('\n5. Unticked and empty is not a team')
r = save(c, {'me_cleans': '', 'others': [{'name': '', 'email': ''}]})
check(not r.get_json()['ok'], 'refused, with a reason')

print('\n6. A good card writes everyone, typed and pasted, and emails nobody')
sent = []
import blueprints.migration as mig
real_send = mig.send_join_invite
mig.send_join_invite = lambda s: (sent.append(s.name) or (True, 'ok'))
r = save(c, {'me_cleans': '1', 'me_name': 'Mo Lewis', 'me_email': 'mo@sparkle.test',
             'me_phone': '(407) 555-0100',
             'others': [{'name': 'Ana Ruiz', 'email': 'ana@sparkle.test', 'phone': ''},
                        {'name': '', 'email': '', 'phone': ''}],
             'paste': 'Bea Cole, bea@sparkle.test, 407-555-0101\n\nCruz Diaz\t407 555 0102\n'})
j = r.get_json()
check(j['ok'], f'saved: {j["say"]}')
check('Mo Lewis (you)' in j['say'], 'the roster names her as "you"')
with app.app_context():
    staff = {s.name: s for s in Staff.query.all()}
check(set(staff) == {'Mo Lewis', 'Ana Ruiz', 'Bea Cole', 'Cruz Diaz'},
      f'four cleaners, the empty row ignored: {sorted(staff)}')
check(staff.get('Bea Cole') and staff['Bea Cole'].phone == '407-555-0101',
      'a pasted line keeps its phone')
check(staff.get('Cruz Diaz') and not staff['Cruz Diaz'].email,
      'a pasted line without an email is still a person')
check(staff.get('Mo Lewis') and staff['Mo Lewis'].user_id == OWNER_ID,
      'her row is linked to her own login')
check(sent == [], 'saving emailed nobody')
with app.app_context():
    check(next(s for s in onboarding.journey() if s['key'] == 'team')['done'],
          'the team step is done')

print('\n7. The invite card names the people it can invite, and not her')
invite = next((x for x in j['cards'] if x.get('kind') == 'confirm'
               and x.get('title', '').startswith('Invite')), None)
check(invite is not None, 'an invite card follows the save')
check(invite and invite.get('later'), 'with a "not yet" way out')
listed = ' '.join(invite['lines']) if invite else ''
check('Ana Ruiz' in listed and 'Bea Cole' in listed, 'Ana and Bea are on it')
check('Mo Lewis' not in listed, 'she is not invited to her own business')
check('Cruz Diaz' not in listed, 'nobody without an email is on it')

print('\n8. Somebody added after the card is not invited by it')
with app.app_context():
    db.session.add(Staff(name='Dee Late', email='dee@sparkle.test', is_active=True))
    db.session.commit()
r = c.post('/settings/getting-started/assistant/confirm',
           json={'token': invite['token']}, headers=H)
j = r.get_json()
check(j['ok'], f'sent: {j["say"]}')
check(sorted(sent) == ['Ana Ruiz', 'Bea Cole'], f'exactly the two it named: {sent}')
r = c.post('/settings/getting-started/assistant/confirm',
           json={'token': invite['token']}, headers=H)
check(not r.get_json()['ok'] and sorted(sent) == ['Ana Ruiz', 'Bea Cole'],
      'pressing it again sends nothing twice')
mig.send_join_invite = real_send

print('\n9. The plan limit is checked before anything is written')
import entitlements
real_remaining = entitlements.remaining
entitlements.remaining = lambda name: 1
r = save(c, {'me_cleans': '', 'others': [{'name': 'Eve One'}, {'name': 'Fay Two'}]})
check(not r.get_json()['ok'], f'refused: {r.get_json()["say"]}')
with app.app_context():
    check(not Staff.query.filter(Staff.name.in_(['Eve One', 'Fay Two'])).count(),
          'neither was written')
entitlements.remaining = real_remaining

print('\n10. Only the owner can save a team')
t = app.test_client()
with t.session_transaction() as s:
    s['logged_in'] = True
    s['role'] = 'team'
r = save(t, {'me_cleans': '', 'others': [{'name': 'Gus Sneak'}]})
with app.app_context():
    check(not Staff.query.filter_by(name='Gus Sneak').count(), 'a team login cannot add one')

print()
if failures:
    print(f'❌ {len(failures)} team-step check(s) failed')
    sys.exit(1)
print('✅ team step holds')
