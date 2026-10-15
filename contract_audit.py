"""The trail behind every quote and agreement: who did what, when, from where.

record() adds one ContractAuditEvent to the current transaction -- it never
commits -- so an event exists exactly when the change it describes does: a
send that rolls back leaves no "sent", and an acceptance that commits always
has its "accepted". The one exception is a refusal (a stale page, a closed
offer), which changes nothing else and is committed on its own by
refused().

Rows are never edited: the ORM refuses (models._evidence_is_permanent) and,
on Postgres, so does the database (migration 0030).
"""
import json
import uuid


def _request_bits():
    """(ip, request id, logged-in name or None) for the request in hand."""
    try:
        from flask import g, has_request_context, session
    except ImportError:
        return None, None, None
    if not has_request_context():
        return None, None, None
    from security import client_ip
    if not getattr(g, 'contract_request_id', None):
        g.contract_request_id = uuid.uuid4().hex
    who = (session.get('user_name') or 'owner') if session.get('logged_in') else None
    return client_ip(), g.contract_request_id, who


def record(event, quote=None, revision=None, agreement=None, actor_kind=None, actor=None, **detail):
    """Append one event. actor_kind defaults to 'staff' for a logged-in
    request and 'customer' otherwise; actor to the login's name."""
    from extensions import db
    from models import ContractAuditEvent
    ip, request_id, who = _request_bits()
    kind = actor_kind or ('staff' if who else 'customer')
    row = ContractAuditEvent(
        event=event[:40],
        quote_id=getattr(quote, 'id', quote),
        revision_id=getattr(revision, 'id', revision),
        agreement_id=getattr(agreement, 'id', agreement),
        actor_kind=kind,
        actor=(actor if actor is not None else who) and str(actor if actor is not None else who)[:200],
        ip_address=ip,
        request_id=request_id,
        detail=json.dumps({k: v for k, v in detail.items() if v is not None},
                          sort_keys=True, default=str) if detail else None,
    )
    db.session.add(row)
    return row


def standalone(event, quote, **detail):
    """An event about something that was not done -- an answer refused, an
    answer that failed -- committed on its own, after whatever the request
    had pending is rolled back. Never raises: failing to log a refusal must
    not turn it into an error page."""
    from extensions import db
    quote_id = getattr(quote, 'id', quote)
    try:
        db.session.rollback()
        record(event, quote=quote_id, **detail)
        db.session.commit()
    except Exception:
        db.session.rollback()


def refused(quote, reason, **detail):
    """An answer the customer's page sent that was not taken."""
    standalone('answer_refused', quote, reason=reason, **detail)


def trail(quote_id, limit=100):
    """A quote's events, newest first, with detail decoded."""
    from models import ContractAuditEvent
    rows = (ContractAuditEvent.query.filter_by(quote_id=quote_id)
            .order_by(ContractAuditEvent.created_at.desc(), ContractAuditEvent.id.desc())
            .limit(limit).all())
    out = []
    for r in rows:
        try:
            d = json.loads(r.detail) if r.detail else {}
        except ValueError:
            d = {}
        out.append((r, d))
    return out


LABELS = {
    'created': 'Created',
    'draft_saved': 'Draft saved',
    'draft_deleted': 'Draft deleted',
    'sent': 'Sent',
    'resent': 'Sent again',
    'send_failed': 'Not sent',
    'viewed': 'First opened by the customer',
    'withdrawn': 'Withdrawn',
    'revised': 'Replaced by a revision',
    'amendment_started': 'Amendment started',
    'accepted': 'Accepted',
    'declined': 'Declined',
    'answer_refused': 'Answer refused',
    'answer_failed': 'Answer not recorded (error)',
    'agreement_executed': 'Agreement executed',
    'delivered': 'Delivered',
    'bounced': 'Bounced',
    'complained': 'Marked as spam',
    'delivery_delayed': 'Delivery delayed',
}
