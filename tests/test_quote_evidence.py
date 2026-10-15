"""What was sent, to whom, and what the customer agreed to -- provable later.

From the quotation-to-contract integrity audit (2026-10-15), each of these
was true before:
  * the customer's link showed the quote row as it stood, not a frozen copy
    of what was sent -- nothing tied an acceptance to particular terms (F1, F6);
  * an acceptance kept a status and a time: not who, from where, or which
    terms (F6);
  * nothing recorded a send beyond a status -- not the recipient, the
    provider's id, or a failed attempt (F7);
  * an accepted quote joined whichever account had the same company name and
    email, so two customers sharing either were merged (F5);
  * a proposal with no price, scope, frequency or term could be sent and
    accepted (F8);
  * an offer stayed open for ever.

Against a disposable Postgres, like the rest of the multi-company suite: the
"evidence cannot be changed" checks are about the database itself.
"""
import hashlib
import json
import os
import pathlib
import sys
from datetime import datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import fresh_postgres  # a multi-company app needs PostgreSQL schemas
from quote_answer import answer, shown_hash
os.environ['DATABASE_URL'] = fresh_postgres.url('dsm_test_quote_evidence')
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['FLASK_ENV'] = 'development'

import notifications
SENT = []
notifications.send_email = lambda *a, **k: (SENT.append(k) or (True, 'Accepted by Resend from q@x.test (id re_msg_123).'))
notifications.send_sms = lambda *a, **k: (True, 'stub')

from sqlalchemy import text
from app import create_app
from extensions import db
from models import (CommercialAccount, CommercialQuote, Prospect, QuoteDelivery,
                    QuoteResponse, QuoteRevision)
import blueprints.quotes as Q
import provisioning
import quote_evidence
import tenancy

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


SLUG = 'qevid'
HOST = f'http://{SLUG}.akye.test'
with app.app_context():
    provisioning.provision(SLUG, 'Quote Evidence Cleaning', quiet=True)
    db.session.remove()
fresh_postgres.set_company_plan(SLUG, 'scale')
c = fresh_postgres.owner_client(app, SLUG, 'akye.test')
FORM = {'company': 'Frozen Co', 'contact_name': 'Pat Buyer', 'email': 'pat@frozen.example',
        'property_type': 'Office Building', 'property_address': '9 Main St',
        'frequency': 'weekly', 'contract_term': 'annual', 'services': ['Office Cleaning'],
        'price_per_visit': '120', 'monthly_price': '516', 'valid_days': '14'}


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


def row(qid):
    return in_tenant(lambda: db.session.get(CommercialQuote, qid).__dict__.copy())


def revisions(qid):
    return in_tenant(lambda: [(r.id, r.number, r.content_hash, r.terms, r.origin)
                              for r in QuoteRevision.query.filter_by(quote_id=qid).order_by(QuoteRevision.number)])


def deliveries(qid):
    return in_tenant(lambda: [(d.revision_id, d.recipient, d.status, d.provider_message_id)
                              for d in QuoteDelivery.query.filter_by(quote_id=qid).order_by(QuoteDelivery.id)])


def response(qid):
    return in_tenant(lambda: (lambda r: r and {k: getattr(r, k) for k in (
        'revision_id', 'content_hash', 'decision', 'signer_name', 'signer_title', 'signer_email',
        'ip_address', 'user_agent', 'account_id')})(QuoteResponse.query.filter_by(quote_id=qid).first()))


def sql_unguarded(statement, **params):
    """Raw SQL with the database's triggers off -- what SQLite, or a damaged
    restore, would allow. For proving the app checks for itself."""
    def go():
        db.session.execute(text('SET LOCAL session_replication_role = replica'))
        db.session.execute(text(statement), params)
        db.session.commit()
    return in_tenant(go)


def sql(statement, **params):
    """Run raw SQL in the company's schema; the error text, or None."""
    def go():
        try:
            db.session.execute(text(statement), params)
            db.session.commit()
            return None
        except Exception as e:
            db.session.rollback()
            return str(e)
    return in_tenant(go)


print('\n1. Sending freezes the terms, and the link is bound to them (F1, F6)')
qid, tok = new_quote()
SENT.clear()
before = datetime.utcnow()
r = c.post(f'/quotes/{qid}/send', base_url=HOST)
q = row(qid)
revs = revisions(qid)
check(q['status'] == 'sent' and len(revs) == 1 and q['issued_revision_id'] == revs[0][0],
      'one revision, and the quote\'s link is bound to it')
rid, _n, h, terms_text, origin = revs[0]
terms = json.loads(terms_text)
check(hashlib.sha256(terms_text.encode()).hexdigest() == h and origin == 'issued',
      'its hash is the SHA-256 of its stored terms')
check(terms['monthly_price'] == '516.00' and terms['services'] == ['Office Cleaning']
      and terms['contract_term'] == 'annual' and terms['email'] == 'pat@frozen.example',
      'the terms are the customer-facing ones, money as fixed decimals')
check(q['expires_at'] and timedelta(days=13, hours=23) < q['expires_at'] - before < timedelta(days=14, minutes=1)
      and terms['expires_at'] == q['expires_at'].isoformat(),
      'the offer closes 14 days out (as set on the form) and the date is one of its terms')
check(any('516.00' in k.get('html', '') and 'Offer open until' in k.get('html', '') for k in SENT),
      'the email carries the price and the closing date')
check(deliveries(qid) == [(rid, 'pat@frozen.example', 'accepted_by_provider', 're_msg_123')],
      'the send is recorded: revision, recipient, "taken by the provider", and its message id')

page = c.get(f'/quotes/view/{tok}', base_url=HOST).get_data(as_text=True)
check(f'value="{h}"' in page and f'Proposal reference {h[:12]}' in page and 'name="signer_name"' in page,
      'the customer\'s page carries the terms reference, and asks for a typed name to accept')

print('\n2. Changing the row behind a sent quote changes nothing the customer sees or signs')
# PR #90 stops the app editing a sent quote. This is what is left: a change
# made around the app -- a script, a console, a future bug.
sql('UPDATE commercial_quote SET monthly_price = 1, services = :s WHERE id = :i', s='Nothing', i=qid)
page = c.get(f'/quotes/view/{tok}', base_url=HOST).get_data(as_text=True)
check('516.00' in page and '$1.00' not in page and 'Office Cleaning' in page,
      'the link still shows the terms that were sent')
SENT.clear()
c.post(f'/quotes/{qid}/send', base_url=HOST)
check(any('516.00' in k.get('html', '') for k in SENT) and len(revisions(qid)) == 1
      and len(deliveries(qid)) == 2 and deliveries(qid)[1][0] == rid,
      'a resend sends the same revision again, and is recorded against it')
review = c.get(f'/quotes/{qid}/review', base_url=HOST).get_data(as_text=True)
check('id="quoteEvidence"' in review and h[:12] in review and '✅ unchanged' in review
      and 're_msg_123' in review and 'not proof it arrived' in review,
      'the owner\'s review shows the version, its fingerprint check, and each send')

print('\n3. Accepting records who, when, where, and exactly which terms')
anon = app.test_client()
r = answer(anon, tok, HOST, 'accept', name='', terms_hash=h)
check(r.status_code == 400 and row(qid)['status'] == 'sent' and response(qid) is None,
      'no typed name, no acceptance -- and nothing changes')
r = answer(anon, tok, HOST, 'accept', name='Pat Buyer', terms_hash='0' * 64)
check(r.status_code == 409 and row(qid)['status'] == 'sent' and 'changed since you opened it' in r.get_data(as_text=True),
      'terms other than the ones on the page are refused, and the customer is asked to read it again')
r = answer(anon, tok, HOST, 'accept', name='Pat Buyer', title='Facilities Manager',
           terms_hash=h, headers={'User-Agent': 'EvidenceBrowser/1.0'})
resp = response(qid)
q = row(qid)
check(r.status_code == 200 and q['status'] == 'accepted' and resp and resp['decision'] == 'accepted',
      'accepted')
check(resp and resp['revision_id'] == rid and resp['content_hash'] == h,
      'bound to the revision sent: delivered and accepted hashes match')
check(resp and resp['signer_name'] == 'Pat Buyer' and resp['signer_title'] == 'Facilities Manager'
      and resp['signer_email'] == 'pat@frozen.example' and resp['ip_address']
      and resp['user_agent'] == 'EvidenceBrowser/1.0',
      'with the typed name and title, the address it was sent to, the IP and the browser')
acc = in_tenant(lambda: CommercialAccount.query.get(q['account_id']))
check(acc is not None and resp['account_id'] == acc.id and acc.billing_amount == 516,
      'and the account it created, linked by id from both the quote and the record -- '
      'at the price sent, not the row\'s tampered one')

print('\n4. The record cannot be changed or removed')
err = sql('UPDATE commercial_quote_revision SET terms = :t WHERE id = :i', t='{}', i=rid)
check(err and 'never changed' in err, 'the database refuses to edit a revision')
err = sql('UPDATE commercial_quote_response SET signer_name = :n WHERE quote_id = :i', n='Someone Else', i=qid)
check(err and 'never changed' in err and response(qid)['signer_name'] == 'Pat Buyer',
      'or an answer')
err = sql('DELETE FROM commercial_quote WHERE id = :i', i=qid)
check(err is not None and row(qid)['status'] == 'accepted',
      'an answered quote cannot be deleted from under its record, even in SQL')
err = sql('DELETE FROM commercial_quote_revision WHERE id = :i', i=rid)
check(err is not None and len(revisions(qid)) == 1, 'nor can the revision it answered')


def orm_change():
    rev = db.session.get(QuoteRevision, rid)
    rev.terms = '{}'
    try:
        db.session.commit()
        return False
    except ValueError:
        db.session.rollback()
        return True


check(in_tenant(orm_change), 'and the app refuses to try')
c.post(f'/commercial/{acc.id}/delete', base_url=HOST)
check(in_tenant(lambda: db.session.get(CommercialAccount, acc.id)) is not None,
      'an account with a signed proposal is kept, not deleted out from under it')
check(quote_evidence.intact(in_tenant(lambda: db.session.get(QuoteRevision, rid))),
      'the revision still hashes to its fingerprint')

print('\n5. A failed send is recorded too, and offers nothing')
fid, ftok = new_quote(company='Mail Down Co')
real = Q.send_email
Q.send_email = lambda **k: (False, 'Resend error 500: down')
c.post(f'/quotes/{fid}/send', base_url=HOST)
Q.send_email = real
f = row(fid)
check(f['status'] == 'draft' and f['expires_at'] is None and f['issued_revision_id'] is None,
      'still a draft, with no closing date and no link bound')
check([d[2] for d in deliveries(fid)] == ['failed'], 'and the failed attempt is on record')
c.post(f'/quotes/{fid}/delete', base_url=HOST)
check(in_tenant(lambda: db.session.get(CommercialQuote, fid) is None),
      'a draft that never went out can still be deleted, attempts and all')

print('\n6. An offer closes on its date')
eid, etok = new_quote(company='Late Co')
c.post(f'/quotes/{eid}/send', base_url=HOST)
eh = shown_hash(app.test_client(), etok, HOST)
sql('UPDATE commercial_quote SET expires_at = :t WHERE id = :i', t=datetime.utcnow() - timedelta(minutes=1), i=eid)
page = c.get(f'/quotes/view/{etok}', base_url=HOST).get_data(as_text=True)
check('This proposal expired on' in page and 'name="signer_name"' not in page,
      'the link says it expired, with nothing to accept')
answer(app.test_client(), etok, HOST, 'accept', name='Late Buyer', terms_hash=eh)
check(row(eid)['status'] == 'sent' and response(eid) is None, 'and posting anyway accepts nothing')
check('>expired</span>' in c.get('/quotes/', base_url=HOST).get_data(as_text=True),
      'the owner\'s list says expired, not sent')
n = len(SENT)
c.post(f'/quotes/{eid}/send', base_url=HOST)
check(len(SENT) == n, 'it is not resent under a link that says it is closed -- a revision is a fresh offer')
import lifecycle
sql('UPDATE commercial_quote SET sent_at = :t WHERE id = :i', t=datetime.utcnow() - timedelta(days=3), i=eid)
in_tenant(lifecycle.run_lifecycle_emails)
check((row(eid)['drip_step'] or 0) == 0, 'and no "still interested?" email goes about it')

print('\n7. An offer must say what it costs, covers, how often and for how long (F8)')
for label, over in (('a price', {'company': 'No Price Co', 'price_per_visit': '', 'monthly_price': ''}),
                    ('what work is included', {'company': 'No Scope Co', 'services': []}),
                    ('how often', {'company': 'No Freq Co', 'frequency': ''}),
                    ('the contract term', {'company': 'No Term Co', 'contract_term': ''})):
    gid, _t = new_quote(**over)
    n = len(SENT)
    r = c.post(f'/quotes/{gid}/send', base_url=HOST, follow_redirects=True)
    check(row(gid)['status'] == 'draft' and len(SENT) == n and 'Not sent' in r.get_data(as_text=True),
          f'one without {label} is not sent')
with app.app_context(), tenancy.use_tenant(SLUG):
    db.session.add(CommercialQuote(company='Old Vague Co', contact_name='Vic', email='vic@vague.example',
                                   frequency='weekly', status='sent', token='tok-old-vague'))
    db.session.commit()
    db.session.remove()
page = app.test_client().get('/quotes/view/tok-old-vague', base_url=HOST).get_data(as_text=True)
check("can't be accepted online yet" in page and 'name="signer_name"' not in page,
      'one sent before this rule says it cannot be accepted online, and to call')
answer(app.test_client(), 'tok-old-vague', HOST, 'accept', name='Vic',
       terms_hash=in_tenant(lambda: quote_evidence.current_hash(CommercialQuote.query.filter_by(token='tok-old-vague').first())))
check(in_tenant(lambda: CommercialQuote.query.filter_by(token='tok-old-vague').first().status) == 'sent',
      'and posting anyway accepts nothing')

print('\n8. The account is found by key, never by name or email (F5)')
a1, t1 = new_quote(company='Same Name LLC', email='office@shared.example')
a2, t2 = new_quote(company='Same Name LLC', email='office@shared.example', property_address='77 Other Rd')
for qq, tt in ((a1, t1), (a2, t2)):
    c.post(f'/quotes/{qq}/send', base_url=HOST)
    answer(app.test_client(), tt, HOST, 'accept', name='Two Buyers')
acc1, acc2 = row(a1)['account_id'], row(a2)['account_id']
check(acc1 and acc2 and acc1 != acc2,
      'two customers who share a company name and an inbox get an account each, not one merged')

with app.app_context(), tenancy.use_tenant(SLUG):
    lead = Prospect(business_name='Lead Linked Inc', category='office', status='interested', stage='proposal')
    db.session.add(lead)
    db.session.commit()
    lead_id = lead.id
    db.session.add(CommercialAccount(business_name='Lead Linked (old name)', prospect_id=lead_id, status='active'))
    db.session.commit()
    lead_acc = CommercialAccount.query.filter_by(prospect_id=lead_id).first().id
    db.session.remove()
lid, ltok = new_quote(company='Lead Linked Inc', prospect_id=str(lead_id), contact_name='New Contact',
                      email='new.contact@leadlinked.example')
c.post(f'/quotes/{lid}/send', base_url=HOST)
answer(app.test_client(), ltok, HOST, 'accept', name='New Contact')
check(row(lid)['account_id'] == lead_acc,
      'a quote for a lead joins the account already made from that lead, though name and contact changed')
la = in_tenant(lambda: db.session.get(CommercialAccount, lead_acc))
check(la.billing_amount == 516 and la.billing_type == 'monthly' and la.frequency == 'weekly'
      and la.contact_name == 'New Contact' and la.email == 'new.contact@leadlinked.example',
      'and that account takes the accepted terms: price, schedule and contact')

c.post(f'/quotes/{a1}/duplicate', base_url=HOST)
dup = in_tenant(lambda: CommercialQuote.query.filter(CommercialQuote.company == 'Same Name LLC',
                                                     CommercialQuote.status == 'draft').first())
check(dup.account_id == acc1, 'a rebid duplicated from an accepted quote stays with that account')
c.post(f'/quotes/{dup.id}/send', base_url=HOST)
answer(app.test_client(), dup.token, HOST, 'accept', name='Two Buyers')
check(row(dup.id)['account_id'] == acc1
      and in_tenant(lambda: CommercialAccount.query.filter_by(business_name='Same Name LLC').count()) == 2,
      'and accepting it joins that account rather than making a third')

print('\n9. Quotes sent before revisions existed are frozen when answered')
with app.app_context(), tenancy.use_tenant(SLUG):
    db.session.add(CommercialQuote(company='Legacy Co', contact_name='Leo', email='leo@legacy.example',
                                   property_type='Office Building', frequency='weekly',
                                   contract_term='annual', services='Office Cleaning',
                                   monthly_price=400, status='sent', token='tok-legacy'))
    db.session.commit()
    leg = CommercialQuote.query.filter_by(token='tok-legacy').first().id
    db.session.remove()
lh = shown_hash(app.test_client(), 'tok-legacy', HOST)
answer(app.test_client(), 'tok-legacy', HOST, 'accept', name='Leo Legacy', terms_hash=lh)
lrev = revisions(leg)
check(row(leg)['status'] == 'accepted' and len(lrev) == 1 and lrev[0][4] == 'backfill'
      and lrev[0][2] == lh and response(leg)['content_hash'] == lh,
      'accepting freezes it as shown -- marked as a backfill -- and binds the answer to it')

print('\n10. Declining is recorded the same way, with no signature needed')
did, dtok = new_quote(company='Decline Co')
c.post(f'/quotes/{did}/send', base_url=HOST)
answer(app.test_client(), dtok, HOST, 'decline', name='')
dr = response(did)
check(row(did)['status'] == 'declined' and dr and dr['decision'] == 'declined'
      and dr['content_hash'] == revisions(did)[0][2] and dr['account_id'] is None,
      'declined, bound to the revision, no account')

print('\n11. The frozen terms decide, not the row: closing date and seller')
def frozen_late():
    q = CommercialQuote(company='Frozen Late Co', contact_name='Fay', email='fay@late.example',
                        property_type='Office Building', frequency='weekly', contract_term='annual',
                        services='Office Cleaning', monthly_price=300, status='draft',
                        token='tok-frozen-late', expires_at=datetime.utcnow() - timedelta(minutes=5))
    db.session.add(q)
    db.session.flush()
    rev = quote_evidence.freeze(q)
    q.issued_revision_id, q.status = rev.id, 'sent'
    q.expires_at = datetime.utcnow() + timedelta(days=365)    # the row, moved on a year
    db.session.commit()
    return q.id
fl = in_tenant(frozen_late)
page = app.test_client().get('/quotes/view/tok-frozen-late', base_url=HOST).get_data(as_text=True)
check('This proposal expired on' in page and 'name="signer_name"' not in page,
      'the closing date it was sent with closes it, though the row now says next year')
answer(app.test_client(), 'tok-frozen-late', HOST, 'accept', name='Fay',
       terms_hash=revisions(fl)[0][2])
check(row(fl)['status'] == 'sent' and response(fl) is None, 'and it accepts nothing')

sel_id, sel_tok = new_quote(company='Seller Co')
c.post(f'/quotes/{sel_id}/send', base_url=HOST)
seller = json.loads(revisions(sel_id)[0][3])['seller']
from models import BusinessSetting
def rename(name):
    BusinessSetting.set('business_name', name)
    db.session.commit()
in_tenant(lambda: rename('Renamed Later Cleaning'))
page = app.test_client().get(f'/quotes/view/{sel_tok}', base_url=HOST).get_data(as_text=True)
doc = page.split('class="qdoc-header"', 1)[-1][:400]
check(seller and seller in doc and 'Renamed Later Cleaning' not in doc,
      f'the proposal names the business it was sent from ({seller!r}), not a later rename')
in_tenant(lambda: rename(seller))

print('\n12. A quote is only ever bound to a revision of its own')
own_id, own_tok = new_quote(company='Owner Co')
c.post(f'/quotes/{own_id}/send', base_url=HOST)
other_rev = revisions(sel_id)[0][0]
err = sql('UPDATE commercial_quote SET issued_revision_id = :r WHERE id = :i', r=other_rev, i=own_id)
check(err and 'not one of its own' in err and row(own_id)['issued_revision_id'] == revisions(own_id)[0][0],
      'the database refuses to point a quote at another quote\'s revision')
err = sql('UPDATE commercial_quote SET issued_revision_id = 999999 WHERE id = :i', i=own_id)
check(err and 'not one of its own' in err, 'or at one that does not exist')

sql_unguarded('UPDATE commercial_quote SET issued_revision_id = :r WHERE id = :i', r=other_rev, i=own_id)
r = app.test_client().get(f'/quotes/view/{own_tok}', base_url=HOST)
body = r.get_data(as_text=True)
check(r.status_code == 409 and "can't be shown" in body and 'Seller Co' not in body,
      'where the database could not stop it, the link shows nothing -- not the other customer\'s proposal')
answer(app.test_client(), own_tok, HOST, 'accept', name='Owner', terms_hash=revisions(sel_id)[0][2])
check(row(own_id)['status'] == 'sent' and response(own_id) is None, 'and accepts nothing')

tam_id, tam_tok = new_quote(company='Tamper Co')
c.post(f'/quotes/{tam_id}/send', base_url=HOST)
tam_rev, _n, tam_hash, tam_terms, _o = revisions(tam_id)[0]
sql_unguarded('UPDATE commercial_quote_revision SET terms = :t WHERE id = :i',
              t=tam_terms.replace('"516.00"', '"1.00"'), i=tam_rev)
r = app.test_client().get(f'/quotes/view/{tam_tok}', base_url=HOST)
check(r.status_code == 409 and '1.00' not in r.get_data(as_text=True),
      'a revision whose terms no longer match their fingerprint is not shown')
answer(app.test_client(), tam_tok, HOST, 'accept', name='Tam', terms_hash=tam_hash)
check(row(tam_id)['status'] == 'sent' and response(tam_id) is None,
      'nor accepted under the fingerprint it no longer matches')
n = len(SENT)
r = c.post(f'/quotes/{tam_id}/send', base_url=HOST, follow_redirects=True)
check(len(SENT) == n and 'no longer matches its' in r.get_data(as_text=True),
      'nor resent; the owner is told why')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ What was sent, to whom, and what was agreed can be shown -- and cannot be rewritten.')
