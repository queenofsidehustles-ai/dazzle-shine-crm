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
- Saving emails nobody, and setup offers no invite card: inviting is done
  from each cleaner's page on the Team tab.
- An uploaded Excel or CSV file fills in rows to check and saves nothing.
- Saving a card shows the next step's card once, not twice, and on reload a
  finished step is a single ✓ line rather than its old card.
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

print('\n2b. The card asks only about her: no pay, no spreadsheet, no extra rows')
import json as _json
blob = _json.dumps(team)
check('pay' not in blob.lower(), 'nothing about pay on it')
check('paste_hint' not in team and not team.get('upload'), 'no spreadsheet upload on it')
check(team.get('team_link', {}).get('href') == '/migration/team',
      'and a way to the Team import for an owner who does not clean')
with app.app_context(), app.test_request_context():
    _l, pc = setup_assistant.price_card()
check('starting price' in pc['note'] and 'zip' not in pc['note'].lower(),
      'the price card calls it a starting price and never claims it is from her ZIP')
check('Pricing' in pc['note'], 'and says where to change the other sizes')

print('\n3. One bad row saves nobody')
c = owner()
r = save(c, {'me_cleans': '1', 'me_name': 'Mo Lewis', 'me_email': 'mo@sparkle.test',
             'me_pay_type': 'percent', 'me_pay_rate': '0',
             'others': [{'name': 'Ana Ruiz', 'email': 'ana@x', 'pay_type': 'percent', 'pay_rate': '45'}]})
j = r.get_json()
check(not j['ok'], 'refused')
check('Ana Ruiz' in j['say'], f'and says which row: {j["say"]}')
with app.app_context():
    check(Staff.query.count() == 0, 'nobody was written, Mo included')

print('\n4. The same name twice is refused')
r = save(c, {'me_cleans': '1', 'me_name': 'Mo Lewis', 'me_pay_type': 'percent', 'me_pay_rate': '0',
             'others': [{'name': 'mo lewis', 'pay_type': 'percent', 'pay_rate': '45'}]})
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
             'me_phone': '(407) 555-0100', 'me_pay_type': 'percent', 'me_pay_rate': '0',
             'others': [{'name': 'Ana Ruiz', 'email': 'ana@sparkle.test', 'phone': '',
                         'pay_type': 'hourly', 'pay_rate': '$22.50'},
                        {'name': '', 'email': '', 'phone': ''}],
             'paste': 'Bea Cole, bea@sparkle.test, 407-555-0101\n\nCruz Diaz\t407 555 0102\n',
             'paste_pay_type': 'percent', 'paste_pay_rate': '40%'})
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

print('\n6b. Pay is what the owner typed, never a default')
with app.app_context():
    staff = {s.name: s for s in Staff.query.all()}
check(staff['Ana Ruiz'].pay_type == 'hourly' and float(staff['Ana Ruiz'].pay_rate) == 22.5,
      'Ana: $22.50 an hour, as typed')
check(staff['Bea Cole'].pay_type == 'percent' and float(staff['Bea Cole'].pay_rate) == 40,
      'Bea: 40% of the job')
check(float(staff['Mo Lewis'].pay_rate) == 0, 'the owner chose 0 for herself, and 0 it is')
r = save(c, {'me_cleans': '', 'others': [{'name': 'Pat NoPay'}]})
check(r.get_json()['ok'], f'a person with no pay is saved: {r.get_json()["say"]}')
with app.app_context():
    pat = Staff.query.filter_by(name='Pat NoPay').one()
    check(pat.pay_rate is None, 'with pay left unset, not 50%')
    check(pat.pay_label() == 'Pay not set', 'and it reads "Pay not set"')
    db.session.delete(pat)
    db.session.commit()
r = save(c, {'me_cleans': '', 'others': [{'name': 'Pat TooMuch', 'pay_type': 'percent',
                                          'pay_rate': '150'}]})
check(not r.get_json()['ok'], '150% of a job is refused')
with app.app_context():
    check(not Staff.query.filter(Staff.name.like('Pat %')).count(), 'it was not written')

print('\n7. No invite card in setup')
check(not any(x.get('kind') == 'confirm' and 'nvite' in (x.get('title') or '')
              for x in j['cards']), 'the next thing shown is not an invite card')
check('Team tab' in j['say'], 'it says where invites are sent from')
mig.send_join_invite = real_send

print('\n8. A spreadsheet fills rows in and saves nothing')
import io, openpyxl
wb = openpyxl.Workbook()
ws = wb.active
ws.append(['First Name', 'Last Name', 'Email Address', 'Cell Phone', 'Hourly Rate'])
ws.append(['Hana', 'Ito', 'hana@sparkle.test', '407-555-0110', '$21'])
ws.append(['Ivy', 'Jones', '', '', ''])
ws.append([None, None, None, None, None])
buf = io.BytesIO(); wb.save(buf)
before = None
with app.app_context():
    before = Staff.query.count()
r = c.post('/settings/getting-started/assistant/team-file', headers=H,
           data={'file': (io.BytesIO(buf.getvalue()), 'team.xlsx')},
           content_type='multipart/form-data')
x = r.get_json()
check(x['ok'], f'the Excel file is read: {x["say"]}')
check([w['name'] for w in x['rows']] == ['Hana Ito', 'Ivy Jones'],
      f'first + last make the name, blank rows dropped: {x["rows"]}')
check(x['rows'][0]['email'] == 'hana@sparkle.test' and x['rows'][0]['phone'] == '407-555-0110',
      'email and cell found by their headings')
check(x['rows'][0]['pay_type'] == 'hourly' and x['rows'][0]['pay_rate'] == '21',
      'an hourly rate column comes over as hourly')
check(x['rows'][1]['pay_rate'] == '' and x['rows'][1]['pay_type'] == '',
      'a blank pay is left blank for the owner, not guessed')
with app.app_context():
    check(Staff.query.count() == before, 'nothing was saved by the upload')
r = c.post('/settings/getting-started/assistant/team-file', headers=H,
           data={'file': (io.BytesIO(b'Name,Email\nJo Kay,jo@sparkle.test\n'), 'team.csv')},
           content_type='multipart/form-data')
x = r.get_json()
check(x['ok'] and [(w['name'], w['email']) for w in x['rows']] == [('Jo Kay', 'jo@sparkle.test')],
      f'a CSV is read the same way: {x["rows"]}')
r = c.post('/settings/getting-started/assistant/team-file', headers=H,
           data={'file': (io.BytesIO(b'xx'), 'team.xls')},
           content_type='multipart/form-data')
check(not r.get_json()['ok'] and '.xlsx' in r.get_json()['say'],
      'an old .xls is refused with what to do instead')

print('\n9. The plan limit is checked before anything is written')
import entitlements
real_remaining = entitlements.remaining
entitlements.remaining = lambda name: 1
r = save(c, {'me_cleans': '', 'others': [{'name': 'Eve One', 'pay_type': 'percent', 'pay_rate': '45'}, {'name': 'Fay Two', 'pay_type': 'percent', 'pay_rate': '45'}]})
check(not r.get_json()['ok'], f'refused: {r.get_json()["say"]}')
with app.app_context():
    check(not Staff.query.filter(Staff.name.in_(['Eve One', 'Fay Two'])).count(),
          'neither was written')
entitlements.remaining = real_remaining

print('\n9b. The Team page import takes Excel, and pay only when it is plain')
wb = openpyxl.Workbook(); ws = wb.active
ws.append(['Name', 'Email', 'Pay'])
ws.append(['Kim Lee', 'kim@sparkle.test', '$19'])
ws.append(['Lou Ma', 'lou@sparkle.test', ''])
buf = io.BytesIO(); wb.save(buf)
real_send = mig.send_join_invite
mig.send_join_invite = lambda s: (True, 'ok')
r = c.post('/migration/team', headers=H,
           data={'csv_file': (io.BytesIO(buf.getvalue()), 'crew.xlsx')},
           content_type='multipart/form-data')
mig.send_join_invite = real_send
with app.app_context():
    kim = Staff.query.filter_by(name='Kim Lee').first()
    lou = Staff.query.filter_by(name='Lou Ma').first()
check(kim is not None and lou is not None, f'both imported from Excel ({r.status_code})')
check(kim and kim.pay_type == 'hourly' and float(kim.pay_rate) == 19, 'Kim: $19 an hour, from the sheet')
check(lou and lou.pay_rate is None, 'Lou: no pay on the sheet, so not set — not 50%')
check(kim and kim.is_existing_team, 'and they are existing team')

print('\n10. Only the owner can save a team')
t = app.test_client()
with t.session_transaction() as s:
    s['logged_in'] = True
    s['role'] = 'team'
r = save(t, {'me_cleans': '', 'others': [{'name': 'Gus Sneak', 'pay_type': 'percent', 'pay_rate': '45'}]})
with app.app_context():
    check(not Staff.query.filter_by(name='Gus Sneak').count(), 'a team login cannot add one')

print('\n11. Saving shows the next card once, and finished steps collapse')
import blueprints.setup_assistant_routes as routes
with app.app_context():
    # A fresh company, chat untouched, nothing typed into it yet.
    for st in Staff.query.all():
        db.session.delete(st)
    BusinessSetting.set(f'setup_chat_{OWNER_ID}', '')
    BusinessSetting.set('phone', '')
    db.session.commit()
c2 = owner()
r = c2.post('/settings/getting-started/assistant/save', headers=H,
            json={'step': 'business', 'fields': {'business_name': 'Sparkle Co',
                                                 'phone': '(407) 555-0100'}})
check(r.get_json()['ok'], 'details saved')
with app.app_context(), app.test_request_context():
    from flask import session
    session['user_id'] = OWNER_ID
    stored = setup_assistant.load_chat()
    shown = routes.for_display(stored)
team_cards = sum(1 for m in shown for x in (m.get('cards') or []) if x.get('kind') == 'team')
check(team_cards == 1, f'the team card is on screen once ({team_cards})')
check(any(m.get('tick') == '✓ Your details' for m in shown),
      'the finished details step is one ✓ line')
check(not any(x.get('kind') == 'form' and x.get('step') == 'business'
              for m in shown for x in (m.get('cards') or [])),
      'and its old card is not back on screen')
html = c2.get('/settings/getting-started').get_data(as_text=True)
check('sa-card sa-focus' not in html,
      'the chat does not pop up again as if it were the first visit')

print()
if failures:
    print(f'❌ {len(failures)} team-step check(s) failed')
    sys.exit(1)
print('✅ team step holds')
