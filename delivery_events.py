"""What the email service said became of a message, filed where it belongs.

A Resend webhook event names the message by the id Resend gave it when we
sent it (OutboundLog.provider_id, QuoteDelivery.provider_message_id) and,
through the tag notifications._tenant_tags() put on it, the company it was
sent for. This finds the message in that company's records and notes what
happened:

  * the Sent log row reads delivered / bounced / complained, instead of a
    "sent" that only ever meant the service took it;
  * a proposal's delivery gets a QuoteDeliveryEvent -- one per provider event
    id, so a retried webhook is recorded once -- and its audit trail an entry
    from the mail service.

Never sends anything.
"""
from datetime import datetime

KINDS = {
    'email.delivered': 'delivered',
    'email.bounced': 'bounced',
    'email.complained': 'complained',
    'email.delivery_delayed': 'delivery_delayed',
}
# What the Sent log shows. A delay is not an outcome, so it leaves "sent" alone.
LOG_STATUS = {'delivered': 'delivered', 'bounced': 'bounced', 'complained': 'complained'}


def _tag(data, name):
    """A tag's value, whichever shape the payload uses: {"tenant": "acme"}
    or [{"name": "tenant", "value": "acme"}]."""
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


def record(payload, event_id):
    """File one webhook event. Returns what happened, for the response body:
    'ignored', 'unknown_tenant', 'not_found', 'duplicate' or 'recorded'."""
    import tenancy
    kind = KINDS.get((payload or {}).get('type'))
    data = (payload or {}).get('data') or {}
    message_id = (data.get('email_id') or '').strip()
    if not kind or not message_id:
        return 'ignored'
    slug = _tag(data, 'tenant')
    if not slug or not tenancy.valid_slug(slug):
        return 'unknown_tenant'
    with tenancy.use_tenant(slug):
        return _file(kind, message_id, (event_id or '')[:100] or None,
                     _when(payload.get('created_at') or data.get('created_at')), _detail(kind, data))


def _file(kind, message_id, event_id, occurred_at, detail):
    from extensions import db
    from models import OutboundLog, QuoteDelivery, QuoteDeliveryEvent
    import contract_audit
    found = False
    status = LOG_STATUS.get(kind)
    for row in OutboundLog.query.filter_by(provider_id=message_id).all():
        found = True
        if status:
            row.status = status
            row.detail = f'Resend: {detail}'[:400]
    delivery = QuoteDelivery.query.filter_by(provider_message_id=message_id).first()
    if delivery is not None:
        found = True
        if event_id and QuoteDeliveryEvent.query.filter_by(provider_event_id=event_id).first():
            db.session.commit()
            return 'duplicate'
        db.session.add(QuoteDeliveryEvent(delivery_id=delivery.id, event=kind, provider_event_id=event_id,
                                          occurred_at=occurred_at, detail=detail))
        contract_audit.record(kind, delivery.quote_id, delivery.revision_id, actor_kind='provider',
                              actor='resend', delivery_id=delivery.id, recipient=delivery.recipient,
                              provider_message_id=message_id, detail=detail)
    db.session.commit()
    return 'recorded' if found else 'not_found'
