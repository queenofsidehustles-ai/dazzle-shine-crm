"""A reply to the shared number reaching the company that sent the text.

A company that connects its own Twilio number points that number at its own
address, so /messages/incoming knows whose reply it is before it runs. Every
other company sends from one shared number, and a phone number can point at
exactly one address -- so for those the company has to be worked out from the
message itself.

What is worth protecting here:

  * the reply goes to whoever texted that person most recently, not to
    whichever company happens to come first
  * a number that merely shares its last seven digits is not a match -- the
    cheap narrowing filter must never be mistaken for the answer
  * a reply nobody can be matched to is written down, not dropped and not
    pushed into an arbitrary company's inbox
  * the alert link points at the company's own address, not the shared one the
    text arrived at, and it survives a slug with a hyphen in it
  * /messages/relay is signature-checked and not gated on a tenant host: an
    unlisted Twilio path accepts unsigned POSTs from anybody, and a gated one
    could never be reached at all
"""
import os, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/relay.db'
os.environ['SECRET_KEY'] = 'test-key-that-is-long-enough-for-prod-check'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
SENT = []
notifications.send_sms = lambda to, body, **k: (SENT.append((to, body)), (True, 'stub'))[1]
notifications.send_email = lambda *a, **k: (True, 'stub')

from datetime import datetime, timedelta
from app import create_app
from extensions import db
from models import ErrorLog
from blueprints import messages as M
import control_plane, tenancy, security, integrations

app = create_app()
failures = []


def check(ok, label):
    print(('  ok   ' if ok else '  FAIL ') + label)
    if not ok:
        failures.append(label)


NOW = datetime.utcnow()
# Three companies, and the same seven trailing digits in two of them.
ROWS = {
    'tenant_kojo':        [('4075551234', NOW - timedelta(hours=5))],
    'tenant_final_touch': [('+1 (407) 555-1234', NOW - timedelta(minutes=10))],
    'tenant_other':       [('3215551234', NOW - timedelta(minutes=1))],
}
ORGS = [{'slug': 'kojo'}, {'slug': 'final-touch'}, {'slug': 'other'}, {'slug': 'dazzle'}]
# Dazzle shares its own line with the platform: it is the number the shared
# traffic goes out on, and it is still Dazzle's business line.
OWN_NUMBERS = {'tenant_dazzle': '+1 (689) 407-4848'}


def _fake_stored(name):
    return OWN_NUMBERS.get(tenancy.current_schema(), '') if name == 'twilio_phone' else ''


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


SQL_SEEN = []


def _fake_execute(stmt, params=None):
    """Stand in for the per-schema read. SQLite has no schemas, so the schema
    the code switched into is read back from tenancy itself."""
    SQL_SEEN.append(str(stmt))
    return _Result(ROWS.get(tenancy.current_schema(), []))


print('1. The company that texted them most recently owns the reply')
with app.app_context():
    db.create_all()
    real_execute, real_orgs = db.session.execute, control_plane.all_orgs
    db.session.execute = _fake_execute
    control_plane.all_orgs = lambda engine: ORGS
    try:
        check(M._company_that_texted('4075551234') == 'final-touch',
              'the 10-minute-old text wins over the 5-hour-old one')
        check(M._company_that_texted('3215551234') == 'other',
              'a number sharing the last seven digits is a different person')
        check(M._company_that_texted('9995550000') == '',
              'nobody has texted this number, so no company claims the reply')
        check(all("status = 'sent'" in q for q in SQL_SEEN) and SQL_SEEN,
              'only texts that actually went out can have prompted a reply')
    finally:
        db.session.execute, control_plane.all_orgs = real_execute, real_orgs

print('\n2. The alert link points at the company, not the shared address')
os.environ['BASE_DOMAIN'] = 'akyehq.com'
try:
    check(M._company_base('final-touch') == 'https://final-touch.akyehq.com',
          'a hyphen in the slug survives -- the schema name cannot be reversed')
finally:
    del os.environ['BASE_DOMAIN']

print('\n3. A first text from a stranger goes to whoever owns the number')
with app.app_context():
    real_stored = integrations._stored
    real_orgs2 = control_plane.all_orgs
    integrations._stored = _fake_stored
    control_plane.all_orgs = lambda engine: ORGS
    try:
        check(M._company_owning_number('+16894074848') == 'dazzle',
              'a text to Dazzle\'s own line is Dazzle\'s, as it was before any of this')
        check(M._company_owning_number('+14075550000') == '',
              'a number no company claims is still nobody\'s')
    finally:
        integrations._stored, control_plane.all_orgs = real_stored, real_orgs2

print('\n4. Who texted them last outranks who owns the number')
os.environ['BASE_DOMAIN'] = 'akyehq.com'   # so the link assertion below is real
with app.app_context():
    landed = {}
    real_handle, real_stored = M._handle_inbound, integrations._stored
    real_execute, real_orgs3 = db.session.execute, control_plane.all_orgs
    M._handle_inbound = lambda link_base=None: (
        landed.update(schema=tenancy.current_schema(), base=link_base), M._blank_twiml())[1]
    integrations._stored = _fake_stored
    db.session.execute = _fake_execute
    control_plane.all_orgs = lambda engine: ORGS
    try:
        with app.test_request_context('/messages/relay', method='POST',
                                      data={'From': '+14075551234', 'To': '+16894074848',
                                            'Body': 'yes 2pm works'}):
            M.relay()
        check(landed.get('schema') == 'tenant_final_touch',
              'a reply to a text Final Touch sent is Final Touch\'s, not Dazzle\'s')
        landed.clear()
        with app.test_request_context('/messages/relay', method='POST',
                                      data={'From': '+19375550000', 'To': '+16894074848',
                                            'Body': 'hi do you clean carpets'}):
            M.relay()
        check(landed.get('schema') == 'tenant_dazzle',
              'but a stranger writing in falls to the company that owns the line')
        check(landed.get('base') == 'https://dazzle.akyehq.com',
              'and the alert link is built for that company')
    finally:
        M._handle_inbound, integrations._stored = real_handle, real_stored
        db.session.execute, control_plane.all_orgs = real_execute, real_orgs3
        del os.environ['BASE_DOMAIN']

print('\n5. A reply matching nobody is written down, not guessed at')
with app.app_context():
    real = M._company_that_texted
    M._company_that_texted = lambda phone10, **k: ''
    try:
        with app.test_request_context('/messages/relay', method='POST',
                                      data={'From': '+14075559999', 'Body': 'who is this'}):
            resp = M.relay()
        check(resp.status_code == 200 and '<Response></Response>' in resp.get_data(as_text=True),
              'Twilio is answered with empty TwiML rather than an error')
        row = ErrorLog.query.filter_by(kind='sms').first()
        check(row is not None, 'the unmatched reply is recorded')
        check(row is not None and 'who is this' in (row.message or ''),
              'along with what they actually said')
    finally:
        M._company_that_texted = real

print('\n6. The endpoint is signed, and reachable')
check('/messages/relay' in security.TWILIO_WEBHOOK_PATHS,
      'it is signature-checked -- an unlisted Twilio path takes unsigned POSTs')
check('/messages/relay' in security.CSRF_EXEMPT_PATHS,
      'Twilio posts from its own origin and is exempt, like /messages/incoming')
check('/messages/relay' not in security.PROVIDER_WEBHOOK_PATHS,
      'it is NOT gated on a tenant host -- the shared number has no company in it')
check('/messages/incoming' in security.PROVIDER_WEBHOOK_PATHS,
      'while a company with its own number still is')

print('\n7. A company with its own number is untouched')
check(app.view_functions['messages.incoming'].__name__ == 'incoming',
      'the original webhook is still the registered handler for /incoming')

print()
if failures:
    print(f'{len(failures)} FAILED:')
    for f in failures:
        print('  - ' + f)
    sys.exit(1)
print('all good')
