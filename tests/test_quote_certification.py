"""Every quote route, tried by everyone who should not get through.

The integrity audit (2026-10-15) asked for adversarial certification of the
quotation flow: tenant isolation across all quote routes, and sales/owner
permissions enforced. This walks the quotes blueprint itself -- so a route
added later is either classified here or fails this test -- and tries each
one as:

  * nobody signed in;
  * a Sales login and a Cleaner login of the same company;
  * another company's owner, with that company's session replayed against
    this company's address;
  * another company's owner on their own address, asking for this company's
    quote by id, and its customer link by token.

None may read a quote, and none of their posts may change one: the database
is compared before and after, row counts and quote states, along with the
emails sent.

Against a disposable Postgres, like the rest of the multi-company suite.
"""
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import fresh_postgres  # a multi-company app needs PostgreSQL schemas
from quote_answer import answer, shown_hash
os.environ['DATABASE_URL'] = fresh_postgres.url('dsm_test_quote_certification')
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['FLASK_ENV'] = 'development'

import notifications
SENT = []
notifications.send_email = lambda *a, **k: (SENT.append(k) or (True, 'stub (id re_cert)'))
notifications.send_sms = lambda *a, **k: (True, 'stub')

from sqlalchemy import text
from app import create_app
from auth import _auth_fingerprint
from extensions import db
from models import CommercialQuote, User
import provisioning
import tenancy

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


A, B = 'certa', 'certb'
HOST_A, HOST_B = f'http://{A}.akye.test', f'http://{B}.akye.test'
for slug, name in ((A, 'Cert A Cleaning'), (B, 'Cert B Cleaning')):
    with app.app_context():
        provisioning.provision(slug, name, quiet=True)
        db.session.remove()
    fresh_postgres.set_company_plan(slug, 'scale')
owner_a = fresh_postgres.owner_client(app, A, 'akye.test')
owner_b = fresh_postgres.owner_client(app, B, 'akye.test')
FORM = {'contact_name': 'Pat Private', 'email': 'pat@private.example', 'property_type': 'Office Building',
        'property_address': '1 Secret St', 'frequency': 'weekly', 'contract_term': 'annual',
        'services': ['Office Cleaning'], 'price_per_visit': '120', 'monthly_price': '516'}

# Company A: a draft, a sent quote, and an accepted one -- each the target of
# routes that act on that state. Several, so A's ids run past B's.
for name in ('Alpha Draft Holdings', 'Alpha Sent Holdings', 'Alpha Signed Holdings'):
    owner_a.post('/quotes/new', base_url=HOST_A, data=dict(FORM, company=name))


def quote_id(slug, company):
    with app.app_context(), tenancy.use_tenant(slug):
        q = CommercialQuote.query.filter_by(company=company).first()
        out = (q.id, q.token)
        db.session.remove()
    return out


DRAFT, _ = quote_id(A, 'Alpha Draft Holdings')
SENT_Q, SENT_TOK = quote_id(A, 'Alpha Sent Holdings')
SIGNED, SIGNED_TOK = quote_id(A, 'Alpha Signed Holdings')
owner_a.post(f'/quotes/{SENT_Q}/send', base_url=HOST_A)
owner_a.post(f'/quotes/{SIGNED}/send', base_url=HOST_A)
answer(app.test_client(), SIGNED_TOK, HOST_A, 'accept', name='Pat Private')
owner_b.post('/quotes/new', base_url=HOST_B, data=dict(FORM, company='Beta Own Quote'))


def login(slug, role, name, host):
    """A client signed in as a fresh `role` login of company `slug`, its
    session cookie set for `host`."""
    with app.app_context(), tenancy.use_tenant(slug):
        u = User.query.filter_by(username=f'{role}@{slug}.test').first()
        if u is None:
            u = User(name=name, username=f'{role}@{slug}.test', role=role, active=True)
            u.set_password('a-perfectly-fine-password')
            db.session.add(u)
            db.session.commit()
        uid, fp = u.id, _auth_fingerprint(u.password_hash)
        db.session.remove()
    cl = app.test_client()
    with cl.session_transaction(base_url=host) as sess:
        sess.update(logged_in=True, role=role, user_id=uid, user_name=name,
                    auth_fingerprint=fp, tenant_slug=slug)
    return cl


def owner_of(slug, host):
    """Company `slug`'s owner session, presented at `host`."""
    with app.app_context(), tenancy.use_tenant(slug):
        u = User.query.filter_by(username=f'owner@{slug}.test').first()
        uid, fp = u.id, _auth_fingerprint(u.password_hash)
        db.session.remove()
    cl = app.test_client()
    with cl.session_transaction(base_url=host) as sess:
        sess.update(logged_in=True, role='owner', user_id=uid, user_name='Owner',
                    auth_fingerprint=fp, tenant_slug=slug)
    return cl


def snapshot():
    """Company A's quote evidence, as counts and states, plus emails sent."""
    with app.app_context(), tenancy.use_tenant(A):
        counts = tuple(db.session.execute(text(f'SELECT count(*) FROM {t}')).scalar() for t in (
            'commercial_quote', 'commercial_quote_revision', 'commercial_quote_delivery',
            'commercial_quote_response', 'commercial_agreement', 'commercial_account',
            'contract_audit_event'))
        states = tuple(db.session.execute(text(
            'SELECT id, status, monthly_price, company, withdrawn_at, issued_revision_id '
            'FROM commercial_quote ORDER BY id')).fetchall())
        db.session.remove()
    return counts, states, len(SENT)


print('\n1. Every quote route is classified')
PUBLIC = {'quotes.view', 'quotes.accept', 'quotes.decline'}
OWNER_ONLY = {'quotes.index', 'quotes.new', 'quotes.lines_json', 'quotes.detail', 'quotes.review',
              'quotes.document', 'quotes.circulate', 'quotes.send_quote', 'quotes.delete',
              'quotes.withdraw', 'quotes.revise', 'quotes.duplicate', 'quotes.amend'}
rules = [r for r in app.url_map.iter_rules() if r.endpoint.startswith('quotes.')]
seen = {r.endpoint for r in rules}
check(seen == PUBLIC | OWNER_ONLY,
      f'the routes are exactly the ones certified here (new: {sorted(seen - PUBLIC - OWNER_ONLY)}, '
      f'gone: {sorted((PUBLIC | OWNER_ONLY) - seen)})')


def target(rule):
    """(path, quote id it acts on) for A: state-changing routes aim at the
    quote whose state they would change."""
    ep = rule.endpoint
    qid = {'quotes.delete': DRAFT, 'quotes.send_quote': SENT_Q, 'quotes.withdraw': SENT_Q,
           'quotes.revise': SENT_Q, 'quotes.amend': SIGNED}.get(ep, SIGNED)
    path = re.sub(r'<int:quote_id>', str(qid), rule.rule)
    path = re.sub(r'<token>', SIGNED_TOK if ep == 'quotes.view' else SENT_TOK, path)
    return path, qid


def attempts(cl, host):
    """Every owner-only route, every method, as `cl` at `host`. Returns the
    responses that came back 200 with company A's data in them."""
    leaks = []
    for rule in rules:
        if rule.endpoint not in OWNER_ONLY:
            continue
        path, _qid = target(rule)
        for method in sorted((rule.methods or set()) - {'HEAD', 'OPTIONS'}):
            data = dict(FORM, company='Hijacked Co', monthly_price='1') if method == 'POST' else None
            r = cl.open(path, base_url=host, method=method, data=data)
            body = r.get_data(as_text=True)
            if r.status_code == 200 and ('Alpha' in body or 'Secret St' in body or 'Pat Private' in body):
                leaks.append(f'{method} {path} -> {r.status_code}')
            if method == 'POST' and r.status_code == 200 and rule.endpoint != 'quotes.lines_json':
                leaks.append(f'{method} {path} answered 200')
    return leaks


# The terms reference a real customer would post -- read now, since opening the
# link records a first view, and every later step must change nothing at all.
SENT_HASH = shown_hash(app.test_client(), SENT_TOK, HOST_A)

print('\n2. Nobody signed in, Sales and Cleaner logins: no quote page, no quote change')
before = snapshot()
actors = (('nobody signed in', app.test_client()),
          ('a Sales login', login(A, 'sales', 'Sam Sales', HOST_A)),
          ('a Cleaner login', login(A, 'cleaner', 'Cleo Cleaner', HOST_A)))
for label, cl in actors:
    leaks = attempts(cl, HOST_A)
    check(not leaks, f'{label}: every owner-only route refused ({leaks[:3]})')
check(snapshot() == before, 'and nothing they posted changed a quote, an answer, an account or the trail, or sent an email')
r = actors[0][1].get(f'/quotes/{SIGNED}', base_url=HOST_A)
check(r.status_code == 302 and '/login' in r.headers.get('Location', ''), 'signed-out visitors are sent to log in')

print('\n3. Another company\'s owner: neither a replayed session nor their own address reaches A')
cross = owner_of(B, HOST_A)
leaks = attempts(cross, HOST_A)
check(not leaks, f'B\'s owner session presented at A\'s address is refused everywhere ({leaks[:3]})')
check(snapshot() == before, 'and changes nothing at A')
for path in (f'/quotes/{SIGNED}', f'/quotes/{SIGNED}/review', f'/quotes/{SIGNED}/document'):
    r = owner_b.get(path, base_url=HOST_B)
    body = r.get_data(as_text=True)
    check(r.status_code == 404 and 'Alpha' not in body, f'on B\'s own address, {path} is not A\'s quote ({r.status_code})')
for what, tok in (('view', SIGNED_TOK), ('view', SENT_TOK)):
    r = app.test_client().get(f'/quotes/view/{tok}', base_url=HOST_B)
    check(r.status_code == 404 and 'Alpha' not in r.get_data(as_text=True),
          'A\'s customer link does not open at B\'s address')
r = app.test_client().post(f'/quotes/view/{SENT_TOK}/accept', base_url=HOST_B,
                           data={'signer_name': 'Mallory', 'terms_hash': SENT_HASH})
check(r.status_code == 404 and snapshot() == before, 'nor accepts at B\'s address')
r = owner_b.post(f'/quotes/{SENT_Q}/withdraw', base_url=HOST_B)
check(r.status_code == 404 and snapshot() == before, 'and B withdrawing "quote #%d" touches nothing of A\'s' % SENT_Q)

print('\n4. The public routes take a token, never an id, and only their own company\'s')
for ep in sorted(PUBLIC):
    rule = next(r for r in rules if r.endpoint == ep)
    check('<token>' in rule.rule and 'quote_id' not in rule.rule, f'{ep} is addressed by its unguessable token')
r = app.test_client().get('/quotes/view/not-a-real-token', base_url=HOST_A)
check(r.status_code == 404, 'a made-up token finds nothing')
r = app.test_client().get(f'/quotes/view/{SENT_TOK}', base_url=HOST_A)
check(r.status_code == 200 and 'Alpha Sent Holdings' in r.get_data(as_text=True),
      'and the real one, at its own company\'s address, works -- these checks are not refusing everything')
r = owner_a.get(f'/quotes/{SIGNED}/review', base_url=HOST_A)
check(r.status_code == 200 and 'Alpha Signed Holdings' in r.get_data(as_text=True),
      'as does the owner\'s own review')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ Every quote route refuses everyone but its own company\'s owner -- and the customer, by token.')
