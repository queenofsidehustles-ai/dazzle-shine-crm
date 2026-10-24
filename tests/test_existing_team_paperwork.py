"""Cleaners a company brings with it: paperwork only, not the hiring flow.

Decided 2026-10-24. Somebody who cleaned for the owner before Akye is not
interviewed, background-checked or shadowed again. What still matters is the
paperwork that pays and protects the business.

What this holds:
- Cleaners added in setup, or by the team import, are marked existing team:
  their checklist is the agreement, the forms and payout details only.
- The owner's own row is marked fully done.
- A cleaner hired the ordinary way keeps the whole checklist.
- The owner can upload a W-9, ID or background check she already has, into
  the encrypted store, and only the owner can.
- The invite to an existing cleaner lists only the paperwork still missing,
  and never asks for a document already on file. A new hire's invite does
  not list any (the hiring flow walks them through it in order).
"""
import os, sys, tempfile, io
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/paper.db'
os.environ['SECRET_KEY'] = 'test-secret-for-paperwork'
os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-test'
sys.path.insert(0, ROOT)

from app import create_app
from extensions import db
from models import BusinessSetting, Staff, User
import auth
import secure_docs
import setup_assistant
import blueprints.migration as mig

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
    BusinessSetting.set('phone', '(407) 555-0100')
    u = User(name='Mo Lewis', username='mo', role='owner')
    u.password_hash = 'x'
    db.session.add(u)
    db.session.commit()
    OWNER_ID = u.id


def owner():
    c = app.test_client()
    with c.session_transaction() as s:
        s.update(logged_in=True, role='owner', user_id=OWNER_ID, user_name='Mo Lewis',
                 auth_fingerprint=auth._auth_fingerprint('x'))
    return c


c = owner()
PAPERWORK = ['ic_agreement', 'welcome_forms', 'payment_info']

print('\n1. Setup marks the team it brings as existing')
import owner_cleaner
with app.app_context():
    owner_cleaner.ensure(User.query.get(OWNER_ID))       # what signup does
r = c.post('/settings/getting-started/assistant/save', headers=H, json={
    'step': 'team', 'fields': {'others': [{'name': 'Ana Ruiz', 'email': 'ana@sparkle.test',
                                           'pay_type': 'percent', 'pay_rate': '45'}]}})
check(r.get_json()['ok'], 'team saved')
with app.app_context():
    ana = Staff.query.filter_by(name='Ana Ruiz').one()
    mo = Staff.query.filter_by(is_owner=True).one()
    check(ana.is_existing_team, 'Ana is existing team')
    steps = [k for k, _ in ana.get_applicable_steps()]
    check(steps == PAPERWORK, f'her checklist is the paperwork only: {steps}')
    applicable = [k for k, _ in mo.get_applicable_steps()]
    check(all(k in mo.get_onboarding() for k in applicable),
          'the owner’s own row is fully done')
    ANA = ana.id

print('\n2. A new hire keeps the whole checklist')
with app.app_context():
    hire = Staff(name='Nia New', email='nia@sparkle.test', is_active=True)
    db.session.add(hire)
    db.session.commit()
    check(not hire.is_existing_team, 'not existing team')
    keys = [k for k, _ in hire.get_applicable_steps()]
    check('phone_interview' in keys and 'shadow_job' in keys,
          'interview and shadow shift are still on it')
    HIRE = hire.id

print('\n3. The team import marks people existing too')
with app.app_context(), app.test_request_context():
    real = mig.send_join_invite
    mig.send_join_invite = lambda s: (True, 'ok')
    mig._import_team_rows([{'name': 'Imo Port', 'email': 'imo@sparkle.test', 'phone': ''}])
    mig.send_join_invite = real
    check(Staff.query.filter_by(name='Imo Port').one().is_existing_team,
          'an imported cleaner is existing team')

print('\n4. The invite lists the paperwork still missing')
with app.app_context(), app.test_request_context():
    ana = Staff.query.get(ANA)
    ana.agreement_token = 'tok-ana'
    db.session.commit()
    labels = [l for l, _h in mig.paperwork_links(ana)]
    check(labels == ['Sign your work agreement', 'Fill in your onboarding form',
                     'Send your W-9', 'Send a photo ID'], f'all four: {labels}')
    hire = Staff.query.get(HIRE)
    hire.agreement_token = 'tok-nia'
    check(mig.paperwork_links(hire) == [], 'a new hire’s invite lists none')
    sent = {}
    import notifications
    real_email = notifications.send_email
    notifications.send_email = lambda **kw: (sent.update(kw) or (True, 'ok'))
    mig.send_join_invite(ana)
    notifications.send_email = real_email
    check('/contractors/documents/tok-ana/w9' in sent.get('html', ''),
          'the email carries the W-9 link')
    check('Set up my account' in sent.get('html', ''), 'and still the sign-in link')

print('\n5. The owner uploads a W-9 she already has')
pdf = b'%PDF-1.4 a signed w9'
r = c.post(f'/contractors/team/{ANA}/documents/w9', headers=H,
           data={'document': (io.BytesIO(pdf), 'ana-w9.pdf', 'application/pdf')},
           content_type='multipart/form-data')
check(r.status_code in (302, 303), f'accepted ({r.status_code})')
with app.app_context(), app.test_request_context():
    ana = Staff.query.get(ANA)
    doc = ana.document('w9')
    check(doc is not None, 'it is on file')
    check(doc and doc.data != pdf and secure_docs.decrypt(doc.data) == pdf,
          'stored encrypted, and decrypts to what was sent')
    check(ana.w9_uploaded_at is not None, 'the W-9 date is set')
    labels = [l for l, _h in mig.paperwork_links(ana)]
    check('Send your W-9' not in labels, f'and she is no longer asked for it: {labels}')

print('\n6. Only the owner, and only real kinds')
t = app.test_client()
with t.session_transaction() as s:
    s.update(logged_in=True, role='team')
r = t.post(f'/contractors/team/{ANA}/documents/id', headers=H,
           data={'document': (io.BytesIO(b'\x89PNG'), 'id.png', 'image/png')},
           content_type='multipart/form-data')
with app.app_context():
    check(Staff.query.get(ANA).document('id') is None, 'a team login cannot file one')
r = c.post(f'/contractors/team/{ANA}/documents/passport', headers=H,
           data={'document': (io.BytesIO(pdf), 'x.pdf', 'application/pdf')},
           content_type='multipart/form-data')
check(r.status_code == 404, f'an unknown kind is refused ({r.status_code})')
r = c.post(f'/contractors/team/{ANA}/documents/id', headers=H,
           data={'document': (io.BytesIO(b'MZ'), 'x.exe', 'application/octet-stream')},
           content_type='multipart/form-data')
with app.app_context():
    check(Staff.query.get(ANA).document('id') is None, 'a non-document file is refused')

print('\n7. The cleaner page explains the short checklist')
html = c.get(f'/contractors/team/{ANA}').get_data(as_text=True)
check('Already on your team before Akye' in html, 'the note is there')
check(f'/contractors/team/{ANA}/documents/id' in html, 'with an Upload for the ID')

print()
if failures:
    print(f'❌ {len(failures)} paperwork check(s) failed')
    sys.exit(1)
print('✅ existing-team paperwork holds')
