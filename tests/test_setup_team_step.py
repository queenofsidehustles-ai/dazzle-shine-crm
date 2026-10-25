"""Step 2 of setup: the owner sets herself up as a cleaner.

Agreed with William on 2026-10-24 and restored 2026-10-25, after a merge had
made the team an optional last step. Signup already creates the owner's own
cleaner row (owner_cleaner.py, #158); this step is where she sees it and says
yes, and it is the first thing setup gives back.

What this holds:
- Team is required, second of four, and an auto-created owner row alone does
  not finish it -- pressing Save does.
- The card is just her: name, email, cell from her row, "I clean jobs myself"
  ticked. No pay, no spreadsheet, no rows for anybody else.
- Save updates her row (no second row is made) and finishes the step.
  Unticked, her row is kept off jobs, and the step is still answered.
- Hired cleaners added as a list (Nana, older pages) still go through one
  all-or-nothing Save: distinct names, pay as typed or "not set", nobody
  emailed, plan limit checked first.
- The Team page import takes Excel or CSV.
- Saving a card shows the next step's card once, and a finished step is one
  ✓ line rather than its old card.
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


import owner_cleaner
with app.app_context():
    # What signup does now: the owner's own cleaner row, made for her.
    owner_cleaner.ensure(User.query.get(OWNER_ID), 'mo@sparkle.test')

print('\n1. Team is required, second of four, and not done just by signing up')
with app.app_context():
    steps = onboarding.journey()
    keys = [s['key'] for s in steps if s.get('required')]
    team_step = next(s for s in steps if s['key'] == 'team')
    check(Staff.query.filter_by(is_owner=True).count() == 1, 'signup made her row')
check(keys == ['business', 'team', 'pricing', 'payments'], f'details, team, prices, payments: {keys}')
check(team_step['done'] is False, 'her row existing does not finish the step')
check([s['key'] for s in steps].count('team') == 1, 'and there is no second, optional team step')

print('\n2. It arrives as one card about her, already filled in')
with app.app_context(), app.test_request_context():
    from flask import session
    session['user_id'] = OWNER_ID
    _t, cards, key = setup_assistant.next_message()
team = next((x for x in cards if x.get('kind') == 'team'), None)
check(key == 'team', f'after details, the chat is on the team ({key})')
check(team is not None and team.get('step_no') == 2 and team.get('step_total') == 4,
      'Step 2 of 4')
check(team and team['me']['name'] == 'Mo Lewis' and team['me']['email'] == 'mo@sparkle.test',
      'her name and email are filled in from her row')
check(team and team['me']['cleans'] is True, '"I clean jobs myself" is ticked')
import json as _json
blob = _json.dumps(team).lower()
check('pay' not in blob and not team.get('upload'), 'nothing about pay, no spreadsheet')
check(team and team.get('team_link', {}).get('href') == '/migration/team',
      'and a way to the Team import for an owner who does not clean')

print('\n2a. Save finishes it, on her own row')
c = owner()
r = save(c, {'me_cleans': '1', 'me_name': 'Mo Lewis', 'me_email': 'mo@sparkle.test',
             'me_phone': '(407) 555-0100'})
j = r.get_json()
check(j['ok'], f'saved: {j["say"]}')
with app.app_context():
    rows = Staff.query.all()
    me = Staff.query.filter_by(is_owner=True).one()
    check(len(rows) == 1, f'no second row was made ({len(rows)})')
    check(me.phone == '(407) 555-0100' and me.is_active, 'her row has her cell and is on jobs')
    check(next(s for s in onboarding.journey() if s['key'] == 'team')['done'],
          'the team step is done')
nxt = [x for x in j['cards'] if x.get('kind') == 'form' and x.get('step') == 'pricing']
check(len(nxt) == 1, 'and prices is next')

print('\n2c. Unticked: she is kept off jobs, and the step is still answered')
with app.app_context():
    BusinessSetting.set('team_confirmed', '')
    db.session.commit()
r = save(c, {'me_cleans': '', 'me_name': 'Mo Lewis'})
check(r.get_json()['ok'] and 'Team page' in r.get_json()['say'], f'saved: {r.get_json()["say"]}')
with app.app_context():
    check(not Staff.query.filter_by(is_owner=True).one().is_active, 'her row is off jobs')
    check(next(s for s in onboarding.journey() if s['key'] == 'team')['done'], 'and the step is done')
r = save(c, {'me_cleans': '1', 'me_name': 'Mo Lewis', 'me_email': 'mo@sparkle.test'})
with app.app_context():
    check(Staff.query.filter_by(is_owner=True).one().is_active, 'ticking it again puts her back on jobs')

print('\n2b. The price card')
with app.app_context(), app.test_request_context():
    _l, pc = setup_assistant.price_card()
check('starting price' in pc['note'] and 'zip' not in pc['note'].lower(),
      'the price card calls it a starting price and never claims it is from her ZIP')
check('Pricing' in pc['note'], 'and says where to change the other sizes')

print('\n3. One bad row saves nobody')
c = owner()
with app.app_context():
    base = Staff.query.count()
r = save(c, {'others': [{'name': 'Zed Fine', 'email': 'zed@sparkle.test', 'pay_type': 'percent', 'pay_rate': '45'},
                        {'name': 'Ana Ruiz', 'email': 'ana@x', 'pay_type': 'percent', 'pay_rate': '45'}]})
j = r.get_json()
check(not j['ok'], 'refused')
check('Ana Ruiz' in j['say'], f'and says which row: {j["say"]}')
with app.app_context():
    check(Staff.query.count() == base, 'nobody was written, the good row included')

print('\n4. The same name twice is refused')
r = save(c, {'others': [{'name': 'Ana Ruiz', 'pay_type': 'percent', 'pay_rate': '45'},
                        {'name': 'ana ruiz', 'pay_type': 'percent', 'pay_rate': '45'}]})
check(not r.get_json()['ok'], 'refused')
with app.app_context():
    check(Staff.query.count() == base, 'still nobody written')

print('\n5. An empty card is not a team')
r = save(c, {'others': [{'name': '', 'email': ''}]})
check(not r.get_json()['ok'], 'refused, with a reason')

print('\n6. A good card writes everyone, typed and pasted, and emails nobody')
sent = []
import blueprints.migration as mig
real_send = mig.send_join_invite
mig.send_join_invite = lambda s: (sent.append(s.name) or (True, 'ok'))
r = save(c, {'others': [{'name': 'Ana Ruiz', 'email': 'ana@sparkle.test', 'phone': '',
                         'pay_type': 'hourly', 'pay_rate': '$22.50'},
                        {'name': '', 'email': '', 'phone': ''}],
             'paste': 'Bea Cole, bea@sparkle.test, 407-555-0101\n\nCruz Diaz\t407 555 0102\n',
             'paste_pay_type': 'percent', 'paste_pay_rate': '40%'})
j = r.get_json()
check(j['ok'], f'saved: {j["say"]}')
check('you, and Ana Ruiz' in j['say'], 'the roster names her as "you", then the new people')
with app.app_context():
    staff = {s.name: s for s in Staff.query.all()}
check({'Ana Ruiz', 'Bea Cole', 'Cruz Diaz'} <= set(staff) and len(staff) == base + 3,
      f'three cleaners, the empty row ignored: {sorted(staff)}')
check(staff.get('Bea Cole') and staff['Bea Cole'].phone == '407-555-0101',
      'a pasted line keeps its phone')
check(staff.get('Cruz Diaz') and not staff['Cruz Diaz'].email,
      'a pasted line without an email is still a person')
check(sent == [], 'saving emailed nobody')
with app.app_context():
    check(next(s for s in onboarding.journey() if s['key'] == 'team')['done'],
          'the team step is done, now somebody has been hired')

print('\n6b. Pay is what the owner typed, never a default')
with app.app_context():
    staff = {s.name: s for s in Staff.query.all()}
check(staff['Ana Ruiz'].pay_type == 'hourly' and float(staff['Ana Ruiz'].pay_rate) == 22.5,
      'Ana: $22.50 an hour, as typed')
check(staff['Bea Cole'].pay_type == 'percent' and float(staff['Bea Cole'].pay_rate) == 40,
      'Bea: 40% of the job')
r = save(c, {'others': [{'name': 'Pat NoPay'}]})
check(r.get_json()['ok'], f'a person with no pay is saved: {r.get_json()["say"]}')
with app.app_context():
    pat = Staff.query.filter_by(name='Pat NoPay').one()
    check(pat.pay_rate is None, 'with pay left unset, not 50%')
    check(pat.pay_label() == 'Pay not set', 'and it reads "Pay not set"')
    db.session.delete(pat)
    db.session.commit()
r = save(c, {'others': [{'name': 'Pat TooMuch', 'pay_type': 'percent',
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
r = save(c, {'others': [{'name': 'Eve One', 'pay_type': 'percent', 'pay_rate': '45'}, {'name': 'Fay Two', 'pay_type': 'percent', 'pay_rate': '45'}]})
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
r = save(t, {'others': [{'name': 'Gus Sneak', 'pay_type': 'percent', 'pay_rate': '45'}]})
with app.app_context():
    check(not Staff.query.filter_by(name='Gus Sneak').count(), 'a team login cannot add one')

print('\n11. Saving shows the next card once, and finished steps collapse')
import blueprints.setup_assistant_routes as routes
with app.app_context():
    # A fresh company, chat untouched, nothing typed into it yet.
    for st in Staff.query.all():
        db.session.delete(st)
    BusinessSetting.set(f'setup_chat_{OWNER_ID}', '')
    BusinessSetting.set('team_confirmed', '')
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
check(team_cards == 1, f'the next card, the team, is on screen once ({team_cards})')
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
