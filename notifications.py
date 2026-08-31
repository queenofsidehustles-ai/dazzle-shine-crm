import os
import re
import hmac
import hashlib
import base64
import requests as http_requests
import branding
import integrations


# An address has to have a domain with a dot and a real suffix. Deliberately
# not RFC-complete — the job is to catch a human typo, not to adjudicate the
# spec, and the only thing worse than letting a bad address through is
# rejecting somebody's real one.
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[a-z]{2,}$', re.I)


def looks_like_email(value):
    """True if this could plausibly be delivered to.

    `duffytyler96@gmail` — no `.com` — passes an `'@' in value` check and fails
    at Stripe, which rejects the address when the customer record is created.
    That happens *before* the payment intent exists, so a typo in an email
    address silently stopped a customer paying at all and left no trace in the
    Stripe dashboard to explain why. Anywhere an address is typed, it gets
    checked here first."""
    return bool(EMAIL_RE.match((value or '').strip()))


def _log_outbound(channel, to_address, to_name, subject, body, ok, detail,
                  provider_id=None):
    """Record every outbound SMS/email in OutboundLog so the owner has a single
    'Sent' history. Uses its OWN short-lived DB session so it can never touch or
    prematurely commit the caller's transaction. Never raises.

    provider_id is the id Resend or Twilio gave the message. Without it, a row
    saying "sent" is unfalsifiable — the customer says nothing arrived, the log
    says it went, and there is no way to find out which is true. With it the
    message can be looked up at the provider and actually traced."""
    try:
        from extensions import db
        from models import OutboundLog
        from sqlalchemy.orm import Session
        with Session(db.engine) as s:
            s.add(OutboundLog(
                channel=channel,
                to_address=(to_address or '')[:200],
                to_name=(to_name or None),
                subject=(subject or None),
                body=(body or ''),
                status='sent' if ok else 'failed',
                detail=(detail or '')[:400],
                provider_id=(provider_id or None),
            ))
            s.commit()
    except Exception:
        pass


# ── Marketing opt-out (unsubscribe) ─────────────────────────────────────────────

def _unsub_secret():
    return (os.environ.get('SECRET_KEY') or os.environ.get('FLASK_SECRET_KEY')
            or 'unsubscribe-fallback').encode()


def unsubscribe_token(email):
    """Signed, tamper-proof token that encodes an email for a one-click unsubscribe."""
    email = (email or '').strip().lower()
    sig = hmac.new(_unsub_secret(), email.encode(), hashlib.sha256).hexdigest()[:16]
    return base64.urlsafe_b64encode(f'{email}|{sig}'.encode()).decode().rstrip('=')


def verify_unsubscribe_token(token):
    """Return the email if the token is valid, else None."""
    try:
        pad = '=' * (-len(token) % 4)
        raw = base64.urlsafe_b64decode((token + pad).encode()).decode()
        email, sig = raw.rsplit('|', 1)
        good = hmac.new(_unsub_secret(), email.encode(), hashlib.sha256).hexdigest()[:16]
        return email if hmac.compare_digest(sig, good) else None
    except Exception:
        return None


def is_opted_out(email):
    from models import EmailOptOut
    if not email:
        return False
    return EmailOptOut.query.filter_by(email=email.strip().lower()).first() is not None


# ── Texting opt-out (STOP) ──────────────────────────────────────────────────────
#
# The carrier-standard keywords. Twilio acts on these itself and stops delivering
# to the number regardless of what we do, so matching them here is not what keeps
# us compliant — it is what lets the CRM know, so a sequence can drop someone
# instead of queueing texts into a void for another week.

SMS_STOP_WORDS = {'stop', 'stopall', 'unsubscribe', 'cancel', 'end', 'quit',
                  'stop all', 'optout', 'opt out', 'remove'}
SMS_START_WORDS = {'start', 'unstop', 'yes'}


def _phone10(p):
    digits = ''.join(ch for ch in (p or '') if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def sms_stop_word(body):
    """The opt-out word in a message, or None.

    Deliberately strict: only a message that is essentially *just* the keyword
    counts. "stop by at 9 instead" is someone rescheduling, and treating that as
    an opt-out would silently cut off a customer who was trying to talk to us."""
    text = (body or '').strip().lower().strip('.!? ')
    return text if text in SMS_STOP_WORDS else None


def sms_start_word(body):
    text = (body or '').strip().lower().strip('.!? ')
    return text if text in SMS_START_WORDS else None


def sms_opted_out(phone):
    from models import SmsOptOut
    p = _phone10(phone)
    if not p:
        return False
    return SmsOptOut.query.filter_by(phone=p).first() is not None


def record_sms_opt_out(phone, reason='stop'):
    """Add a number to the do-not-text list. Idempotent."""
    from models import SmsOptOut
    from extensions import db
    p = _phone10(phone)
    if not p or sms_opted_out(p):
        return False
    db.session.add(SmsOptOut(phone=p, reason=(reason or '')[:40]))
    db.session.commit()
    return True


def clear_sms_opt_out(phone):
    """They asked to hear from us again (START), or the owner cleared it by hand."""
    from models import SmsOptOut
    from extensions import db
    p = _phone10(phone)
    row = SmsOptOut.query.filter_by(phone=p).first() if p else None
    if not row:
        return False
    db.session.delete(row)
    db.session.commit()
    return True


def send_marketing_sms(to_phone, message):
    """A text that is marketing rather than service — a follow-up to someone who
    never booked, not a "your cleaner is on the way". Returns (ok, detail).

    Only these check the opt-out list. Transactional texts to a live booking
    deliberately do not: someone who stopped marketing still needs to be told
    their cleaner is outside, and Twilio makes the final call on a number that
    has genuinely opted out of everything."""
    if sms_opted_out(to_phone):
        detail = 'Not sent — this number has asked us to stop texting.'
        _log_outbound('sms', to_phone, None, None, message, False, detail)
        return False, detail
    return send_sms(to_phone, message)


def send_triggered_email(trigger, to_email, to_name, variables=None, unsubscribe_url=None,
                         append_text=None, append_unless=None):
    """Look up an EmailTemplate by trigger key, fill in variables, and send.
    If unsubscribe_url is given, an unsubscribe line is added to the footer
    (use for marketing emails). Returns True if sent, False otherwise.

    append_text adds a block to the end of the body, but only when the template
    doesn't already place it itself via append_unless (a placeholder such as
    '{{checklist}}'). Templates are editable and already exist on every running
    instance, so a variable added to a default today would never show up in a
    copy the owner had edited months ago — this way new content reaches both,
    and moving the placeholder into the template takes it out of the footer."""
    from models import EmailTemplate, BusinessSetting
    tmpl = EmailTemplate.query.filter_by(trigger=trigger, is_active=True).first()
    if not tmpl:
        return False
    biz = branding.biz_name()
    biz_phone = BusinessSetting.get('phone') or os.environ.get('BUSINESS_PHONE', '')
    v = {
        'business_name': biz,
        'phone': biz_phone,
        'first_name': to_name.split()[0] if to_name else '',
        'full_name': to_name or '',
    }
    if variables:
        v.update(variables)
    subject = _sub(tmpl.subject, v)
    raw_body = tmpl.body or ''
    if append_text and not (append_unless and append_unless in raw_body):
        raw_body = raw_body.rstrip() + '\n\n' + append_text
    body_text = _sub(raw_body, v)
    html = _wrap_html(body_text, biz, unsubscribe_url=unsubscribe_url)
    send_email(to_email=to_email, to_name=to_name, subject=subject,
               html=html, from_name=biz)
    return True


def _sub(text, variables):
    for key, val in variables.items():
        text = text.replace('{{' + key + '}}', str(val) if val is not None else '')
    return text


def _wrap_html(body_text, biz_name, unsubscribe_url=None):
    """Wrap plain-text email body in a branded HTML shell."""
    lines = body_text.replace('\r\n', '\n').split('\n')
    paragraphs = ''
    for line in lines:
        line = line.strip()
        if not line:
            paragraphs += '<br>'
        elif line.startswith('- ') or line[:2].rstrip('.').isdigit():
            paragraphs += f'<li style="margin-bottom:6px">{line.lstrip("- 0123456789.")}</li>'
        else:
            paragraphs += f'<p style="margin:0 0 10px">{line}</p>'
    unsub = ''
    if unsubscribe_url:
        unsub = (f'<br><a href="{unsubscribe_url}" style="color:#9a95ad;text-decoration:underline">'
                 f'Unsubscribe from these emails</a>')
    return f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <div style="background:linear-gradient(135deg,#1f1333,#3b2460);padding:28px 32px;border-radius:12px 12px 0 0">
    <p style="color:#d3a84f;font-size:1.1rem;font-weight:700;margin:0">{biz_name}</p>
  </div>
  <div style="background:#ffffff;padding:28px 32px;border-radius:0 0 12px 12px;border:1px solid #e4dfef;border-top:none">
    {paragraphs}
    <hr style="border:none;border-top:1px solid #e4dfef;margin:24px 0">
    <p style="font-size:0.78rem;color:#9a95ad;margin:0">{biz_name} · Questions? Reply to this email.{unsub}</p>
  </div>
</div>"""


def send_email(to_email, to_name, subject, html, from_name=None,
               from_email=None, reply_to=None):
    """Send via Resend. Returns (ok: bool, detail: str) so callers/diagnostics
    can see what happened. Existing callers that ignore the return value are
    unaffected. from_email/reply_to let a branded caller (e.g. a commercial
    quote) override the sender identity per brand."""
    api_key = integrations.resend_api_key()
    from_email = from_email or branding.from_email()
    if not from_name:
        from_name = branding.biz_name()
    if not api_key:
        # Log it. Returning silently made a missing key look like nothing was
        # ever attempted — the Sent Log stayed empty and there was no way to
        # tell "we tried and failed" from "we never tried".
        detail = 'Email not connected — add your email service key in Settings → Connections.'
        _log_outbound('email', to_email, to_name, subject, html, False, detail)
        return False, detail
    if not to_email:
        detail = 'No email address on this record to send to.'
        _log_outbound('email', to_email, to_name, subject, html, False, detail)
        return False, detail
    # Replies go to the inbox Monica actually checks, even though the email is
    # sent "from" the branded domain address.
    reply_to = reply_to or os.environ.get('REPLY_TO_EMAIL') or \
        branding.owner_email()
    try:
        resp = http_requests.post(
            'https://api.resend.com/emails',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'from': f'{from_name} <{from_email}>',
                'to': [to_email],
                'reply_to': reply_to,
                'subject': subject,
                'html': html,
            },
            timeout=10,
        )
        if 200 <= resp.status_code < 300:
            # "Accepted", not "delivered" — and the difference is the whole
            # problem. A 2xx here means Resend took the message, nothing more.
            # It can still bounce, or land in spam, and this log would happily
            # say Sent while the customer sees nothing. Recording the provider's
            # own id is what turns "it says sent" into something traceable: it
            # can be pasted into the Resend dashboard to see what really
            # happened to that specific email.
            try:
                msg_id = (resp.json() or {}).get('id') or ''
            except ValueError:
                msg_id = ''
            detail = f'Accepted by Resend from {from_email}'
            detail += f' (id {msg_id}).' if msg_id else '. No message id returned.'
            ok = True
        else:
            ok, msg_id = False, ''
            detail = f'Resend error {resp.status_code}: {resp.text[:400]}'
    except Exception as e:
        ok, msg_id, detail = False, '', f'Could not reach Resend: {e}'
    _log_outbound('email', to_email, to_name, subject, html, ok, detail,
                  provider_id=msg_id)
    return ok, detail


def add_to_mailerlite(email, name, group_id=None):
    api_key = os.environ.get('MAILERLITE_API_KEY')
    if not group_id:
        group_id = os.environ.get('MAILERLITE_GROUP_ID', '189490896944760797')
    if not api_key:
        return
    try:
        http_requests.post(
            'https://connect.mailerlite.com/api/subscribers',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'email': email,
                'fields': {'name': name},
                'groups': [group_id],
            },
            timeout=10,
        )
    except Exception:
        pass


def send_sms(to_phone, message):
    """Send an SMS via Twilio. Returns (ok: bool, detail: str) so diagnostics
    can surface the real reason a text failed. Existing callers ignore the return."""
    # The free plan sends no texts, and this is the only limit in the product
    # that is about money rather than product design: every message costs real
    # cash, every month, forever, to somebody who has never paid anything. It is
    # enforced here rather than at each of the two dozen call sites, because one
    # of those would eventually be missed and nobody would notice until the bill.
    #
    # Email is untouched, so a free business is never unable to reach its
    # customers -- only unable to do it by text.
    try:
        import entitlements
        if not entitlements.can('sms'):
            entitlements.record_denial('sms', path='send_sms')
            return False, 'Texting is part of the Pro plan. This was not sent.'
    except Exception:
        pass          # never let a plan check be the reason a text fails
    account_sid = integrations.twilio_account_sid()
    auth_token = integrations.twilio_auth_token()
    from_phone = integrations.twilio_phone()
    if not all([account_sid, auth_token, from_phone]):
        missing = integrations.missing_for('texting')
        # Log it rather than returning silently — an unconfigured Twilio used to
        # leave the Sent Log completely empty, which reads as "nothing happened"
        # when the truth is "nothing could happen, and here's why".
        detail = ('Texting not connected — add it in Settings → Connections. '
                  'Still needed: ' + ', '.join(missing))
        _log_outbound('sms', to_phone, None, None, message, False, detail)
        return False, detail
    if not to_phone:
        detail = 'No phone number on this record to send to.'
        _log_outbound('sms', to_phone, None, None, message, False, detail)
        return False, detail
    try:
        from twilio.rest import Client
        digits = ''.join(filter(str.isdigit, to_phone))
        formatted = ('+1' + digits) if not to_phone.startswith('+') else to_phone
        client = Client(account_sid, auth_token)
        msg = client.messages.create(body=message, from_=from_phone, to=formatted)
        ok, sid = True, msg.sid
        detail = f'Accepted by Twilio for {formatted} (id {sid}).'
    except Exception as e:
        ok, sid, detail = False, '', f'Twilio error: {e}'
    _log_outbound('sms', to_phone, None, None, message, ok, detail, provider_id=sid)
    return ok, detail
