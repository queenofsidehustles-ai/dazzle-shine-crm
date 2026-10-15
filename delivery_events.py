"""What the email service said became of a message, filed where it belongs.

A Resend webhook event names the message by the id Resend gave it when we
sent it (OutboundLog.provider_id, QuoteDelivery.provider_message_id) and,
through the tag notifications._tenant_tags() put on it, the company schema it
was sent from. This keeps the event and notes what happened:

  * an EmailDeliveryEvent, by message id and recipient -- kept whether or not
    anything of ours matches yet. A "delivered" can arrive before the send
    that caused it has committed its own rows (the quote's send commits after
    the provider answers); keyed by message id rather than by a row of ours,
    it is there when that row is. One per provider event id: a retry, or an
    old event replayed, is recorded once and changes nothing;
  * the Sent log row moves forward -- sent, delivered, bounced, complained --
    never back, and only for the recipient the event is about: a bounce at a
    CC'd address is not the customer's bounce;
  * a proposal's delivery gets an audit entry from the mail service.

Never sends anything.
"""
from datetime import datetime

KINDS = {
    'email.delivered': 'delivered',
    'email.bounced': 'bounced',
    'email.complained': 'complained',
    'email.delivery_delayed': 'delivery_delayed',
}
# How far along the Sent log's status is. An event only moves it forward, so
# a "delivered" arriving after a "complained" (a replay, a slow retry) cannot
# undo it. A delay is not an outcome and leaves the status alone.
RANK = {'sent': 0, 'delivered': 1, 'bounced': 2, 'complained': 3}


class Retry(Exception):
    """Something on our side, not the event: the caller answers non-2xx so
    the email service tries again later."""


def _tag(data, name):
    """A tag's value, whichever shape the payload uses: {"tenant": "x"} or
    [{"name": "tenant", "value": "x"}]."""
    tags = data.get('tags')
    if isinstance(tags, dict):
        return tags.get(name)
    if isinstance(tags, list):
        for t in tags:
            if isinstance(t, dict) and t.get('name') == name:
                return t.get('value')
    return None


def _when(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _recipients(data):
    to = data.get('to')
    if isinstance(to, str):
        to = [to]
    return [str(a).strip().lower() for a in (to or []) if str(a).strip()]


def _detail(kind, data):
    if kind == 'bounced':
        b = data.get('bounce') or {}
        bits = [b.get('type'), b.get('subType'), b.get('message')]
        return ' — '.join(str(x) for x in bits if x)[:400] or 'Bounced.'
    if kind == 'complained':
        return 'The recipient marked it as spam.'
    if kind == 'delivery_delayed':
        return 'The receiving server has not accepted it yet; the service is retrying.'
    return 'Accepted by the recipient\'s mail server.'


def _schema(tag):
    """The company schema a tag names, if it is one that exists; PUBLIC for no
    tag (a single-business install, or the platform's own mail); None for a
    tag naming nothing."""
    import re
    import tenancy
    from extensions import db
    from sqlalchemy import text
    if not tag:
        return tenancy.PUBLIC
    if not re.fullmatch(re.escape(tenancy.SCHEMA_PREFIX) + r'[a-z0-9_]{1,63}', tag):
        return None
    try:
        found = db.session.execute(text(
            'SELECT 1 FROM information_schema.schemata WHERE schema_name = :s'), {'s': tag}).first()
    except Exception as e:
        raise Retry(str(e))
    finally:
        db.session.rollback()
    return tag if found else None


def record(payload, event_id):
    """File one webhook event. Returns what happened, for the response body:
    'ignored', 'unknown_tenant', 'duplicate' or 'recorded'. Raises Retry when
    the failure is ours to recover from."""
    import tenancy
    kind = KINDS.get((payload or {}).get('type'))
    data = (payload or {}).get('data') or {}
    message_id = (data.get('email_id') or '').strip()[:100]
    if not kind or not message_id:
        return 'ignored'
    schema = _schema(_tag(data, 'tenant'))
    if schema is None:
        return 'unknown_tenant'
    try:
        with tenancy.use_tenant(schema):
            return _file(kind, message_id, (event_id or '')[:100] or None, _recipients(data),
                         _when(payload.get('created_at') or data.get('created_at')), _detail(kind, data))
    except Retry:
        raise
    except Exception as e:
        raise Retry(str(e))


def _file(kind, message_id, event_id, recipients, occurred_at, detail):
    from extensions import db
    from models import EmailDeliveryEvent, OutboundLog, QuoteDelivery
    import contract_audit
    # Deduplicate before touching anything else: a replay is a no-op.
    if event_id and EmailDeliveryEvent.query.filter_by(provider_event_id=event_id).first():
        db.session.rollback()
        return 'duplicate'
    recipient = ', '.join(recipients)[:200] or None
    db.session.add(EmailDeliveryEvent(provider_message_id=message_id, recipient=recipient, event=kind,
                                      provider_event_id=event_id, occurred_at=occurred_at, detail=detail))
    if kind in RANK:
        for row in OutboundLog.query.filter_by(provider_id=message_id).all():
            mine = not recipients or (row.to_address or '').strip().lower() in recipients
            if mine and row.status in RANK and RANK[kind] > RANK[row.status]:
                row.status = kind
                row.detail = f'Resend: {detail}'[:400]
    delivery = QuoteDelivery.query.filter_by(provider_message_id=message_id).first()
    if delivery is not None and about(delivery, recipient):
        contract_audit.record(kind, delivery.quote_id, delivery.revision_id, actor_kind='provider',
                              actor='resend', delivery_id=delivery.id, recipient=recipient,
                              provider_message_id=message_id, detail=detail)
    db.session.commit()
    return 'recorded'


def about(delivery, recipient):
    """Is an event for `recipient` about this delivery's addressee? An event
    naming nobody is taken to be."""
    if not recipient:
        return True
    return (delivery.recipient or '').strip().lower() in [r.strip() for r in recipient.split(',')]


def for_message(message_id, addressee=None):
    """The events recorded for one message, oldest first -- only those about
    `addressee`, when given."""
    from models import EmailDeliveryEvent
    if not message_id:
        return []
    rows = (EmailDeliveryEvent.query.filter_by(provider_message_id=message_id)
            .order_by(EmailDeliveryEvent.occurred_at, EmailDeliveryEvent.id).all())
    if addressee:
        a = addressee.strip().lower()
        rows = [r for r in rows if not r.recipient or a in [x.strip() for x in r.recipient.split(',')]]
    return rows


def audit_early(delivery):
    """At the send's own commit: audit entries for events the provider sent
    before that commit, which found no delivery to write them against."""
    import contract_audit
    for ev in for_message(delivery.provider_message_id, delivery.recipient):
        contract_audit.record(ev.event, delivery.quote_id, delivery.revision_id, actor_kind='provider',
                              actor='resend', delivery_id=delivery.id, recipient=ev.recipient,
                              provider_message_id=delivery.provider_message_id, detail=ev.detail,
                              arrived_before_send_committed=True)
