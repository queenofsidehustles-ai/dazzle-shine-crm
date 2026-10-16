"""The release-gate evidence: the audit chain, certify.py, the backup's
off-database record, and the issue -> accept -> amend journey.

From the GREEN remediation plan (2026-10-16). What each would cost if it
regressed:
  * the audit chain: an edit made by somebody able to switch the guards off
    (the database owner can) would leave no trace;
  * certify.py schema / evidence / compare: the gates would rest on startup
    logs instead of on the database itself;
  * the backup: a restore that came back changed, or with its guards off,
    would be called good, and there would be no record outside the database
    to hold a later one against;
  * the journey: G2 would have nothing reproducible to run.

Against a disposable Postgres, like the rest of the multi-company suite.
"""
import gzip
import json
import os
import pathlib
import sys
import tempfile
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import fresh_postgres
from quote_answer import answer
os.environ['DATABASE_URL'] = fresh_postgres.url('dsm_test_evidence_cert')
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['FLASK_ENV'] = 'development'

import notifications
SENT = []
notifications.send_email = lambda *a, **k: (SENT.append(k) or (True, 'stub (id re_test)'))
notifications.send_sms = lambda *a, **k: (True, 'stub')

from sqlalchemy import text
from app import create_app
from extensions import db
from models import CommercialQuote, ContractAuditEvent
import backup
import certify
import contract_audit
import evidence_check
import provisioning
import quote_evidence
import tenancy

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


A, DEMO = 'evcert', 'evdemo'
HOST = f'http://{A}.akye.test'
for slug, name in ((A, 'Evidence Cleaning'), (DEMO, 'Evidence Demo')):
    with app.app_context():
        provisioning.provision(slug, name, quiet=True)
        db.session.remove()
    fresh_postgres.set_company_plan(slug, 'scale')
SA, SD = tenancy.schema_for(A), tenancy.schema_for(DEMO)
engine = provisioning._engine()
owner = fresh_postgres.owner_client(app, A, 'akye.test')
FORM = {'contact_name': 'Pat Private', 'email': 'pat@private.example', 'property_type': 'Office Building',
        'property_address': '1 Secret St', 'frequency': 'weekly', 'contract_term': 'annual',
        'services': ['Office Cleaning'], 'price_per_visit': '120', 'monthly_price': '516'}


def sql(statement, schema=SA, **params):
    with engine.begin() as conn:
        return conn.execute(text(statement.format(s=f'"{schema}".')), params)


def rows(statement, schema=SA, **params):
    with engine.connect() as conn:
        return conn.execute(text(statement.format(s=f'"{schema}".')), params).mappings().all()


def verify(path):
    """backup.verify into a fresh scratch database. A restore boots the app
    against the scratch database and stubs the mailer, for the rest of the
    process -- right for the CLI, wrong for this test, so both are put back."""
    live, mailer = os.environ['DATABASE_URL'], notifications.send_email
    verify.n = getattr(verify, 'n', 0) + 1
    try:
        return backup.verify(path, quiet=True,
                             scratch_url=fresh_postgres.url(f'dsm_test_evidence_cert_scratch{verify.n}'))
    finally:
        os.environ['DATABASE_URL'], notifications.send_email = live, mailer


def as_owner(*statements, schema=SA):
    """What only the database owner can do: switch a guard off, act, switch
    it back on -- in one transaction."""
    with engine.begin() as conn:
        for st in statements:
            conn.execute(text(st.format(s=f'"{schema}".')))


# One accepted quote, so there is real evidence to check.
owner.post('/quotes/new', base_url=HOST, data=dict(FORM, company='Chain Holdings'))
with app.app_context(), tenancy.use_tenant(A):
    q = CommercialQuote.query.filter_by(company='Chain Holdings').first()
    QID, TOK = q.id, q.token
    db.session.remove()
owner.post(f'/quotes/{QID}/send', base_url=HOST)
answer(app.test_client(), TOK, HOST, 'accept', name='Pat Private')

print('\n1. The audit trail is a hash chain, computed by the database')
chain = rows('SELECT * FROM {s}contract_audit_event ORDER BY chain_seq')
check(len(chain) >= 4 and all(r['row_hash'] and r['chain_seq'] for r in chain),
      f'every entry has its place and hash ({len(chain)} entries)')
check([r['chain_seq'] for r in chain] == list(range(1, len(chain) + 1)), 'numbered 1..n with no gaps')
prev, ok = quote_evidence.AUDIT_GENESIS, True
for r in chain:
    ok = ok and r['prev_hash'] == prev and quote_evidence.audit_row_hash(r, r['chain_seq'], prev) == r['row_hash']
    prev = r['row_hash']
check(ok, 'each names the one before, and recomputes from its own contents')
with engine.connect() as conn:
    check(evidence_check.audit_chain(conn, SA)['problems'] == [], 'the checker agrees')

# Twelve writers at once: one line, no two in the same place.
gate = threading.Barrier(12)


def write(i):
    with app.app_context(), tenancy.use_tenant(A):
        gate.wait()
        contract_audit.record('draft_saved', QID, actor_kind='system', actor=f'writer {i}')
        db.session.commit()
        db.session.remove()


threads = [threading.Thread(target=write, args=(i,)) for i in range(12)]
[t.start() for t in threads]
[t.join() for t in threads]
with engine.connect() as conn:
    c = evidence_check.audit_chain(conn, SA)
check(c['problems'] == [] and c['length'] == len(chain) + 12,
      f'twelve simultaneous entries extend it as one line ({c["length"]})')

print('\n2. Entries written before the chain are chained, oldest first')
as_owner('ALTER TABLE {s}contract_audit_event DISABLE TRIGGER contract_audit_event_chain',
         "INSERT INTO {s}contract_audit_event (created_at, event, actor_kind, actor) "
         "VALUES (now(), 'created', 'system', 'legacy one'), (now(), 'sent', 'system', 'legacy two')",
         'ALTER TABLE {s}contract_audit_event ENABLE TRIGGER contract_audit_event_chain', schema=SD)
check(len(rows('SELECT id FROM {s}contract_audit_event WHERE chain_seq IS NULL', SD)) == 2,
      'two unchained entries, as an old database has')
with engine.connect() as conn:
    check(any('not in the chain' in p for p in evidence_check.audit_chain(conn, SD)['problems']),
          'the checker says they are outside it')
as_owner(*quote_evidence.audit_backfill_sql(f'"{SD}".'), schema=SD)
with engine.connect() as conn:
    c = evidence_check.audit_chain(conn, SD)
check(c['problems'] == [] and c['length'] >= 2, f'migration 0031\'s backfill chains them ({c["length"]})')
try:
    sql("UPDATE {s}contract_audit_event SET actor = 'x'", SD)
    check(False, 'and the frozen guard is back on afterwards')
except Exception:
    check(True, 'and the frozen guard is back on afterwards')

print('\n3. certify.py: read-only, and it fails on what it should')
out = tempfile.mkdtemp()
check(certify.main(['schema', '--company', A, '--out', f'{out}/s.json']) == 0, 'schema: passes')
report = json.load(open(f'{out}/s.json'))
check(report['passed'] and report['sections'][0]['version'] == evidence_check.head_revision(),
      'on the migration head, with every guard on')
check(certify.main(['evidence', '--company', A, '--out', f'{out}/e.json']) == 0, 'evidence: passes')
ev = json.load(open(f'{out}/e.json'))
dump = json.dumps(ev)
check('Pat Private' not in dump and 'pat@private.example' not in dump and '1 Secret St' not in dump,
      'its output names no customer')
with engine.connect() as conn, conn.begin():
    evidence_check.read_only(conn)
    try:
        conn.execute(text(f'UPDATE "{SA}".commercial_quote SET company = company'))
        check(False, 'the connection it reads with refuses writes')
    except Exception:
        check(True, 'the connection it reads with refuses writes')
as_owner('ALTER TABLE {s}commercial_agreement DISABLE TRIGGER commercial_agreement_kept')
check(certify.main(['schema', '--company', A]) == 1, 'a guard switched off fails schema')
with engine.connect() as conn:
    p = evidence_check.schema_report(conn, SA)['problems']
check(any('commercial_agreement_kept' in x and 'switched off' in x for x in p), 'and names it')
as_owner('ALTER TABLE {s}commercial_agreement ENABLE TRIGGER commercial_agreement_kept')

print('\n4. The backup writes the evidence down outside, and the restore is held to it')
bdir = tempfile.mkdtemp()
path, manifest = backup.create(bdir, os.environ['DATABASE_URL'], quiet=True)
ev = manifest.get('evidence') or {}
check(SA in ev and ev[SA]['audit_head'] and ev[SA]['agreements'],
      'the manifest holds the chain head and every evidence hash')
check('Pat Private' not in json.dumps(ev), 'and nothing about any customer')
ok, _ = verify(path)
check(ok, 'a faithful backup restores and matches what was written down, guards on')
check(certify.main(['compare', path.replace('.json.gz', '.manifest.json')]) == 0,
      'compare: the live database still holds everything the manifest wrote down')

# A backup whose revision was altered after it was taken.
bad = path.replace('.json.gz', '-altered.json.gz')
with gzip.open(path, 'rt') as src, gzip.open(bad, 'wt') as dst:
    for i, line in enumerate(src):
        rec = json.loads(line) if i else None
        if rec and rec.get('__table__') == 'commercial_quote_revision':
            rec['row']['terms'] = rec['row']['terms'].replace('516', '999')
            line = json.dumps(rec) + '\n'
        dst.write(line)
os.replace(path.replace('.json.gz', '.manifest.json'), bad.replace('.json.gz', '.manifest.json'))
try:
    verify(bad)
    check(False, 'a backup with altered terms fails verification')
except backup.BackupFailed as e:
    check('no longer hash' in str(e), f'a backup with altered terms fails verification')

print('\n5. An edit by somebody able to switch the guards off still shows')
as_owner('ALTER TABLE {s}contract_audit_event DISABLE TRIGGER contract_audit_event_frozen',
         "UPDATE {s}contract_audit_event SET actor = 'Someone Else' WHERE event = 'accepted'",
         'ALTER TABLE {s}contract_audit_event ENABLE TRIGGER contract_audit_event_frozen')
with engine.connect() as conn:
    c = evidence_check.audit_chain(conn, SA)
check(any('changed since it was written' in x for x in c['problems']), 'the chain shows the edited entry')
check(certify.main(['evidence', '--company', A]) == 1, 'evidence fails')
check(certify.main(['compare', bad.replace('.json.gz', '.manifest.json')]) == 1,
      'and so does the database against the record written down before')
try:
    backup.create(tempfile.mkdtemp(), os.environ['DATABASE_URL'], quiet=True)
    check(False, 'and the next backup refuses to write it down as the truth')
except backup.BackupFailed as e:
    check('changed since it was written' in str(e), 'and the next backup refuses to write it down as the truth')
# Re-hashing the edited row to cover it up breaks the next link instead.
row = rows("SELECT * FROM {s}contract_audit_event WHERE event = 'accepted'")[0]
forged = quote_evidence.audit_row_hash(row, row['chain_seq'], row['prev_hash'])
as_owner('ALTER TABLE {s}contract_audit_event DISABLE TRIGGER contract_audit_event_frozen',
         f"UPDATE {{s}}contract_audit_event SET row_hash = '{forged}' WHERE id = {row['id']}",
         'ALTER TABLE {s}contract_audit_event ENABLE TRIGGER contract_audit_event_frozen')
with engine.connect() as conn:
    c = evidence_check.audit_chain(conn, SA)
    then = json.load(open(bad.replace('.json.gz', '.manifest.json')))['evidence'][SA]
    cmp = evidence_check.compare(conn, SA, then)
check(any('does not follow' in x for x in c['problems']) and cmp['problems'],
      'covering it up with a new hash breaks the next link, and the head written down')

print('\n6. G2: the journey, on a demo company')
sql(f"UPDATE public.organizations SET is_demo = true WHERE slug = '{DEMO}'")
sql(f"UPDATE public.organizations SET is_demo = false WHERE slug = '{A}'")
check(certify.main(['journey', '--company', A]) == 1, 'refused on a company that is not a demo')
fresh_postgres.owner_client(app, DEMO, 'akye.test')   # the demo's seeded owner, here
before = len(SENT)
jout = f'{out}/j.json'
code = certify.main(['journey', '--company', DEMO, '--out', jout])
pack = json.load(open(jout))
for s in pack.get('steps', []):
    if not s.get('ok', True):
        print('      ', s)
check(code == 0 and pack['passed'], 'issue → accept → amend passes every check')
check(len(SENT) == before and len(pack['outbox']) >= 2, 'it sent nothing: the stub recorded each send')
ids = pack['ids']
check(set(ids) == {'original', 'amendment'} and all(v['agreement_id'] for v in ids.values()),
      'the pack names each quote, revision, answer, agreement and account')
check(any(s.get('check', '').startswith('the database refuses') and s['ok'] for s in pack['steps'])
      and all(s['ok'] for s in pack['steps'] if s.get('check', '').startswith('the database refuses')),
      'every direct UPDATE and DELETE at the evidence was refused')
with engine.connect() as conn:
    c = evidence_check.audit_chain(conn, SD)
check(c['problems'] == [], 'and the demo\'s chain is still whole')

print('\n7. G4: a refused or unsaved delivery event reaches the errors page, which alerts')
import blueprints.api as api_bp_module
import delivery_events
from models import ErrorLog
os.environ['RESEND_EVENTS_WEBHOOK_SECRET'] = 'whsec_' + 'dGVzdA=='
PLATFORM = 'http://akye.test'


def logged(kind):
    with app.app_context():
        n = ErrorLog.query.filter_by(kind=kind).count()
        db.session.remove()
    return n


r = app.test_client().post('/api/email-events', base_url=PLATFORM,
                           json={'type': 'email.delivered', 'data': {'email_id': 'x'}})
check(r.status_code == 403 and logged('SignatureRefused') == 1,
      'an unsigned event is refused and logged as an error (a wrong secret looks like this)')
real_ok, real_record = api_bp_module._resend_signature_ok, delivery_events.record
api_bp_module._resend_signature_ok = lambda *a, **k: True


def cannot_save(*a, **k):
    raise delivery_events.Retry('database unavailable')


delivery_events.record = cannot_save
try:
    r = app.test_client().post('/api/email-events', base_url=PLATFORM,
                               json={'type': 'email.delivered', 'data': {'email_id': 'x'}})
finally:
    api_bp_module._resend_signature_ok, delivery_events.record = real_ok, real_record
check(r.status_code == 503 and logged('EventNotSaved') == 1,
      'an event that could not be saved answers 503 for a retry, and is logged separately')

if failures:
    print(f'\n❌ {len(failures)} failed')
    sys.exit(1)
print('\n✅ all passed')
