"""A sent quote's terms, frozen; and the record of sending and answering it.

The quote row is the working copy. When it is sent, its customer-facing terms
are written out as canonical JSON -- sorted keys, fixed separators, money as
two-decimal strings -- and hashed (SHA-256) into a QuoteRevision that is never
changed. The customer's link shows that revision, the email is built from it,
and an acceptance names its hash: so "what was sent" and "what was accepted"
are the same bytes, provably, whatever happens to the row afterwards.

The hash shows the terms are unchanged. It is not a signature and says nothing
about who accepted -- that is the response's job (typed name, time, IP).
"""
import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

TERMS_VERSION = 1
# Tables whose rows are never updated, and the migration that froze them.
# A restored backup re-freezes all of them (install_guards); each migration
# freezes only its own, since a later table does not exist yet when an
# earlier migration runs.
FROZEN_0029 = ('commercial_quote_revision', 'commercial_quote_response')
FROZEN_0030 = ('commercial_agreement', 'email_delivery_event', 'contract_audit_event')
FROZEN_TABLES = FROZEN_0029 + FROZEN_0030
# Tables whose rows are never deleted either: nothing else points at an
# agreement, a delivery outcome or an audit entry, so a foreign key cannot
# keep them. (Revisions
# and deliveries are not here: a draft's unsent attempts go with the draft.)
# A backup restore empties every table before refilling it, and says so with
# SET LOCAL akye.restoring = 'on' (backup.restore) -- the only way past.
KEPT_TABLES = ('commercial_quote_response', 'commercial_agreement', 'email_delivery_event',
               'contract_audit_event')


def _money(v):
    if v in (None, ''):
        return None
    try:
        return format(Decimal(str(v)).quantize(Decimal('0.01')), 'f')
    except (InvalidOperation, ValueError):
        return None


def _text(v):
    return (v or '').strip() if isinstance(v, str) else (v if v is not None else '')


def terms(q):
    """Everything the customer is offered, and nothing about the offer's
    bookkeeping (status, drip step, view times)."""
    import brands
    import branding
    try:
        lines = json.loads(q.line_items) if q.line_items else None
    except ValueError:
        lines = None
    return {
        'v': TERMS_VERSION,
        'quote_id': q.id,
        'seller': branding.biz_name(),
        'brand': q.brand or brands.brand_for_property(q.property_type),
        'company': _text(q.company),
        'contact_name': _text(q.contact_name),
        'email': _text(q.email),
        'phone': _text(q.phone),
        'property_type': _text(q.property_type),
        'property_address': _text(q.property_address),
        'units': _text(q.units),
        'sqft': _text(q.sqft),
        'services': [s.strip() for s in (q.services or '').split(',') if s.strip()],
        'frequency': _text(q.frequency),
        'contract_term': _text(q.contract_term),
        'price_per_visit': _money(q.price_per_visit),
        'monthly_price': _money(q.monthly_price),
        'scope_notes': _text(q.scope_notes),
        'line_items': lines if isinstance(lines, dict) else None,
        'show_line_prices': q.show_line_prices is not False,
        'first_visit_premium': bool(q.first_visit_premium),
        'expires_at': q.expires_at.replace(microsecond=0).isoformat() if q.expires_at else None,
    }


def canonical(t):
    return json.dumps(t, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def current_hash(q):
    """The hash the quote row's terms would freeze to now."""
    return digest(canonical(terms(q)))


def freeze(q, by=None, origin='issued'):
    """The revision holding q's terms as they are now: the existing one if
    these exact terms were frozen before (a retried send), else a new one.
    Flushed, not committed -- it belongs to the caller's transaction."""
    from extensions import db
    from models import QuoteRevision
    text = canonical(terms(q))
    h = digest(text)
    rev = QuoteRevision.query.filter_by(quote_id=q.id, content_hash=h).first()
    if rev:
        return rev
    n = db.session.query(db.func.max(QuoteRevision.number)).filter_by(quote_id=q.id).scalar() or 0
    rev = QuoteRevision(quote_id=q.id, number=n + 1, terms=text, content_hash=h,
                        origin=origin, created_by=(by or None))
    db.session.add(rev)
    db.session.flush()
    return rev


def issued(q):
    """The revision the customer's link is bound to, or None (a draft, or a
    quote sent before revisions existed). Only one of q's own: a pointer to
    another quote's revision is no revision at all (see broken())."""
    from models import QuoteRevision
    if not q.issued_revision_id:
        return None
    rev = QuoteRevision.query.get(q.issued_revision_id)
    return rev if rev is not None and rev.quote_id == q.id else None


def intact(rev):
    """Its stored terms still hash to its stored hash."""
    return bool(rev) and digest(rev.terms) == rev.content_hash


def broken(q):
    """Sent, but its link's revision is missing, someone else's, or no longer
    matches its fingerprint. The database stops each of these (migration
    0029); this is for when it could not -- SQLite, a damaged restore. Such a
    quote is neither shown nor answered: falling back to the working row
    would offer terms nobody froze."""
    if q.status == 'draft' or not q.issued_revision_id:
        return False
    rev = issued(q)
    return rev is None or not intact(rev)


class Frozen:
    """A quote as a revision froze it: the revision's terms, with the live
    row's status, token and dates. Anything that renders a quote -- the
    customer's page, the email, the printable copy -- can take one in place
    of the row, so a sent quote is always shown as it was sent."""

    def __init__(self, q, rev):
        self._q, self.revision = q, rev
        t = json.loads(rev.terms)
        self._t = t
        self.company = t['company']
        self.contact_name = t['contact_name']
        self.email = t['email']
        self.phone = t['phone']
        self.property_type = t['property_type']
        self.property_address = t['property_address']
        self.units = t['units']
        self.sqft = t['sqft']
        self.services = ', '.join(t['services'])
        self.frequency = t['frequency']
        self.contract_term = t['contract_term']
        self.price_per_visit = Decimal(t['price_per_visit']) if t['price_per_visit'] else None
        self.monthly_price = Decimal(t['monthly_price']) if t['monthly_price'] else None
        self.scope_notes = t['scope_notes']
        self.line_items = json.dumps(t['line_items']) if t['line_items'] else None
        self.show_line_prices = t['show_line_prices']
        self.first_visit_premium = t['first_visit_premium']
        self.brand = t['brand']
        self.seller = t['seller']
        self.expires_at = datetime.fromisoformat(t['expires_at']) if t['expires_at'] else None
        self.content_hash = rev.content_hash

    @property
    def expired(self):
        """Past the closing date it was sent with. A row moved later does not
        reopen it; one moved earlier (never by the app) still closes it, so
        the page and the accept route always agree."""
        return bool(self._q.status == 'sent' and (
            self._q.expired or (self.expires_at and self.expires_at <= datetime.utcnow())))

    def __getattr__(self, name):
        return getattr(self._q, name)


def as_issued(q):
    """What the customer is shown for q: its frozen revision once sent, the
    row itself for a draft or a quote sent before revisions existed."""
    rev = issued(q) if q.status != 'draft' else None
    return Frozen(q, rev) if rev else q


def shown_hash(q):
    """The hash of the terms q's link shows right now -- the revision's, or
    for a quote sent before revisions, the row's -- posted back on accept."""
    rev = issued(q) if q.status != 'draft' else None
    return rev.content_hash if rev else current_hash(q)


def expiry_for(q, now=None):
    """When an offer sent now closes."""
    days = q.valid_days if q.valid_days and q.valid_days > 0 else 30
    return (now or datetime.utcnow()).replace(microsecond=0) + timedelta(days=min(days, 365))


def provider_message_id(detail):
    """The provider's id out of send_email's detail ('... (id abc123).')."""
    import re
    m = re.search(r'\(id ([^)\s]+)\)', detail or '')
    return m.group(1)[:100] if m else None


def frozen_sql(prefix, tables):
    """Statements making each table refuse UPDATE."""
    out = [f"""
        CREATE OR REPLACE FUNCTION {prefix}quote_evidence_frozen() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% rows are evidence and are never changed', TG_TABLE_NAME;
        END $$"""]
    for table in tables:
        out += [f'DROP TRIGGER IF EXISTS {table}_frozen ON {prefix}{table}',
                f'CREATE TRIGGER {table}_frozen BEFORE UPDATE ON {prefix}{table} '
                f'FOR EACH ROW EXECUTE PROCEDURE {prefix}quote_evidence_frozen()']
    return out


def kept_sql(prefix, tables):
    """Statements making each table refuse DELETE, except during a restore."""
    out = [f"""
        CREATE OR REPLACE FUNCTION {prefix}quote_evidence_kept() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF current_setting('akye.restoring', true) = 'on' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION '% rows are evidence and are never deleted', TG_TABLE_NAME;
        END $$"""]
    for table in tables:
        out += [f'DROP TRIGGER IF EXISTS {table}_kept ON {prefix}{table}',
                f'CREATE TRIGGER {table}_kept BEFORE DELETE ON {prefix}{table} '
                f'FOR EACH ROW EXECUTE PROCEDURE {prefix}quote_evidence_kept()']
    return out


def ownership_sql(prefix):
    """A quote's issued_revision_id must name a revision of that same quote.

    A constraint trigger checked at commit, not a foreign key: a backup
    restore inserts quotes before their revisions, in one transaction, and a
    key would refuse the first quote. Deferred, the check runs once both are
    in.

    The body finds the revisions next to the quote it was fired for
    (TG_TABLE_SCHEMA) rather than naming a schema: a company built under one
    schema name and renamed (the demo, demo_company.py) keeps its functions,
    and a name written into them would point at a schema that is gone."""
    return [f"""
        CREATE OR REPLACE FUNCTION {prefix}quote_issued_revision_owned() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            owned boolean;
        BEGIN
            IF NEW.issued_revision_id IS NOT NULL THEN
                EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I.commercial_quote_revision r '
                               'WHERE r.id = $1 AND r.quote_id = $2)', TG_TABLE_SCHEMA)
                    INTO owned USING NEW.issued_revision_id, NEW.id;
                IF NOT owned THEN
                    RAISE EXCEPTION 'quote % is bound to revision %, which is not one of its own',
                        NEW.id, NEW.issued_revision_id;
                END IF;
            END IF;
            RETURN NULL;
        END $$""",
            f'DROP TRIGGER IF EXISTS commercial_quote_issued_owned ON {prefix}commercial_quote',
            f'CREATE CONSTRAINT TRIGGER commercial_quote_issued_owned '
            f'AFTER INSERT OR UPDATE OF issued_revision_id ON {prefix}commercial_quote '
            f'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW '
            f'EXECUTE PROCEDURE {prefix}quote_issued_revision_owned()']


# The audit trail as a hash chain. Every contract_audit_event row carries its
# place in the chain (chain_seq), the hash of the row before it (prev_hash) and
# its own (row_hash), computed by the database on insert -- under a lock, so
# two requests cannot both claim the same place. A row changed afterwards no
# longer hashes to its row_hash, and every row after it names the wrong
# predecessor. The triggers above already refuse edits; the chain is what still
# shows an edit made by somebody able to switch those triggers off (the
# database's owner can), once the chain's head has been written down somewhere
# that person cannot reach -- the nightly backup's manifest (backup.py).
AUDIT_GENESIS = '0' * 64
AUDIT_FIELDS = ('event', 'quote_id', 'revision_id', 'agreement_id', 'actor_kind', 'actor',
                'ip_address', 'request_id', 'detail')


def _field(value):
    return '-' if value is None else f'{len(str(value))}:{value}'


def audit_row_hash(row, seq, prev):
    """What the database computes for one audit row (audit_chain_sql), here
    so a checker can recompute the chain without trusting the stored hashes.
    `row` is a mapping or an object with the audit columns."""
    get = (lambda k: row[k]) if hasattr(row, 'keys') else (lambda k: getattr(row, k))
    created = get('created_at')
    stamp = created.strftime('%Y-%m-%dT%H:%M:%S.%f') if created is not None else None
    parts = [str(get('id')), str(seq), prev, _field(stamp)] + [
        _field(None if get(k) is None else str(get(k))) for k in AUDIT_FIELDS]
    return digest('|'.join(parts))


def _field_sql(expr):
    """audit_field, written out: the chain trigger names no function or table
    by its schema (see ownership_sql for why)."""
    return f"CASE WHEN ({expr}) IS NULL THEN '-' ELSE length({expr})::text || ':' || ({expr}) END"


def audit_chain_sql(prefix):
    """The function that hashes one row, the trigger that chains each insert,
    and the unique index that keeps the chain a single line."""
    fields = ', '.join(_field_sql(f'NEW.{k}::text') for k in AUDIT_FIELDS)
    stamp = _field_sql("to_char(NEW.created_at, 'YYYY-MM-DD\"T\"HH24:MI:SS.US')")
    return [f"""
        CREATE OR REPLACE FUNCTION {prefix}audit_field(v text) RETURNS text
        LANGUAGE sql IMMUTABLE AS $$
            SELECT CASE WHEN v IS NULL THEN '-' ELSE length(v)::text || ':' || v END
        $$""", f"""
        CREATE OR REPLACE FUNCTION {prefix}contract_audit_chain() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            last_seq bigint;
            last_hash text;
        BEGIN
            -- A restore puts the chain back exactly as it was taken, so it
            -- can be checked against the copy written down outside.
            IF current_setting('akye.restoring', true) = 'on' AND NEW.row_hash IS NOT NULL THEN
                RETURN NEW;
            END IF;
            PERFORM pg_advisory_xact_lock(hashtext(TG_TABLE_SCHEMA || '.contract_audit_chain'));
            EXECUTE format('SELECT chain_seq, row_hash FROM %I.%I WHERE chain_seq IS NOT NULL '
                           'ORDER BY chain_seq DESC LIMIT 1', TG_TABLE_SCHEMA, TG_TABLE_NAME)
                INTO last_seq, last_hash;
            NEW.chain_seq := COALESCE(last_seq, 0) + 1;
            NEW.prev_hash := COALESCE(last_hash, '{AUDIT_GENESIS}');
            NEW.row_hash := encode(sha256(convert_to(concat_ws('|',
                NEW.id::text, NEW.chain_seq::text, NEW.prev_hash,
                {stamp},
                {fields}), 'UTF8')), 'hex');
            RETURN NEW;
        END $$""",
            f'DROP TRIGGER IF EXISTS contract_audit_event_chain ON {prefix}contract_audit_event',
            f'CREATE TRIGGER contract_audit_event_chain BEFORE INSERT ON {prefix}contract_audit_event '
            f'FOR EACH ROW EXECUTE PROCEDURE {prefix}contract_audit_chain()',
            f'CREATE UNIQUE INDEX IF NOT EXISTS uq_contract_audit_event_chain_seq '
            f'ON {prefix}contract_audit_event (chain_seq)']


def audit_backfill_sql(prefix):
    """Chain the rows written before the chain existed, oldest first. Run
    once, by migration 0031, with the frozen trigger briefly off -- it only
    fills the three new columns in."""
    args = ', '.join(f'{prefix}audit_field(r.{k}::text)' for k in AUDIT_FIELDS)
    return [
        f'ALTER TABLE {prefix}contract_audit_event DISABLE TRIGGER contract_audit_event_frozen',
        f"""
        DO $$
        DECLARE
            r record;
            prev text := '{AUDIT_GENESIS}';
            seq bigint := 0;
            h text;
        BEGIN
            FOR r IN SELECT * FROM {prefix}contract_audit_event WHERE chain_seq IS NULL ORDER BY id LOOP
                seq := seq + 1;
                h := encode(sha256(convert_to(concat_ws('|', r.id::text, seq::text, prev,
                    {prefix}audit_field(to_char(r.created_at, 'YYYY-MM-DD"T"HH24:MI:SS.US')),
                    {args}), 'UTF8')), 'hex');
                UPDATE {prefix}contract_audit_event
                   SET chain_seq = seq, prev_hash = prev, row_hash = h WHERE id = r.id;
                prev := h;
            END LOOP;
        END $$""",
        f'ALTER TABLE {prefix}contract_audit_event ENABLE TRIGGER contract_audit_event_frozen']


def guard_sql(prefix=''):
    """Migration 0029's guards, exactly as it installs them."""
    return frozen_sql(prefix, FROZEN_0029) + ownership_sql(prefix)


def install_guards(conn, schema=None):
    """Every guard, for a schema built by create_all() rather than by the
    migrations -- a restored backup. Postgres only; a no-op elsewhere."""
    from sqlalchemy import text
    if conn.dialect.name != 'postgresql':
        return
    prefix = f'"{schema}".' if schema else ''
    for statement in (frozen_sql(prefix, FROZEN_TABLES) + kept_sql(prefix, KEPT_TABLES)
                      + ownership_sql(prefix) + audit_chain_sql(prefix)):
        conn.execute(text(statement))
