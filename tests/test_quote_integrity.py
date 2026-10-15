"""A commercial quote, once sent, is what the customer was offered -- and an
acceptance either happens completely or not at all.

From the quotation-to-contract integrity audit (2026-10-15), each of these
was possible before:
  * a sent quote's price changed under the link the customer already had,
    so they could accept terms nobody had sent them (F1);
  * an accepted quote deleted outright (F2);
  * a draft nobody sent accepted by posting to its link (F3);
  * an acceptance saved with no account behind it when a later step failed,
    the failure swallowed and the status forced through with raw SQL (F4);
  * two acceptances arriving together both counted.

Against a disposable Postgres, like the rest of the multi-company suite.
"""
import json
import os
import pathlib
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import fresh_postgres  # a multi-company app needs PostgreSQL schemas
os.environ['DATABASE_URL'] = fresh_postgres.url('dsm_test_quote_integrity')
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['FLASK_ENV'] = 'development'

import notifications
SENT = []
notifications.send_email = lambda *a, **k: (SENT.append(k) or (True, 'stub'))
notifications.send_sms = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
from models import CommercialAccount, CommercialQuote
import blueprints.quotes as Q
import provisioning
import tenancy

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


SLUG = 'qint'
HOST = f'http://{SLUG}.akye.test'
with app.app_context():
    provisioning.provision(SLUG, 'Quote Integrity Cleaning', quiet=True)
    db.session.remove()
fresh_postgres.set_company_plan(SLUG, 'scale')
c = fresh_postgres.owner_client(app, SLUG, 'akye.test')
LINES = {'areas': [{'name': 'Lobby', 'subtotal': 120, 'lines': [
    {'item': 'custom', 'label': 'Lobby floors', 'qty': 1, 'unit': 'visit', 'price': 120, 'override': True}]}],
    'per_visit': 120, 'monthly': 516}


def in_tenant(fn):
    with app.app_context(), tenancy.use_tenant(SLUG):
        try:
            return fn()
        finally:
            db.session.remove()


def make(company, status='draft', token=None, price=516):
    def go():
        q = CommercialQuote(company=company, contact_name='Pat Buyer', email='pat@buyer.example',
                            property_type='Office Building', property_address='9 Main St',
                            frequency='weekly', contract_term='12_months', services='Floors',
                            price_per_visit=120, monthly_price=price, status=status,
                            token=token or f'tok-{company.lower().replace(" ", "-")}',
                            line_items=json.dumps(LINES))
        db.session.add(q)
        db.session.commit()
        return q.id, q.token
    return in_tenant(go)


def quote(qid):
    def go():
        q = db.session.get(CommercialQuote, qid)
        return None if q is None else {k: getattr(q, k) for k in (
            'status', 'monthly_price', 'company', 'line_items', 'withdrawn_at', 'revised_from_id',
            'responded_at', 'token')}
    return in_tenant(go)


def accounts(company):
    return in_tenant(lambda: CommercialAccount.query.filter_by(business_name=company).count())


def public(token, action=None):
    cl = app.test_client()
    if action:
        return cl.post(f'/quotes/view/{token}/{action}', base_url=HOST)
    return cl.get(f'/quotes/view/{token}', base_url=HOST)


TAMPER = {'company': 'Tampered Co', 'contact_name': 'Pat Buyer', 'email': 'pat@buyer.example',
          'property_type': 'Office Building', 'frequency': 'weekly', 'contract_term': '12_months',
          'price_per_visit': '1', 'monthly_price': '1'}


print('\n1. A sent quote is not changed under the customer\'s link (F1)')
sid, stok = make('Sent Co', status='sent')
before = quote(sid)
r1 = c.post(f'/quotes/{sid}', base_url=HOST, data=TAMPER)
r2 = c.post(f'/quotes/{sid}/review', base_url=HOST, data=TAMPER)
n = len(SENT)
r3 = c.post(f'/quotes/{sid}/send', base_url=HOST, data=TAMPER)
after = quote(sid)
check(after['company'] == 'Sent Co' and float(after['monthly_price']) == 516 and after['line_items'] == before['line_items'],
      'not by its edit form, its review page, or the form the Send button posts')
check(len(SENT) > n and float(after['monthly_price']) == 516,
      'Resend goes out with exactly the terms they already have')
flash = c.get(f'/quotes/{sid}', base_url=HOST).get_data(as_text=True)
check('terms are fixed' in flash and 'quoteLocked' in flash and 'Save draft' not in flash,
      'the edit page says why, shows the terms read-only, and offers Revise or Withdraw')
check('$516' in public(stok).get_data(as_text=True).replace(',', ''), 'and the link still shows what was sent')


print('\n2. Revising: a new draft and a new link; the old one withdrawn')
r = c.post(f'/quotes/{sid}/revise', base_url=HOST)
nid = int(r.headers['Location'].rstrip('/').split('/')[-1])
old, new = quote(sid), quote(nid)
check(old['status'] == 'withdrawn' and old['withdrawn_at'] is not None,
      'the sent version is withdrawn in the same step')
check(new['status'] == 'draft' and new['revised_from_id'] == sid and new['token'] != stok
      and new['line_items'] == before['line_items'] and float(new['monthly_price']) == 516,
      'and the revision starts from exactly the terms that were sent -- not re-priced -- with its own link')
page = public(stok).get_data(as_text=True)
check('no longer open' in page and f'/quotes/view/{stok}/accept' not in page,
      'the old link says the proposal is no longer open, with nothing to accept')
r = public(stok, 'accept')
check(r.status_code == 302 and quote(sid)['status'] == 'withdrawn' and accounts('Sent Co') == 0,
      'and posting to it anyway accepts nothing')
c.post(f'/quotes/{nid}', base_url=HOST, data=dict(TAMPER, company='Sent Co', monthly_price='600'))
check(float(quote(nid)['monthly_price']) == 600, 'the revision, a draft, is edited as normal')


print('\n3. Withdrawing')
wid, wtok = make('Withdraw Co', status='sent')
c.post(f'/quotes/{wid}/withdraw', base_url=HOST)
r = public(wtok, 'accept')
check(quote(wid)['status'] == 'withdrawn' and accounts('Withdraw Co') == 0,
      'a withdrawn offer cannot be accepted')
n = len(SENT)
c.post(f'/quotes/{wid}/send', base_url=HOST)
check(quote(wid)['status'] == 'withdrawn' and len(SENT) == n, 'nor sent again under the same link')


print('\n4. Only a draft is deleted (F2)')
for status in ('sent', 'accepted', 'declined', 'withdrawn'):
    xid, _t = make(f'Keep {status}', status=status)
    c.post(f'/quotes/{xid}/delete', base_url=HOST)
    check(quote(xid) is not None, f'a {status} quote is kept as the record of what was offered')
did, _t = make('Scratch Draft')
c.post(f'/quotes/{did}/delete', base_url=HOST)
check(quote(did) is None, 'a draft can still be thrown away')


print('\n5. Only a sent quote is answered (F3)')
drid, drtok = make('Draft Only Co')
r = public(drtok, 'accept')
check(r.status_code == 302 and quote(drid)['status'] == 'draft' and accounts('Draft Only Co') == 0,
      'a draft nobody sent cannot be accepted by posting to its link')
public(drtok, 'decline')
check(quote(drid)['status'] == 'draft', 'or declined')
check(f'/quotes/view/{drtok}/accept' not in public(drtok).get_data(as_text=True),
      'and its preview has no Accept button')
dcid, dctok = make('Declined Co', status='declined')
public(dctok, 'accept')
check(quote(dcid)['status'] == 'declined' and accounts('Declined Co') == 0,
      'a declined quote cannot be accepted afterwards')
n = len(SENT)
c.post(f'/quotes/{dcid}/send', base_url=HOST)
check(quote(dcid)['status'] == 'declined' and len(SENT) == n,
      'nor re-sent under the link they declined -- a new offer is a revision')
r = c.post(f'/quotes/{dcid}/revise', base_url=HOST)
check(quote(dcid)['status'] == 'declined' and r.status_code == 302, 'which a declined quote can have')


print('\n6. Accepting is all or nothing (F4)')
aid, atok = make('Atomic Co', status='sent')
real = Q._account_from_quote
def broken(q):
    real(q)
    raise RuntimeError('account step failed')
Q._account_from_quote = broken
n = len(SENT)
r = public(atok, 'accept')
Q._account_from_quote = real
check(r.status_code == 503 and "couldn't record" in r.get_data(as_text=True),
      'when a step fails, the customer is told it was not recorded and to try again')
check(quote(aid)['status'] == 'sent' and quote(aid)['responded_at'] is None and accounts('Atomic Co') == 0
      and len(SENT) == n,
      'and nothing was saved: still open, no half-made account, no "accepted" email to the owner')
r = public(atok, 'accept')
check(r.status_code == 200 and quote(aid)['status'] == 'accepted' and accounts('Atomic Co') == 1,
      'trying again then works')

eid, etok = make('Email Down Co', status='sent')
real_send = Q.send_email
def down(**kw):
    raise RuntimeError('mail provider down')
Q.send_email = down
r = public(etok, 'accept')
Q.send_email = real_send
check(r.status_code == 200 and quote(eid)['status'] == 'accepted' and accounts('Email Down Co') == 1,
      'the owner\'s email failing after it is saved does not undo -- or hide -- an acceptance')


print('\n7. Two acceptances, one agreement')
did2, dtok2 = make('Double Tap Co', status='sent')
first = public(dtok2, 'accept')
second = public(dtok2, 'accept')
check(first.status_code == 200 and second.status_code == 302 and accounts('Double Tap Co') == 1,
      'a second press is a no-op, not a second account')

cid, ctok = make('Race Co', status='sent')
results, gate = [], threading.Barrier(4)
def press():
    cl = app.test_client()
    gate.wait()
    results.append(cl.post(f'/quotes/view/{ctok}/accept', base_url=HOST).status_code)
threads = [threading.Thread(target=press) for _ in range(4)]
[t.start() for t in threads]
[t.join() for t in threads]
check(sorted(results).count(200) == 1 and accounts('Race Co') == 1 and quote(cid)['status'] == 'accepted',
      f'four at once: exactly one counts, one account ({sorted(results)})')

rid, rtok = make('Accept Then Withdraw Co', status='sent')
public(rtok, 'accept')
c.post(f'/quotes/{rid}/withdraw', base_url=HOST)
c.post(f'/quotes/{rid}/revise', base_url=HOST)
check(quote(rid)['status'] == 'accepted',
      'an owner withdrawing or revising just after the customer accepted cannot undo the acceptance')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ A sent quote stays what was sent, and an acceptance is complete or not at all.')
