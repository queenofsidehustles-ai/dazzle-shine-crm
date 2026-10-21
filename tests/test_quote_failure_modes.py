"""G3: an acceptance happens completely or not at all -- when a step fails
part-way, when the owner withdraws the offer at the same moment, and when the
offer closes between the page being checked and the answer being written.

From the GREEN remediation plan (2026-10-16), section 4. test_quote_integrity
covers simultaneous acceptances and a failing email; this covers the rest:

  * a failure injected at each write an acceptance makes -- the account, the
    agreement, the audit entries -- rolls the whole answer back: the quote is
    still open, no answer, agreement or account is left behind, the failure
    is on the trail, and the customer can simply try again;
  * accept and withdraw pressed together, repeatedly: exactly one wins, and
    the records agree with whichever did;
  * the offer's closing date passing after the checks but before the answer
    is written: refused, by the write itself.

Against a disposable Postgres, like the rest of the multi-company suite.
"""
import os
import pathlib
import sys
import threading
from datetime import datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import fresh_postgres
from quote_answer import shown_hash
os.environ['DATABASE_URL'] = fresh_postgres.url('dsm_test_quote_failure_modes')
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['FLASK_ENV'] = 'development'

import notifications
notifications.send_email = lambda *a, **k: (True, 'stub (id re_fail)')
notifications.send_sms = lambda *a, **k: (True, 'stub')

import sqlalchemy as sa
from sqlalchemy import text
from app import create_app
from extensions import db
from models import (CommercialAccount, CommercialAgreement, CommercialQuote, ContractAuditEvent,
                    QuoteResponse)
import blueprints.quotes as Q
import provisioning
import tenancy

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


SLUG = 'qfail'
HOST = f'http://{SLUG}.akye.test'
with app.app_context():
    provisioning.provision(SLUG, 'Failure Modes Cleaning', quiet=True)
    db.session.remove()
fresh_postgres.set_company_plan(SLUG, 'scale')
owner = fresh_postgres.owner_client(app, SLUG, 'akye.test')
FORM = {'contact_name': 'Pat Buyer', 'email': 'pat@buyer.example', 'property_type': 'Office Building',
        'property_address': '9 Main St', 'frequency': 'weekly', 'contract_term': 'annual',
        'services': ['Office Cleaning'], 'price_per_visit': '120', 'monthly_price': '516'}


def in_tenant(fn):
    with app.app_context(), tenancy.use_tenant(SLUG):
        try:
            return fn()
        finally:
            db.session.remove()


def sent_quote(company, cl=None):
    cl = cl or owner
    cl.post('/quotes/new', base_url=HOST, data=dict(FORM, company=company))
    qid, tok = in_tenant(lambda: (lambda q: (q.id, q.token))(
        CommercialQuote.query.filter_by(company=company).first()))
    cl.post(f'/quotes/{qid}/send', base_url=HOST)
    return qid, tok


def state(qid, company):
    def go():
        q = db.session.get(CommercialQuote, qid)
        return {'status': q.status,
                'responses': QuoteResponse.query.filter_by(quote_id=qid).count(),
                'agreements': CommercialAgreement.query.filter_by(quote_id=qid).count(),
                'accounts': CommercialAccount.query.filter_by(business_name=company).count(),
                'events': [e.event for e in ContractAuditEvent.query.filter_by(quote_id=qid)
                           .order_by(ContractAuditEvent.id)]}
    return in_tenant(go)


def accept(tok, cl=None, terms=None):
    cl = cl or app.test_client()
    return cl.post(f'/quotes/view/{tok}/accept', base_url=HOST,
                   data={'terms_hash': terms or shown_hash(cl, tok, HOST), 'signer_name': 'Pat Buyer'})


print('\n1. A failure at any write rolls the whole acceptance back')


def failing_at(model, when=lambda target: True):
    def boom(mapper, connection, target):
        if when(target):
            raise RuntimeError(f'injected: {model.__tablename__} insert failed')
    return model, boom


for label, (model, boom) in (
        ('the account', failing_at(CommercialAccount)),
        ('the agreement', failing_at(CommercialAgreement)),
        ('the audit entry', failing_at(ContractAuditEvent, lambda t: t.event in ('accepted', 'agreement_executed'))),
        ('the answer', failing_at(QuoteResponse))):
    company = f'Fault {label.split()[-1].title()} Co'
    qid, tok = sent_quote(company)
    sa.event.listen(model, 'before_insert', boom)
    try:
        r = accept(tok)
    finally:
        sa.event.remove(model, 'before_insert', boom)
    s = state(qid, company)
    check(r.status_code == 503 and s['status'] == 'sent' and s['responses'] == 0
          and s['agreements'] == 0 and s['accounts'] == 0 and 'accepted' not in s['events'],
          f'{label} fails: nothing is kept, and the offer is still open ({s["status"]}, {r.status_code})')
    check('answer_failed' in s['events'], f'{label} fails: the trail says the answer was not recorded')
    r = accept(tok)
    s = state(qid, company)
    check(r.status_code == 200 and s['status'] == 'accepted' and s['responses'] == 1
          and s['agreements'] == 1 and s['accounts'] == 1,
          f'{label}: trying again works, once')

print('\n2. Accept and withdraw pressed together: exactly one wins, every time')
outcomes = []
for i in range(8):
    company = f'Race {i} Co'
    qid, tok = sent_quote(company)
    terms = shown_hash(app.test_client(), tok, HOST)
    gate = threading.Barrier(2)
    customer = app.test_client()
    boss = fresh_postgres.owner_client(app, SLUG, 'akye.test')

    def do_accept():
        gate.wait()
        accept(tok, customer, terms)

    def do_withdraw():
        gate.wait()
        boss.post(f'/quotes/{qid}/withdraw', base_url=HOST)

    ts = [threading.Thread(target=do_accept), threading.Thread(target=do_withdraw)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    s = state(qid, company)
    accepted = (s['status'] == 'accepted' and s['responses'] == 1 and s['agreements'] == 1
                and s['accounts'] == 1 and 'withdrawn' not in s['events'])
    withdrawn = (s['status'] == 'withdrawn' and s['responses'] == 0 and s['agreements'] == 0
                 and s['accounts'] == 0 and 'accepted' not in s['events'])
    outcomes.append('accepted' if accepted else 'withdrawn' if withdrawn else f'BROKEN {s}')
check(all(o in ('accepted', 'withdrawn') for o in outcomes),
      f'one winner, and the records agree with it, in all 8 ({", ".join(outcomes)})')

print('\n3. The offer closing between the checks and the write')
company = 'Closing Co'
qid, tok = sent_quote(company)
terms = shown_hash(app.test_client(), tok, HOST)
engine = provisioning._engine()
schema = tenancy.schema_for(SLUG)
real_gaps = Q._binding_gaps


def close_now(*a, **k):
    """Runs after every check _answerable() makes, before the answer is
    written: the offer's closing date passes right here."""
    with engine.begin() as conn:
        conn.execute(text(f'UPDATE "{schema}".commercial_quote SET expires_at = :t WHERE id = :q'),
                     {'t': datetime.utcnow() - timedelta(seconds=1), 'q': qid})
    return real_gaps(*a, **k)


Q._binding_gaps = close_now
try:
    r = accept(tok, terms=terms)
finally:
    Q._binding_gaps = real_gaps
s = state(qid, company)
check(s['status'] == 'sent' and s['responses'] == 0 and s['agreements'] == 0 and s['accounts'] == 0,
      'the write itself refuses an offer that closed a moment ago')
check(s['events'][-1:] == ['answer_refused'], 'and the trail records the refusal')

if failures:
    print(f'\n❌ {len(failures)} failed')
    sys.exit(1)
print('\n✅ all passed')
