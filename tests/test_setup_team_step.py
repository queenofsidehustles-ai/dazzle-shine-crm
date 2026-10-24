"""The team step of setup: the people she hires, optional, after the first job.

The owner is already the first cleaner (owner_cleaner.py), created with the
account and given no pay, so a job can be given to herself before anybody is
added and the team is not something setup makes her do first. This step is
for the day she hires.

What this holds:
- Team is an optional step, last on the list, and arrives as one 'team' card
  with no row for the owner.
- One Save writes every cleaner on the card, typed or pasted.
- One bad row saves nobody, so fixing it and pressing Save again works.
- Names must be distinct -- a solo job pays the cleaner it names.
- Pay is what the owner typed, never a default.
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


print('\n1. Team is optional, and last')
with app.app_context():
    steps = onboarding.journey()
    keys = [s['key'] for s in steps if s.get('required')]
    team_step = next(s for s in steps if s['key'] == 'team')
check(keys == ['business', 'pricing', 'payments'], f'the required steps have no team: {keys}')
check(team_step.get('required') is False and steps[-1]['key'] == 'team',
      'the team step is optional and comes last')
check(team_step['done'] is False, 'and nobody hired yet means it is not done')

print('\n2. It arrives as one team card, with no row for the owner')
with app.app_context(), app.test_request_context():
    from flask import session
    session['user_id'] = OWNER_ID
    cards = setup_assistant.team_card()
team = cards[0]
check(len(cards) == 1 and team['kind'] == 'team' and team['step'] == 'team',
      'one team card, not one per cleaner')
check('me' not in team, 'there is no owner row: she is already the first cleaner')
check('already on the team' in team['note'] and 'emailed' in team['note'],
      'it says she is on the team, and that nobody is emailed')

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
check(not r.get_json()['ok'] and 'pay' in r.get_json()['say'],
      f'a row with no pay is refused: {r.get_json()["say"]}')
r = save(c, {'others': [{'name': 'Pat TooMuch', 'pay_type': 'percent', 'pay_rate': '150'}]})
check(not r.get_json()['ok'], '150% of a job is refused')
with app.app_context():
    check(not Staff.query.filter(Staff.name.like('Pat %')).count(), 'neither was written')

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
price_cards = sum(1 for m in shown for x in (m.get('cards') or [])
                  if x.get('kind') == 'form' and x.get('step') == 'pricing')
check(price_cards == 1, f'the next card, prices, is on screen once ({price_cards})')
check(any(m.get('tick') == '✓ Check your details' for m in shown),
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
