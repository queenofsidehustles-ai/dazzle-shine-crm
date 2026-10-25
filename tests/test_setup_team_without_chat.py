"""Step 2 of setup can be finished without the setup chat.

The team step is done when the owner presses Save on her own card. That card
was only ever in Nana's chat, and the chat is only shown with a Claude API key
and AI switched on. Without it -- no key, AI off, the model down -- nothing
anywhere set `team_confirmed`, so a new owner sat at "1 of 4" with no way on
except hiring somebody (25 Oct operational report, P0-03). The list now shows
the same card as a plain form.
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/team-nochat.db'
os.environ['SECRET_KEY'] = 'test'
os.environ.pop('ANTHROPIC_API_KEY', None)
sys.path.insert(0, ROOT)

from app import create_app
from extensions import db
from models import BusinessSetting, Staff, User
import auth
import onboarding
import owner_cleaner
import setup_assistant

app = create_app()
failures = []
H = {'Origin': 'http://localhost'}


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


with app.app_context():
    db.create_all()
    for k, v in (('business_name', 'Sparkle Co'), ('email', 'mo@sparkle.test'),
                 ('phone', '(407) 555-0100'), ('zip_code', '32801')):
        BusinessSetting.set(k, v)
    u = User(name='Mo Lewis', username='mo', role='owner')
    u.password_hash = 'x'
    db.session.add(u)
    db.session.commit()
    OWNER_ID = u.id
    owner_cleaner.ensure(u, 'mo@sparkle.test')      # what signup does
    db.session.commit()

c = app.test_client()
with c.session_transaction() as s:
    s.update(logged_in=True, role='owner', user_id=OWNER_ID, user_name='Mo Lewis',
             auth_fingerprint=auth._auth_fingerprint('x'))

print('\n1. No chat, and step 2 is next')
check(not setup_assistant.configured(), 'the setup chat is not available (no API key)')
html = c.get('/settings/getting-started').get_data(as_text=True)
check('1 of 4 done' in html, 'one of four done')
check('id="teamStepForm"' in html and 'value="Mo Lewis"' in html and 'I clean jobs myself' in html,
      'the team card is on the list as a form, filled in from her row')

print('\n2. Save finishes it, on her own row')
r = c.post('/settings/getting-started/team', data={
    'me_name': 'Mo Lewis', 'me_email': 'mo@sparkle.test', 'me_phone': '(407) 555-0100',
    'me_cleans': '1'}, headers=H)
check(r.status_code == 302, 'saved')
with app.app_context():
    check(BusinessSetting.get('team_confirmed') == '1', 'the step is answered')
    rows = Staff.query.all()
    check(len(rows) == 1 and rows[0].is_owner and rows[0].is_active,
          f'still exactly one staff row, hers, active ({len(rows)})')
    p = onboarding.progress()
    check(p['next']['key'] == 'pricing', f'and the next step is prices ({p["next"]["key"]})')
html = c.get('/settings/getting-started').get_data(as_text=True)
check('2 of 4 done' in html and 'id="teamStepForm"' not in html, 'two of four, and the form has gone')

print('\n3. Saving again makes no second row')
c.post('/settings/getting-started/team', data={'me_name': 'Mo Lewis', 'me_cleans': '1'}, headers=H)
with app.app_context():
    check(Staff.query.count() == 1, 'one row, however many times she presses Save')

print('\n4. Only the owner')
staff = app.test_client()
with staff.session_transaction() as s:
    s.update(logged_in=True, role='cleaner', user_name='Sam')
r = staff.post('/settings/getting-started/team', data={'me_name': 'X', 'me_cleans': '1'}, headers=H)
check(r.status_code in (302, 403), f'a non-owner is turned away ({r.status_code})')
with app.app_context():
    check(Staff.query.count() == 1 and Staff.query.first().name == 'Mo Lewis', 'and nothing changed')

print()
if failures:
    print(f'❌ {len(failures)} failed')
    sys.exit(1)
print('✅ step 2 can be finished with no chat')
