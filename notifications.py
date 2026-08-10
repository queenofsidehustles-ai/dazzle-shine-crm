import os
import hmac
import hashlib
import base64
import requests as http_requests
import branding
import integrations


def _log_outbound(channel, to_address, to_name, subject, body, ok, detail):
    """Record every outbound SMS/email in OutboundLog so the owner has a single
    'Sent' history. Uses its OWN short-lived DB session so it can never touch or
    prematurely commit the caller's transaction. Never raises."""
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


def send_triggered_email(trigger, to_email, to_name, variables=None, unsubscribe_url=None):
    """Look up an EmailTemplate by trigger key, fill in variables, and send.
    If unsubscribe_url is given, an unsubscribe line is added to the footer
    (use for marketing emails). Returns True if sent, False otherwise."""
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
    body_text = _sub(tmpl.body, v)
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
            ok, detail = True, f'Sent OK (from {from_email}).'
        else:
            ok, detail = False, f'Resend error {resp.status_code}: {resp.text[:400]}'
    except Exception as e:
        ok, detail = False, f'Could not reach Resend: {e}'
    _log_outbound('email', to_email, to_name, subject, html, ok, detail)
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
        ok, detail = True, f'Sent OK to {formatted} (Twilio id {msg.sid}).'
    except Exception as e:
        ok, detail = False, f'Twilio error: {e}'
    _log_outbound('sms', to_phone, None, None, message, ok, detail)
    return ok, detail
