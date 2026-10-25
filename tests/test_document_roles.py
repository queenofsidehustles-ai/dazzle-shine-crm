"""Who may touch a cleaner's ID, W-9 and background check: the owner, nobody else.

P1-05 from the 25 Oct report: owner uploads of ID, W-9 and background
documents went in with the paperwork-only path for an existing team, and the
negative cases were not held by a test. Every role other than owner, each a
real login, is refused viewing, uploading over, deleting and requesting a
document, and the stored bytes are untouched. And the paperwork-only path is
for people brought over, not for somebody newly hired.
"""
import io
import os
import sys
import tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/docroles.db'
os.environ['SECRET_KEY'] = 'a-real-production-secret'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_email = lambda *a, **k: (True, 'stub')
notifications.send_sms = lambda *a, **k: (True, 'stub')

import auth
import secure_docs
from app import create_app
from extensions import db
from models import ContractorDocument, Staff, User

app = create_app()
failures = []
H = {'Origin': 'http://localhost'}
ID = b'%PDF-1.4 a driving licence, the real one'


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


def client_for(user):
    c = app.test_client()
    with c.session_transaction() as s:
        s.update(logged_in=True, role=user.role, user_id=user.id, user_name=user.name,
                 auth_fingerprint=auth._auth_fingerprint(user.password_hash))
    return c


with app.app_context():
    db.create_all()
    users = {}
    for role in ('owner', 'admin', 'dispatcher', 'sales', 'cleaner', 'limited'):
        u = User(name=role.title(), username=f'{role}@docs.test', role=role, active=True)
        u.password_hash = f'hash-{role}'
        db.session.add(u)
        users[role] = u
    ana = Staff(name='Ana Lopez', phone='4075550111', is_active=True, agreement_token='tok-ana')
    db.session.add(ana)
    db.session.commit()
    doc = ContractorDocument(staff_id=ana.id, kind='id', filename='licence.pdf',
                             content_type='application/pdf', size_bytes=len(ID),
                             data=secure_docs.encrypt(ID))
    db.session.add(doc)
    db.session.commit()
    DOC, ANA = doc.id, ana.id
    clients = {r: client_for(u) for r, u in users.items()}

print('\n1. Every role but the owner is refused')
for role in ('admin', 'dispatcher', 'sales', 'cleaner', 'limited'):
    c = clients[role]
    r = c.get(f'/contractors/documents/{DOC}/view')
    check(r.status_code in (302, 403, 404) and ID not in r.get_data(),
          f'{role}: cannot open the ID ({r.status_code})')
    r = c.post(f'/contractors/team/{ANA}/documents/id',
               data={'document': (io.BytesIO(b'%PDF-1.4 forged'), 'forged.pdf')},
               content_type='multipart/form-data', headers=H)
    check(r.status_code in (302, 403), f'{role}: cannot file a document over it ({r.status_code})')
    r = c.post(f'/contractors/documents/{DOC}/delete', headers=H)
    check(r.status_code in (302, 403), f'{role}: cannot delete it ({r.status_code})')
    r = c.post(f'/contractors/documents/request/{ANA}/w9', headers=H)
    check(r.status_code in (302, 403), f'{role}: cannot send a request in the owner\'s name ({r.status_code})')
with app.app_context():
    d = db.session.get(ContractorDocument, DOC)
    check(d is not None and secure_docs.decrypt(d.data) == ID and d.filename == 'licence.pdf',
          'after all of that, the stored ID is exactly what it was')

print('\n2. The owner can')
r = clients['owner'].get(f'/contractors/documents/{DOC}/view')
check(r.status_code == 200 and r.get_data() == ID and 'no-store' in (r.headers.get('Cache-Control') or ''),
      'the owner opens it, byte for byte, never cached')

print('\n3. Paperwork-only is for a team brought over, not a new hire')
with app.app_context():
    old = Staff(name='Bo Chen', is_active=True); old.mark_existing_team()
    new = Staff(name='Cy Diaz', is_active=True)
    db.session.add_all([old, new]); db.session.commit()
    old_steps = {k for k, _ in old.get_applicable_steps()}
    new_steps = {k for k, _ in new.get_applicable_steps()}
    check('background_check' not in old_steps and 'phone_interview' not in old_steps,
          'somebody brought over skips the hiring steps')
    check({'background_check', 'phone_interview', 'orientation'} <= new_steps,
          'a new hire still has the background check, interview and orientation')
    check(not new.is_existing_team, 'and is not marked as existing team by default')

print()
if failures:
    print(f'❌ {len(failures)} failed')
    sys.exit(1)
print('✅ only the owner can touch a cleaner\'s documents')
