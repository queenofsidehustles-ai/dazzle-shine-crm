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
FROZEN_TABLES = ('commercial_quote_revision', 'commercial_quote_response')


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
    quote sent before revisions existed)."""
    from models import QuoteRevision
    if not q.issued_revision_id:
        return None
    return QuoteRevision.query.get(q.issued_revision_id)


def intact(rev):
    """Its stored terms still hash to its stored hash."""
    return bool(rev) and digest(rev.terms) == rev.content_hash


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
        self.content_hash = rev.content_hash

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


def install_guards(conn, schema=None):
    """The UPDATE-refusing trigger on the frozen tables, for a schema built by
    create_all() rather than by migration 0029 -- a restored backup. Postgres
    only; a no-op elsewhere."""
    from sqlalchemy import text
    if conn.dialect.name != 'postgresql':
        return
    prefix = f'"{schema}".' if schema else ''
    conn.execute(text(f"""
        CREATE OR REPLACE FUNCTION {prefix}quote_evidence_frozen() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% rows are evidence and are never changed', TG_TABLE_NAME;
        END $$"""))
    for table in FROZEN_TABLES:
        conn.execute(text(f'DROP TRIGGER IF EXISTS {table}_frozen ON {prefix}{table}'))
        conn.execute(text(f'CREATE TRIGGER {table}_frozen BEFORE UPDATE ON {prefix}{table} '
                          f'FOR EACH ROW EXECUTE PROCEDURE {prefix}quote_evidence_frozen()'))
