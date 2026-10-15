"""After a quote is accepted: the agreement, its amendments, what the mail
service said, and the trail of who did what.

From the quotation-to-contract integrity audit (2026-10-15), still open after
#90 and #91:
  * no executed-agreement record tying the accepted revision, the answer and
    the account together;
  * no way to change an accepted agreement except a fresh, unlinked quote --
    and nothing to say which terms were in force on a given day;
  * "sent" meant only that the mail service took it; a bounce looked the same;
  * no audit trail: who sent, viewed, accepted, or tried to.

Against a disposable Postgres, like the rest of the multi-company suite.
"""
import base64
import hashlib
import hmac
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import fresh_postgres  # a multi-company app needs PostgreSQL schemas
from quote_answer import answer, shown_hash
os.environ['DATABASE_URL'] = fresh_postgres.url('dsm_test_contract_trail')
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['FLASK_ENV'] = 'development'
WEBHOOK_KEY = b'contract-trail-test-signing-key!'
os.environ['RESEND_EVENTS_WEBHOOK_SECRET'] = 'whsec_' + base64.b64encode(WEBHOOK_KEY).decode()

import notifications
REAL_SEND = notifications.send_email
SENT = []
NEXT_ID = []                      # set to choose the provider id the next send gets
_counter = iter(range(1, 100000))


def _fake_send(*a, **k):
    SENT.append(k)
    return True, f'Accepted by Resend (id {NEXT_ID.pop() if NEXT_ID else f"re_msg_{next(_counter)}"}).'


notifications.send_email = _fake_send
notifications.send_sms = lambda *a, **k: (True, 'stub')

from sqlalchemy import text
from app import create_app
from extensions import db
from models import (CommercialAccount, CommercialAgreement, CommercialQuote, ContractAuditEvent,
                    OutboundLog, QuoteDelivery, EmailDeliveryEvent, QuoteResponse)
import provisioning
import tenancy

app = create_app()
failures = []
import delivery_events


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


SLUG = 'trail'
SCHEMA = tenancy.schema_for(SLUG)
HOST = f'http://{SLUG}.akye.test'
PLATFORM = 'http://akye.test'
with app.app_context():
    provisioning.provision(SLUG, 'Trail Cleaning', quiet=True)
    db.session.remove()
fresh_postgres.set_company_plan(SLUG, 'scale')
c = fresh_postgres.owner_client(app, SLUG, 'akye.test')
FORM = {'company': 'Agreed Co', 'contact_name': 'Ann Agreed', 'email': 'ann@agreed.example',
        'property_type': 'Office Building', 'property_address': '1 Main St',
        'frequency': 'weekly', 'contract_term': 'annual', 'services': ['Office Cleaning'],
        'price_per_visit': '120', 'monthly_price': '516'}


def in_tenant(fn):
    with app.app_context(), tenancy.use_tenant(SLUG):
        try:
            return fn()
        finally:
            db.session.remove()


def new_quote(**over):
    data = dict(FORM, **over)
    c.post('/quotes/new', base_url=HOST, data=data)
    return in_tenant(lambda: (lambda q: (q.id, q.token))(
        CommercialQuote.query.filter_by(company=data['company']).order_by(CommercialQuote.id.desc()).first()))


def get(model, **by):
    return in_tenant(lambda: model.query.filter_by(**by).order_by(model.id).all())


def events(qid):
    return [e.event for e in get(ContractAuditEvent, quote_id=qid)]


def sql(statement, **params):
    def go():
        try:
            db.session.execute(text(statement), params)
            db.session.commit()
            return None
        except Exception as e:
            db.session.rollback()
            return str(e)
    return in_tenant(go)


def webhook(payload, event_id=None, key=WEBHOOK_KEY, base=PLATFORM):
    body = json.dumps(payload).encode()
    mid, stamp = event_id or f'msg_{time.time_ns()}', str(int(time.time()))
    sig = base64.b64encode(hmac.new(key, f'{mid}.{stamp}.'.encode() + body, hashlib.sha256).digest()).decode()
    return app.test_client().post('/api/email-events', base_url=base, data=body,
                                  content_type='application/json',
                                  headers={'svix-id': mid, 'svix-timestamp': stamp, 'svix-signature': f'v1,{sig}'})


print('\n1. Accepting executes an agreement, and the trail says how it got there')
qid, tok = new_quote()
c.post(f'/quotes/{qid}/send', base_url=HOST)
cust = app.test_client()
cust.get(f'/quotes/view/{tok}', base_url=HOST)
h = shown_hash(cust, tok, HOST)
answer(cust, tok, HOST, 'accept', name='Ann Agreed', terms_hash='f' * 64)
answer(cust, tok, HOST, 'accept', name='', terms_hash=h)
answer(cust, tok, HOST, 'accept', name='Ann Agreed', title='Office Manager', terms_hash=h)
answer(app.test_client(), tok, HOST, 'accept', name='Second Tap', terms_hash=h)
ag = get(CommercialAgreement, quote_id=qid)
resp = get(QuoteResponse, quote_id=qid)
q = in_tenant(lambda: db.session.get(CommercialQuote, qid))
check(len(ag) == 1 and resp and ag[0].response_id == resp[0].id and ag[0].revision_id == q.issued_revision_id
      and ag[0].account_id == q.account_id and ag[0].content_hash == resp[0].content_hash
      and ag[0].effective_on is not None and ag[0].amends_agreement_id is None,
      'one agreement: the accepted revision, the signed answer and the account, from the day of acceptance')
ev = events(qid)
check(ev[:4] == ['created', 'sent', 'viewed', 'answer_refused'] and ev.count('answer_refused') == 3
      and 'accepted' in ev and ev[-1] == 'answer_refused' and 'agreement_executed' in ev,
      f'the trail: created, sent, viewed, the refused tries, accepted, executed, the late tap ({ev})')
rows = get(ContractAuditEvent, quote_id=qid)
reasons = [json.loads(e.detail or '{}').get('reason') for e in rows if e.event == 'answer_refused']
check(reasons == ['stale_terms', 'no_name', 'not_open'],
      f'each refusal says why: stale terms, no name, already answered ({reasons})')
sent = next(e for e in rows if e.event == 'sent')
acc_ev = next(e for e in rows if e.event == 'accepted')
check(sent.actor_kind == 'staff' and sent.actor and sent.revision_id == q.issued_revision_id
      and json.loads(sent.detail)['recipient'] == 'ann@agreed.example',
      'a send names who sent it, which version, and to whom')
check(acc_ev.actor_kind == 'customer' and acc_ev.actor == 'Ann Agreed' and acc_ev.ip_address
      and acc_ev.request_id and json.loads(acc_ev.detail)['content_hash'] == h,
      'an acceptance names the signer, the IP, the request and the terms')
same_request = [e for e in rows if e.request_id == acc_ev.request_id]
check({e.event for e in same_request} == {'accepted', 'agreement_executed'},
      'and the agreement is recorded in the same request as the answer')

print('\n2. The agreement and the trail cannot be rewritten')
err = sql('UPDATE commercial_agreement SET account_id = 999 WHERE id = :i', i=ag[0].id)
check(err and 'never changed' in err, 'the database refuses to edit an agreement')
err = sql('UPDATE contract_audit_event SET actor = :a WHERE quote_id = :q', a='someone else', q=qid)
check(err and 'never changed' in err, 'or the trail')
err = sql('DELETE FROM commercial_agreement WHERE id = :i', i=ag[0].id)
check(err and 'never deleted' in err and get(CommercialAgreement, quote_id=qid),
      'nor delete one')
err = sql('DELETE FROM contract_audit_event WHERE quote_id = :q', q=qid)
check(err and 'never deleted' in err and events(qid), 'or any of the trail')
err = sql('DELETE FROM commercial_quote_response WHERE quote_id = :q', q=qid)
check(err and get(QuoteResponse, quote_id=qid), 'or the customer\'s answer')


def orm_edit():
    a = db.session.get(CommercialAgreement, ag[0].id)
    a.account_id = 999
    try:
        db.session.commit()
        return False
    except ValueError:
        db.session.rollback()
        return True


check(in_tenant(orm_edit), 'and the app refuses to try')

print('\n3. An agreement is changed by amending it -- and the old one is kept')
acc_id = q.account_id
r = c.post(f'/quotes/{qid}/amend', base_url=HOST)
amd = in_tenant(lambda: CommercialQuote.query.filter_by(amends_agreement_id=ag[0].id).first())
check(amd is not None and amd.status == 'draft' and amd.revised_from_id == qid and amd.account_id == acc_id
      and float(amd.monthly_price) == 516 and amd.services == 'Office Cleaning',
      'Amend opens a draft starting from exactly the agreed terms, for the same account')
r = c.post(f'/quotes/{qid}/amend', base_url=HOST, follow_redirects=True)
check(in_tenant(lambda: CommercialQuote.query.filter_by(amends_agreement_id=ag[0].id).count()) == 1
      and 'already open' in r.get_data(as_text=True),
      'one amendment open at a time, so the terms cannot fork')
page = c.get(f'/quotes/{amd.id}', base_url=HOST).get_data(as_text=True)
check('An amendment to' in page and 'stays in force' in page, 'the draft says what it amends')
c.post(f'/quotes/{amd.id}', base_url=HOST, data=dict(FORM, monthly_price='600', price_per_visit='140'))
c.post(f'/quotes/{amd.id}/send', base_url=HOST)
page = app.test_client().get(f'/quotes/view/{tok}', base_url=HOST).get_data(as_text=True)
check('You accepted this proposal' in page and 'replaced' not in page,
      'until the amendment is accepted, the original is the agreement in force')
answer(app.test_client(), amd.token, HOST, 'accept', name='Ann Agreed')
ags = get(CommercialAgreement, account_id=acc_id)
check(len(ags) == 2 and ags[1].quote_id == amd.id and ags[1].amends_agreement_id == ags[0].id,
      'accepting it executes a second agreement that names the one it replaces')
old = in_tenant(lambda: db.session.get(CommercialQuote, qid))
check(old.status == 'accepted' and ags[0].content_hash == h and get(QuoteResponse, quote_id=qid)[0].signer_title == 'Office Manager',
      'the original quote, its answer and its agreement are exactly as they were')
acc = in_tenant(lambda: db.session.get(CommercialAccount, acc_id))
check(float(acc.billing_amount) == 600 and in_tenant(lambda: CommercialAccount.query.count()) == 1,
      'the account takes the amended terms -- the same account, not a new one')
page = app.test_client().get(f'/quotes/view/{tok}', base_url=HOST).get_data(as_text=True)
check('replaced by an amended agreement' in page, 'the old link says it has been replaced, and still shows what was agreed')
review = c.get(f'/quotes/{qid}/review', base_url=HOST).get_data(as_text=True)
check(f'Replaced by agreement #{ags[1].id}' in review and 'Amend this agreement' not in review,
      'the owner sees what replaced it, and is not offered to amend a replaced agreement')
r = c.post(f'/quotes/{qid}/amend', base_url=HOST, follow_redirects=True)
check('already been replaced' in r.get_data(as_text=True)
      and in_tenant(lambda: CommercialQuote.query.filter_by(amends_agreement_id=ag[0].id).count()) == 1,
      'and amending it anyway is refused: amend the latest one')
acct_page = c.get(f'/commercial/{acc_id}', base_url=HOST).get_data(as_text=True)
block = acct_page.split('id="accountAgreements"', 1)[-1].split('</div>', 1)[0]
check(block.count('in force') == 1 and block.count('replaced') >= 1 and '$600.00/mo' in block
      and f'Agreement #{ags[1].id}' in block,
      'the account lists its agreements: the one in force, and the one it replaced')
err = sql('INSERT INTO commercial_agreement (quote_id, revision_id, response_id, account_id, content_hash, '
          'effective_on, amends_agreement_id, created_at) SELECT :q, revision_id, id, account_id, content_hash, '
          'now(), :a, now() FROM commercial_quote_response WHERE quote_id = :q', q=qid, a=ag[0].id)
check(err is not None and len(get(CommercialAgreement, account_id=acc_id)) == 2,
      'the database itself allows one successor per agreement')

print('\n4. What the mail service said became of it')
dl = get(QuoteDelivery, quote_id=qid)[0]
check(dl.provider_message_id and dl.provider_message_id.startswith('re_msg_'), 'the send kept the provider\'s message id')
in_tenant(lambda: (db.session.add(OutboundLog(channel='email', to_address='ann@agreed.example', status='sent',
                                              provider_id=dl.provider_message_id)), db.session.commit()))


def ev(kind, mid, to=('ann@agreed.example',), when=None, **data):
    return {'type': f'email.{kind}', 'created_at': when or '2026-10-15T12:00:00.000Z',
            'data': dict({'email_id': mid, 'to': list(to), 'tags': {'tenant': SCHEMA}}, **data)}


delivered = ev('delivered', dl.provider_message_id)
r = webhook(delivered, event_id='evt_delivered_1')
check(r.status_code == 200 and r.get_json()['outcome'] == 'recorded', f'a signed "delivered" is taken ({r.get_data(as_text=True)[:80]})')
r = webhook(delivered, event_id='evt_delivered_1')
evs = get(EmailDeliveryEvent, provider_message_id=dl.provider_message_id)
check(r.get_json()['outcome'] == 'duplicate' and len(evs) == 1 and evs[0].event == 'delivered'
      and evs[0].occurred_at.hour == 12 and evs[0].recipient == 'ann@agreed.example',
      'recorded once, for its recipient, though the service sent it twice')
log = get(OutboundLog, provider_id=dl.provider_message_id)[0]
check(log.status == 'delivered', 'and the Sent log says delivered, not just sent')
check('delivered' in events(qid), 'the trail notes it, from the mail service')
review = c.get(f'/quotes/{qid}/review', base_url=HOST).get_data(as_text=True)
check('✅ Delivered' in review, 'the owner\'s record shows it delivered')

webhook(ev('complained', dl.provider_message_id, when='2026-10-15T13:00:00.000Z'), event_id='evt_complained_1')
r = webhook(delivered, event_id='evt_delivered_1')
webhook(ev('delivered', dl.provider_message_id, when='2026-10-15T11:00:00.000Z'), event_id='evt_delivered_late')
log = get(OutboundLog, provider_id=dl.provider_message_id)[0]
check(r.get_json()['outcome'] == 'duplicate' and log.status == 'complained',
      'an old event replayed, or a late one, never moves the Sent log backwards (complained stays complained)')

in_tenant(lambda: (db.session.add(OutboundLog(channel='email', to_address='cust@cc.example', status='sent',
                                              provider_id='re_cc_1')), db.session.commit()))
webhook(ev('bounced', 're_cc_1', to=('owner-copy@cc.example',), bounce={'message': 'No such user'}))
check(get(OutboundLog, provider_id='re_cc_1')[0].status == 'sent',
      'a bounce at a copied address is not the customer\'s bounce')

bq_id, bq_tok = new_quote(company='Bounce Co', email='nobody@bounce.example')
c.post(f'/quotes/{bq_id}/send', base_url=HOST)
bdl = get(QuoteDelivery, quote_id=bq_id)[0]
webhook(ev('bounced', bdl.provider_message_id, to=('nobody@bounce.example',),
           bounce={'type': 'Permanent', 'message': 'Mailbox does not exist'}))
bev = get(EmailDeliveryEvent, provider_message_id=bdl.provider_message_id)
review = c.get(f'/quotes/{bq_id}/review', base_url=HOST).get_data(as_text=True)
check(bev and bev[0].event == 'bounced' and 'Mailbox does not exist' in bev[0].detail
      and 'Bounced' in review and 'Mailbox does not exist' in review,
      'a bounce is recorded with its reason, and the owner sees the proposal never arrived')

eq_id, eq_tok = new_quote(company='Early Co', email='early@early.example')
r = webhook(ev('delivered', 're_early_1', to=('early@early.example',)), event_id='evt_early_1')
check(r.status_code == 200 and get(EmailDeliveryEvent, provider_message_id='re_early_1'),
      'an event that arrives before its send has finished saving is kept, not dropped')
NEXT_ID.append('re_early_1')
c.post(f'/quotes/{eq_id}/send', base_url=HOST)
review = c.get(f'/quotes/{eq_id}/review', base_url=HOST).get_data(as_text=True)
early = [e for e in get(ContractAuditEvent, quote_id=eq_id) if e.event == 'delivered']
check('✅ Delivered' in review and early and json.loads(early[0].detail).get('arrived_before_send_committed'),
      'and once the send is saved, its record and trail show it delivered')

real_file = delivery_events._file
delivery_events._file = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('database went away'))
r = webhook(ev('delivered', 're_retry_1', to=('x@retry.example',)), event_id='evt_retry_1')
delivery_events._file = real_file
check(r.status_code == 503 and not get(EmailDeliveryEvent, provider_message_id='re_retry_1'),
      'an event we failed to save is answered 503, so the service sends it again')
r = webhook(ev('delivered', 're_retry_1', to=('x@retry.example',)), event_id='evt_retry_1')
check(r.status_code == 200 and len(get(EmailDeliveryEvent, provider_message_id='re_retry_1')) == 1,
      'and the retry is recorded')

r = webhook(delivered, key=b'not-the-real-signing-key-at-all!')
check(r.status_code == 403, 'an unsigned or wrongly signed event is refused')
r = app.test_client().post('/api/email-events', base_url=PLATFORM, json=delivered)
check(r.status_code == 403, 'including one with no signature at all')
n = len(get(EmailDeliveryEvent, provider_message_id=dl.provider_message_id))
for tag in ('tenant_nosuchco', 'nosuchco', 'tenant_trail; DROP TABLE x'):
    r = webhook(ev('bounced', dl.provider_message_id, tags={'tenant': tag}))
    check(r.status_code == 200 and r.get_json()['outcome'] == 'unknown_tenant'
          and len(get(EmailDeliveryEvent, provider_message_id=dl.provider_message_id)) == n,
          f'an event tagged for a company that is not there ({tag!r}) touches nothing')
r = webhook(ev('opened', dl.provider_message_id))
check(r.status_code == 200 and r.get_json()['outcome'] == 'ignored', 'event types we do not track are acknowledged and ignored')

print('\n5. Every email names the company it was sent from, so its outcome can find its way back')
captured = []


class _Resp:
    status_code = 200

    def json(self):
        return {'id': 're_real_1'}


real_post = notifications.http_requests.post
notifications.http_requests.post = lambda url, **k: (captured.append(k.get('json')) or _Resp())
os.environ['RESEND_API_KEY'] = 'test-key-not-real'
try:
    with app.test_request_context('/', base_url=HOST), tenancy.use_tenant(SLUG):
        REAL_SEND(to_email='x@example.com', to_name='X', subject='s', html='<p>h</p>')
        db.session.remove()
    with app.app_context(), tenancy.use_tenant(SLUG):        # a scheduled job: no request at all
        REAL_SEND(to_email='y@example.com', to_name='Y', subject='s', html='<p>h</p>')
        db.session.remove()
    with app.app_context():                                   # the platform's own mail
        REAL_SEND(to_email='z@example.com', to_name='Z', subject='s', html='<p>h</p>')
        db.session.remove()
finally:
    notifications.http_requests.post = real_post
    os.environ.pop('RESEND_API_KEY', None)
tags = [c_.get('tags') or [] for c_ in captured]
check(len(captured) == 3 and {'name': 'tenant', 'value': SCHEMA} in tags[0] and {'name': 'tenant', 'value': SCHEMA} in tags[1]
      and tags[2] == [],
      'in a request and in a job alike, the message carries its company; the platform\'s own does not '
      '(nothing left this machine: the HTTP call was intercepted)')

print('\n6. A quote accepted before agreements were recorded is amended once, not forked')
def legacy():
    q = CommercialQuote(company='Legacy Signed Co', contact_name='Lee', email='lee@legacy.example',
                        property_type='Office Building', frequency='weekly', contract_term='annual',
                        services='Office Cleaning', monthly_price=400, status='accepted', token='tok-legacy-signed')
    db.session.add(q)
    db.session.commit()
    return q.id
lid = in_tenant(legacy)
c.post(f'/quotes/{lid}/amend', base_url=HOST)
a1 = in_tenant(lambda: CommercialQuote.query.filter_by(amends_quote_id=lid).first())
check(a1 is not None and a1.amends_agreement_id is None and a1.status == 'draft',
      'it can be amended, though it has no agreement row')
c.post(f'/quotes/{a1.id}/send', base_url=HOST)
answer(app.test_client(), a1.token, HOST, 'accept', name='Lee')
r = c.post(f'/quotes/{lid}/amend', base_url=HOST, follow_redirects=True)
check(in_tenant(lambda: CommercialQuote.query.filter_by(amends_quote_id=lid).count()) == 1
      and 'already been replaced' in r.get_data(as_text=True),
      'once that amendment is accepted, amending the original again is refused')
review = c.get(f'/quotes/{lid}/review', base_url=HOST).get_data(as_text=True)
check(f'quote #{a1.id}' in review and 'Amend this agreement' not in review,
      'and its record says what replaced it')
err = sql("INSERT INTO commercial_quote (company, contact_name, email, token, status, amends_quote_id) "
          "VALUES ('Fork Co', 'F', 'f@fork.example', 'tok-fork', 'accepted', :l)", l=lid)
check(err is not None, 'the database itself allows one accepted amendment per quote')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ What was agreed, what replaced it, what arrived, and who did what -- all on record.')
