"""G2: one proposal taken the whole way -- issued, accepted, amended -- through
the app's own routes, on a demo company, with every record it leaves checked.

Run by `certify.py journey --company <slug>`. What it does, in order:

  1. refuses unless the company is marked is_demo and the database is on this
     code's migration head (so it cannot migrate anything);
  2. as the company's owner: creates a certification proposal and sends it.
     A demo company never sends (demo_guard), so the send goes to a stub that
     records the message and answers with a "cert-..." id; the evidence says so;
  3. as the customer, on the issued link: checks the page shows exactly the
     issued revision's hash, and accepts with a typed name;
  4. checks one answer, one agreement, the account link, and the trail;
  5. tries what must not work: a second acceptance, editing and deleting the
     accepted quote, and -- in transactions that are always rolled back --
     UPDATE and DELETE straight at the evidence tables;
  6. amends it, sends and accepts the amendment, and checks the original
     agreement is exactly as it was, the new one names it, and the old link
     says it was replaced;
  7. runs evidence_check over the records it made.

What it leaves behind is an ordinary certification proposal on the demo
company (which the demo's rebuild clears). The returned dict is the evidence
pack: ids, hashes, request ids, timings -- and the certification names it typed,
which are made up.
"""
import os
import re
import secrets
from datetime import datetime
from urllib.parse import urlsplit

CERT_NAME = 'Certification Signer'
CERT_EMAIL = 'certification@example.com'


class Refused(Exception):
    pass


def _preflight(slug):
    import backup
    import control_plane
    import evidence_check
    from sqlalchemy import text
    engine = backup._read_engine()
    org = control_plane.find(engine, slug)
    if not org:
        raise Refused(f'no company {slug}')
    if not org.get('is_demo'):
        raise Refused(f'{slug} is not a demo company; the journey writes records and runs only on one')
    if not (os.environ.get('BASE_DOMAIN') or '').strip():
        raise Refused('BASE_DOMAIN is not set; the journey reaches the company at its own address')
    # Booting the app migrates every schema that is behind -- public and every
    # company, not only this one. So all of them must already be on this
    # code's head, or the journey would be what migrated production.
    head = evidence_check.head_revision()
    with engine.connect() as conn:
        behind = []
        for schema in ['public'] + evidence_check.inventory(conn)['schemas']:
            found = conn.execute(text('SELECT to_regclass(:t)'),
                                 {'t': f'"{schema}".alembic_version'}).scalar()
            version = conn.execute(text(
                f'SELECT version_num FROM "{schema}".alembic_version')).scalar() if found else None
            if version != head:
                behind.append(f'{schema} ({version})')
    engine.dispose()
    if behind:
        raise Refused(f'not every schema is on {head}: {", ".join(behind[:5])}'
                      f'{" …" if len(behind) > 5 else ""}. Deploy first, so that this is not what migrates them')
    return org


def run(slug):
    """The evidence pack. Problems are listed in it, never raised -- except a
    refusal to start, which is returned as the only problem."""
    try:
        org = _preflight(slug)
    except Refused as e:
        return {'command': 'journey', 'company': slug, 'problems': [str(e)]}
    return Journey(org).go()


class Journey:
    def __init__(self, org):
        self.org = org
        self.slug = org['slug']
        self.schema = org['schema_name']
        self.host = f'https://{self.slug}.{os.environ["BASE_DOMAIN"].strip()}'
        self.problems = []
        self.steps = []
        self.ids = {}
        self.outbox = []

    # -- plumbing -----------------------------------------------------------

    def check(self, ok, what, **facts):
        self.steps.append({'check': what, 'ok': bool(ok), 'at': datetime.utcnow().isoformat() + 'Z',
                           **{k: v for k, v in facts.items() if v is not None}})
        print(f'  {"✅" if ok else "❌"} {what}')
        if not ok:
            self.problems.append(what)
            if facts.get('response'):
                print(f'      answered {facts["response"]}')
        return ok

    @staticmethod
    def _answer(r):
        """What a request was answered with, for a failed step: the status and
        where it was sent. A redirect to the login or another page is the
        usual reason, and says which check refused it."""
        location = urlsplit(r.headers.get('Location') or '')
        return {'status': r.status_code, 'location': location.path or None}

    def tenant(self, fn):
        import tenancy
        from extensions import db
        with self.app.app_context(), tenancy.use_tenant(self.slug):
            try:
                return fn()
            finally:
                db.session.remove()

    def _stub_send(self, *args, **kw):
        """Stands in for the mail provider: records, answers like Resend."""
        message_id = 'cert-' + secrets.token_hex(8)
        self.outbox.append({'to': kw.get('to_email'), 'subject': kw.get('subject'),
                            'message_id': message_id})
        return True, f'certification stub — not sent (id {message_id})'

    def owner_client(self):
        import demo_company
        from auth import _auth_fingerprint
        from models import User

        def find():
            u = (User.query.filter_by(username=demo_company.OWNER[1], active=True).first()
                 or User.query.filter_by(role='owner', active=True).order_by(User.id).first())
            return (u.id, u.name, _auth_fingerprint(u.password_hash)) if u else None
        found = self.tenant(find)
        if not found:
            raise Refused(f'{self.slug} has no active owner')
        uid, name, fp = found
        self.owner_name = name
        c = self.app.test_client()
        with c.session_transaction(base_url=self.host) as s:
            s.update(logged_in=True, role='owner', user_id=uid, user_name=name,
                     auth_fingerprint=fp, tenant_slug=self.slug)
        return c

    def quote(self, qid):
        from models import CommercialQuote
        return self.tenant(lambda: _plain(CommercialQuote.query.get(qid)))

    def one(self, model, **by):
        return self.tenant(lambda: _plain(model.query.filter_by(**by).first()))

    def all(self, model, **by):
        return self.tenant(lambda: [_plain(r) for r in model.query.filter_by(**by).order_by(model.id).all()])

    # -- the journey --------------------------------------------------------

    def go(self):
        import blueprints.quotes as Q
        from app import create_app
        self.app = create_app()
        real_send = Q.send_email
        Q.send_email = self._stub_send
        started = datetime.utcnow()
        try:
            self.owner = self.owner_client()
            self.customer = self.app.test_client()
            first = self.issue_and_accept('Certification Original', price='500')
            if first:
                self.must_not(first)
                self.amend(first)
            self.reconcile()
        except Refused as e:
            self.problems.append(str(e))
        except Exception as e:  # a crash is a failed gate, with what it was
            self.problems.append(f'journey stopped: {type(e).__name__}: {e}')
        finally:
            Q.send_email = real_send
        return {'command': 'journey', 'company': self.slug, 'schema': self.schema,
                'started_at': started.isoformat() + 'Z', 'transport': 'certification stub (demo company)',
                'ids': self.ids, 'outbox': self.outbox, 'steps': self.steps, 'problems': self.problems}

    def issue_and_accept(self, company, price, amend_of=None):
        from models import (CommercialAgreement, CommercialQuote, ContractAuditEvent,
                            QuoteDelivery, QuoteResponse, QuoteRevision)
        tag = company.split()[-1].lower()
        if amend_of is None:
            self.form = {
                'company': f'{company} {secrets.token_hex(3)}', 'contact_name': CERT_NAME,
                'email': CERT_EMAIL, 'property_type': 'Office Building',
                'property_address': '1 Certification Way', 'frequency': 'weekly',
                'contract_term': 'annual', 'services': ['Office Cleaning'],
                'price_per_visit': '120', 'monthly_price': price}
            r = self.owner.post('/quotes/new', base_url=self.host, data=self.form)
            m = re.search(r'/quotes/(\d+)', r.headers.get('Location', ''))
            if not self.check(r.status_code == 302 and m, f'{tag}: the owner creates a draft',
                              response=self._answer(r)):
                return None
            qid = int(m.group(1))
        else:
            qid = amend_of
        q = self.quote(qid)
        self.check(q and q['status'] == 'draft', f'{tag}: it is a draft, with no revision yet',
                   quote_id=qid)
        r = self.owner.post(f'/quotes/{qid}/send', base_url=self.host)
        q = self.quote(qid)
        rev = self.one(QuoteRevision, id=q['issued_revision_id']) if q['issued_revision_id'] else None
        delivery = (self.all(QuoteDelivery, quote_id=qid) or [None])[-1]
        self.check(q['status'] == 'sent' and rev and rev['quote_id'] == qid,
                   f'{tag}: sending freezes revision {rev and rev["id"]} and binds the link to it',
                   revision_id=rev and rev['id'], content_hash=rev and rev['content_hash'],
                   approved_by=rev and rev.get('created_by'), issued_at=rev and str(rev['created_at']),
                   response=self._answer(r))
        self.check(delivery and delivery['revision_id'] == (rev and rev['id'])
                   and (delivery.get('provider_message_id') or '').startswith('cert-'),
                   f'{tag}: the delivery names that revision and the message id',
                   delivery_id=delivery and delivery['id'],
                   message_id=delivery and delivery.get('provider_message_id'))
        if not rev:
            return None
        page = self.customer.get(f'/quotes/view/{q["token"]}', base_url=self.host)
        shown = re.search(r'name="terms_hash" value="([0-9a-f]{64})"', page.get_data(as_text=True))
        self.check(page.status_code == 200 and shown and shown.group(1) == rev['content_hash'],
                   f'{tag}: the customer\'s link shows exactly the issued terms')
        r = self.customer.post(f'/quotes/view/{q["token"]}/accept', base_url=self.host,
                               data={'terms_hash': rev['content_hash'], 'signer_name': CERT_NAME,
                                     'signer_title': 'Certification'})
        q = self.quote(qid)
        responses = self.all(QuoteResponse, quote_id=qid)
        agreements = self.all(CommercialAgreement, quote_id=qid)
        resp, ag = (responses or [None])[0], (agreements or [None])[0]
        self.check(r.status_code == 200 and q['status'] == 'accepted', f'{tag}: the customer accepts it')
        self.check(len(responses) == 1 and resp['decision'] == 'accepted'
                   and resp['content_hash'] == rev['content_hash'] and resp['signer_name'] == CERT_NAME,
                   f'{tag}: one answer, naming the issued hash and the typed name',
                   response_id=resp and resp['id'])
        self.check(len(agreements) == 1 and ag['response_id'] == resp['id']
                   and ag['content_hash'] == rev['content_hash'] and ag['account_id'] == q['account_id']
                   and q['account_id'], f'{tag}: one agreement, tied to that answer and the account',
                   agreement_id=ag and ag['id'], account_id=q['account_id'])
        events = self.all(ContractAuditEvent, quote_id=qid)
        names = [e['event'] for e in events]
        want = ['created', 'sent', 'viewed', 'accepted', 'agreement_executed']
        self.check(all(w in names for w in want) and all(e['row_hash'] for e in events),
                   f'{tag}: the trail has {", ".join(want)}, each in the hash chain',
                   events=[{'event': e['event'], 'seq': e['chain_seq'], 'request_id': e['request_id'],
                            'actor_kind': e['actor_kind']} for e in events])
        self.ids[tag] = {'quote_id': qid, 'revision_id': rev['id'], 'content_hash': rev['content_hash'],
                         'delivery_id': delivery and delivery['id'], 'response_id': resp and resp['id'],
                         'agreement_id': ag and ag['id'], 'account_id': q['account_id'], 'token_bound': True}
        return qid

    def must_not(self, qid):
        from models import CommercialAgreement, CommercialQuote, QuoteResponse
        q = self.quote(qid)
        before = (q['monthly_price'], q['status'], self.ids['original']['content_hash'])
        r = self.customer.post(f'/quotes/view/{q["token"]}/accept', base_url=self.host,
                               data={'terms_hash': before[2], 'signer_name': 'Someone Else'})
        self.check(len(self.all(QuoteResponse, quote_id=qid)) == 1
                   and len(self.all(CommercialAgreement, quote_id=qid)) == 1,
                   'a second acceptance of the same link records nothing')
        edit = self.owner.post(f'/quotes/{qid}', base_url=self.host, data=dict(self.form, monthly_price='1'))
        gone = self.owner.post(f'/quotes/{qid}/delete', base_url=self.host)
        q = self.quote(qid)
        self.check(q and (q['monthly_price'], q['status']) == before[:2],
                   'the accepted quote can be neither edited nor deleted')
        for what, r in (('edit', edit), ('delete', gone)):
            # Refused by the rule, not by a crash or a lost session: the
            # owner is sent back to the quote, still signed in.
            where = r.headers.get('Location', '')
            self.check(r.status_code in (302, 303) and f'/quotes/{qid}' in where and 'login' not in where,
                       f'the {what} was answered with a refusal, not an error',
                       status=r.status_code, location=where)
        for what, sql in (
                ('UPDATE a revision', 'UPDATE {s}commercial_quote_revision SET terms = terms WHERE quote_id = :q'),
                ('DELETE an answer', 'DELETE FROM {s}commercial_quote_response WHERE quote_id = :q'),
                ('UPDATE an agreement', 'UPDATE {s}commercial_agreement SET account_id = account_id WHERE quote_id = :q'),
                ('DELETE an agreement', 'DELETE FROM {s}commercial_agreement WHERE quote_id = :q'),
                ('UPDATE the trail', 'UPDATE {s}contract_audit_event SET actor = actor WHERE quote_id = :q'),
                ('DELETE the trail', 'DELETE FROM {s}contract_audit_event WHERE quote_id = :q')):
            self.check(self._refused(sql, qid), f'the database refuses to {what}')

    def _refused(self, sql, qid):
        """Run one forbidden statement in a transaction that is rolled back
        whatever happens. True if the database refused it."""
        import backup
        from sqlalchemy import text
        engine = backup._read_engine()
        try:
            with engine.connect() as conn:
                tx = conn.begin()
                try:
                    conn.execute(text(sql.format(s=f'"{self.schema}".')), {'q': qid})
                    return False
                except Exception:
                    return True
                finally:
                    tx.rollback()
        finally:
            engine.dispose()

    def amend(self, qid):
        from models import CommercialAgreement, CommercialQuote
        original = self.ids['original']
        r = self.owner.post(f'/quotes/{qid}/amend', base_url=self.host)
        new = self.tenant(lambda: [x.id for x in CommercialQuote.query.filter_by(amends_quote_id=qid).all()])
        if not self.check(r.status_code == 302 and len(new) == 1,
                          'amending opens one draft for the same account', response=self._answer(r)):
            return
        nid = new[0]
        self.owner.post(f'/quotes/{nid}', base_url=self.host,
                        data=dict(self.form, monthly_price='650', price_per_visit='150'))
        if not self.issue_and_accept('Certification Amendment', price='650', amend_of=nid):
            return
        amended = self.ids['amendment']
        old = self.one(CommercialAgreement, id=original['agreement_id'])
        new_ag = self.one(CommercialAgreement, id=amended['agreement_id'])
        self.check(old and old['content_hash'] == original['content_hash'] and old['quote_id'] == qid,
                   'the original agreement is exactly as it was')
        self.check(new_ag and new_ag['amends_agreement_id'] == original['agreement_id'],
                   'the new agreement names the one it replaces')
        self.check(len(self.tenant(lambda: CommercialQuote.query.filter_by(
            amends_quote_id=qid, status='accepted').all())) == 1,
            'the original has exactly one accepted amendment')
        q = self.quote(qid)
        page = self.customer.get(f'/quotes/view/{q["token"]}', base_url=self.host).get_data(as_text=True)
        self.check('replaced' in page.lower(), 'the original link says it was replaced')

    def reconcile(self):
        import backup
        import evidence_check
        engine = backup._read_engine()
        try:
            with engine.connect() as conn, conn.begin():
                evidence_check.read_only(conn)
                rec = evidence_check.reconcile(conn, self.schema)
                chain = evidence_check.audit_chain(conn, self.schema)
        finally:
            engine.dispose()
        mine = {str(v['quote_id']) for v in self.ids.values()} | {
            str(v.get(k)) for v in self.ids.values() for k in ('agreement_id', 'response_id', 'revision_id')}
        ours = [p for p in rec['problems'] if set(re.findall(r'\d+', p)) & mine]
        self.check(not ours, 'the records made reconcile: hashes, answers, agreements, accounts',
                   problems=ours or None)
        self.check(not chain['problems'], f'the company\'s audit chain is whole ({chain["length"]} entries)',
                   problems=chain['problems'] or None)
        others = [p for p in rec['problems'] if p not in ours]
        if others:
            self.steps.append({'note': 'problems elsewhere in this company (not this run)', 'problems': others})


def _plain(row):
    if row is None:
        return None
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}
