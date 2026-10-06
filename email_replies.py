"""Getting a prospect's reply back to the company that wrote to them.

An introduction sent from the call sheet goes out from the company's own
domain, and a reply to it goes wherever Reply-To says. That used to be the
owner's mailbox, which meant the CRM never learned anybody had answered: the
chase still fired on Thursday for somebody who wrote back on Tuesday, and the
best prospect on the list got nagged for replying.

So the reply comes back here first. Every outreach email carries its own
Reply-To, and that address says which company and which business it belongs
to -- unlike the texting relay, which has to work it out from who wrote to the
person most recently, because a phone number carries nothing.

The address lives on the platform's domain, not the company's. One MX record
on akyehq.com set up once serves every company forever, and a company that has
already proved a sending domain should not also have to run a mail server.
What the recipient sees is still the company: the From line is theirs, which
is the line a person reads.

  <slug>-<id>-<sig>@reply.akyehq.com

The signature is what stops it being a way to write into somebody else's CRM.
Prospect ids are small integers and they repeat in every company's schema, so
an address without one would let anybody who can send an email append notes to
any record they could guess the number of.
"""
import hashlib
import hmac
import os
import re

# <slug>-<id>-<sig>, where slug may itself contain hyphens.
ADDRESS = re.compile(r'^(?P<slug>[a-z0-9-]+)-(?P<id>\d+)-(?P<sig>[0-9a-f]{12})$')

SIG_LENGTH = 12


def domain():
    """Where replies are received. Empty means the feature is switched off."""
    return (os.environ.get('REPLY_DOMAIN') or '').strip().lower()


def _secret():
    from flask import current_app
    try:
        return str(current_app.config.get('SECRET_KEY') or '')
    except Exception:
        return os.environ.get('SECRET_KEY') or ''


def _sign(slug, prospect_id):
    msg = f'{slug}:{prospect_id}'.encode()
    return hmac.new(_secret().encode(), msg, hashlib.sha256).hexdigest()[:SIG_LENGTH]


def address_for(slug, prospect_id):
    """The Reply-To for one company's prospect, or '' when switched off."""
    host = domain()
    slug = (slug or '').strip().lower()
    if not host or not slug or not prospect_id:
        return ''
    return f'{slug}-{prospect_id}-{_sign(slug, prospect_id)}@{host}'


def parse(address):
    """(slug, prospect_id) for an address we issued, or None.

    None covers every way this can be somebody else's mail: a different
    domain, a malformed local part, or a signature that does not check out.
    Compared in constant time, because a signature that leaks its length under
    timing is not a signature.
    """
    host = domain()
    addr = (address or '').strip().lower()
    if not host or '@' not in addr:
        return None
    local, _, got_host = addr.partition('@')
    if got_host != host:
        return None
    m = ADDRESS.match(local)
    if not m:
        return None
    slug, pid, sig = m.group('slug'), int(m.group('id')), m.group('sig')
    if not hmac.compare_digest(sig, _sign(slug, pid)):
        return None
    return slug, pid


def pick_address(payload):
    """The address we issued, out of everything the message was sent to.

    A reply carries To, Cc and whatever the mail client decided to keep, and
    only one of them is ours. Checking all of them means a reply that also
    copies a colleague still lands.
    """
    seen = []
    for key in ('to', 'cc', 'bcc'):
        value = (payload or {}).get(key)
        if isinstance(value, str):
            seen.extend(re.findall(r'[^\s<>,;"]+@[^\s<>,;"]+', value))
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str):
                    seen.extend(re.findall(r'[^\s<>,;"]+@[^\s<>,;"]+', item))
                elif isinstance(item, dict):
                    seen.extend(re.findall(r'[^\s<>,;"]+@[^\s<>,;"]+',
                                           str(item.get('address') or item.get('email') or '')))
    for candidate in seen:
        found = parse(candidate)
        if found:
            return found
    return None


def current_slug():
    """This company's slug, for building a reply address.

    g.tenant_slug inside a request, and the control plane outside one. Never
    reversed out of the schema name: schema_for() turns every hyphen into an
    underscore and final-touch-group-llc cannot be recovered from
    tenant_final_touch_group_llc.
    """
    try:
        from flask import g
        slug = (getattr(g, 'tenant_slug', None) or '').strip()
        if slug:
            return slug
    except Exception:
        pass
    try:
        import tenancy
        from extensions import db
        from sqlalchemy import text as _sa_text
        if not tenancy.is_tenant():
            return ''
        row = db.session.execute(_sa_text(
            'SELECT slug FROM public.organizations WHERE schema_name = :s'),
            {'s': tenancy.current_schema()}).first()
        return (row[0] if row else '') or ''
    except Exception:
        return ''


def record(slug, prospect_id, from_address, subject, body):
    """Put a reply where the company will see it, and stop the chase.

    Three things, in the order they matter. The owner is sent the reply,
    because a message sitting in a CRM nobody has opened today is a message
    nobody has read. The prospect's record keeps it, so the next call starts
    from what they said. And the follow-up stops being a chase: somebody who
    has written back should get a person, not the next scheduled nudge.

    The forward is addressed so that hitting reply in her own mail client
    reaches the prospect, not us.
    """
    from datetime import datetime
    from html import escape

    from extensions import db
    from models import Prospect, BusinessSetting
    from scheduling import local_today
    import prospecting

    prospect = Prospect.query.get(prospect_id)
    if prospect is None:
        return False, 'No such business in that company.'

    said = (body or '').strip()
    snippet = said if len(said) <= 400 else said[:400] + '…'
    prospect.notes = prospecting.note_entry(
        prospect, f'Replied — {subject or "(no subject)"}\n{snippet}')

    # A reply is an answer, not a step in a sequence. Whatever was scheduled
    # for them stops, and what is due is that somebody reads it.
    prospect.next_action = 'They replied — read it'
    prospect.next_action_date = local_today().isoformat()
    if prospect.stage in (None, 'new', 'working'):
        prospect.stage = 'interested'
    prospect.sequence = None
    db.session.commit()

    to = (BusinessSetting.get('email') or '').strip()
    if to:
        try:
            import product
            from notifications import send_email
            html = ('<p style="font-family:Inter,Arial,sans-serif;color:#555">'
                    f'<strong>{escape(prospect.business_name or "A business")}</strong> '
                    'replied to your introduction.</p>'
                    '<div style="font-family:Inter,Arial,sans-serif;font-size:15px;'
                    'line-height:1.65;white-space:pre-wrap;border-left:3px solid #ddd;'
                    'padding-left:12px">' + escape(said) + '</div>')
            send_email(to, None, f'Reply from {prospect.business_name}: {subject or ""}'.strip(),
                       html, from_name=product.name(),
                       from_email=product.from_email(),
                       reply_to=(from_address or prospect.email or None),
                       api_key=product.resend_api_key())
        except Exception:
            # The reply is already saved. Failing to forward it must not undo
            # that, or a mail outage loses the message outright.
            pass
    return True, f'Recorded against {prospect.business_name}.'
