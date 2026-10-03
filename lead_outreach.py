"""Email and text Akye's own prospects from the console.

These are the product writing to people who are not companies yet -- the
New Leads list, uploaded or from the early-access form. So everything here is
the product's, never a cleaning company's:

  email   the product's Resend key, sent from product.outreach_from_email():
          a domain of its own, so complaints about cold mail stay off the
          domain that sends receipts and trial reminders.
  texts   the product's own Twilio number: PRODUCT_TWILIO_ACCOUNT_SID,
          PRODUCT_TWILIO_AUTH_TOKEN, PRODUCT_TWILIO_PHONE. Deliberately no
          fallback to TWILIO_*: those are the platform keys a company with no
          number of its own texts its customers through, and a prospect must
          never get Akye's pitch from a cleaning company's number.

Cold outreach has rules, and they are enforced here rather than left to
whoever presses the button:

  * Every email carries a one-click unsubscribe link and the company's postal
    address (CAN-SPAM). An unsubscribed address is never emailed again.
  * Every text says who it is from and how to stop ("Reply STOP to opt out").
    A number that replied STOP is never texted again (see sms_inbound()), nor
    is a lead the console marked "do not text" (on the Do Not Call list, say).
  * Texts only go out between 11am and 8pm Eastern -- 8am to 5pm Pacific -- so
    nobody in the continental US gets one before 8am or after 8pm.
  * A bulk send skips anyone reached on that channel in the last 7 days, and
    sends at most MAX_BULK at a time.

Whether texting a given list is lawful at all -- the TCPA and state laws such
as Florida's FTSA turn on the consent the person gave -- is a decision for the
people sending, before they upload. This module makes the sending itself clean
and traceable; it cannot make an unconsented list consented.
"""
import hashlib
import hmac
import html as _html
import os
from datetime import datetime, timedelta

import product

# Per click, not per day. Each email or text is a call to Resend or Twilio
# made inside the request, and the web worker gives a request 30-60 seconds:
# 200 sends ran past that, so the worker was killed half way through and the
# page errored for everybody. Fifty fits comfortably. Pressing send again picks
# up the rest, because anyone just reached is skipped for 7 days.
MAX_BULK = 50
RECENT = timedelta(days=7)
SMS_MAX_CHARS = 480            # three segments; past that it is not a text
STOP_LINE = 'Reply STOP to opt out.'


# ── Where links point ───────────────────────────────────────────────────────

def site():
    """The product's public site. Not the bare domain -- akyehq.com only
    answers "/", so a link there to /signup goes nowhere."""
    host = product.canonical_host()
    if not host:
        d = (product.domain() or '').lower()
        host = d if (not d or d.startswith('www.')) else f'www.{d}'
    return f'{product.scheme_for(host)}://{host}' if host else ''


def signup_url(medium):
    return (f'{site()}/signup?utm_source=outreach&utm_medium={medium}'
            f'&utm_campaign=lead_invite')


# ── Unsubscribe links (email) ───────────────────────────────────────────────

def _secret():
    return ('lead-unsubscribe:' + (os.environ.get('SECRET_KEY') or '')).encode()


def unsubscribe_token(email):
    email = (email or '').strip().lower()
    sig = hmac.new(_secret(), email.encode(), hashlib.sha256).hexdigest()[:20]
    import base64
    return base64.urlsafe_b64encode(f'{email}|{sig}'.encode()).decode().rstrip('=')


def email_from_token(token):
    import base64
    try:
        raw = base64.urlsafe_b64decode((token + '=' * (-len(token) % 4)).encode()).decode()
        email, sig = raw.rsplit('|', 1)
        good = hmac.new(_secret(), email.encode(), hashlib.sha256).hexdigest()[:20]
        return email if hmac.compare_digest(sig, good) else None
    except Exception:
        return None


def unsubscribe_url(email):
    return f'{site()}/leads/unsubscribe/{unsubscribe_token(email)}'


# ── Filling in a message ────────────────────────────────────────────────────

def first_name(lead):
    return (lead.get('name') or '').split()[0] if lead.get('name') else ''


def fill(template, lead, medium):
    """{first_name}, {name}, {company} and {signup_link}, and nothing else --
    str.format on text somebody typed would choke on any other brace."""
    values = {
        '{first_name}': first_name(lead) or 'there',
        '{name}': lead.get('name') or '',
        '{company}': lead.get('company') or 'your business',
        '{signup_link}': signup_url(medium),
    }
    out = template or ''
    for key, val in values.items():
        out = out.replace(key, val)
    return out


def default_email():
    n = product.name()
    return (f'Try {n} free', (
        f'Hi {{first_name}},\n\n'
        f'We built {n} to run a cleaning business like {{company}} end to end -- '
        f'scheduling, the team, quotes, hiring, and getting paid -- and thought '
        f'it was worth a look.\n\n'
        f'No card needed to try it: {{signup_link}}\n\n'
        f'Questions? Just reply -- a person reads it.'))


def default_text():
    n = product.name()
    return (f'Hi {{first_name}}, {n} here -- software that runs a cleaning business '
            f'end to end: scheduling, team, quotes and pay. Try it free: {{signup_link}}')


# ── Who can be reached ──────────────────────────────────────────────────────

def email_block(lead, now=None, bulk=False):
    """Why this lead cannot be emailed now, or None."""
    if not (lead.get('email') or '').strip():
        return 'no email address'
    if lead.get('unsubscribed_at'):
        return 'unsubscribed'
    if bulk and lead.get('last_emailed_at') and \
            lead['last_emailed_at'] > (now or datetime.utcnow()) - RECENT:
        return 'emailed in the last 7 days'
    return None


def sms_block(lead, now=None, bulk=False):
    """Why this lead cannot be texted now, or None."""
    digits = ''.join(ch for ch in (lead.get('phone') or '') if ch.isdigit())
    if len(digits) < 10:
        return 'no usable phone number'
    if lead.get('sms_opted_out_at'):
        return 'replied STOP'
    if lead.get('do_not_text_at'):
        return 'marked do not text'
    if bulk and lead.get('last_texted_at') and \
            lead['last_texted_at'] > (now or datetime.utcnow()) - RECENT:
        return 'texted in the last 7 days'
    return None


def quiet_hours(now_utc=None):
    """Why texts cannot go out right now, or None. 11am-8pm Eastern keeps every
    continental US time zone inside 8am-8pm."""
    from zoneinfo import ZoneInfo
    from datetime import timezone
    now = (now_utc or datetime.utcnow()).replace(tzinfo=timezone.utc)
    eastern = now.astimezone(ZoneInfo('America/New_York'))
    if 11 <= eastern.hour < 20:
        return None
    return ('texts only go out 11am-8pm Eastern (8am-8pm in every US time zone); '
            f'it is {eastern.strftime("%-I:%M %p")} Eastern now')


def sms_credentials():
    sid = (os.environ.get('PRODUCT_TWILIO_ACCOUNT_SID') or '').strip()
    token = (os.environ.get('PRODUCT_TWILIO_AUTH_TOKEN') or '').strip()
    phone = (os.environ.get('PRODUCT_TWILIO_PHONE') or '').strip()
    return (sid, token, phone) if (sid and token and phone) else None


def email_ready():
    return bool(product.resend_api_key())


# ── Sending ─────────────────────────────────────────────────────────────────

def email_html(body_text, to_email):
    paras = ''.join(
        f'<p style="margin:0 0 14px">{_html.escape(p).replace(chr(10), "<br>")}</p>'
        for p in (body_text or '').strip().split('\n\n') if p.strip())
    address = ', '.join(product.legal_address())
    entity = product.legal_entity() or product.name()
    return f'''
<div style="font-family:-apple-system,Segoe UI,Inter,sans-serif;max-width:540px;
            margin:0 auto;color:#16213a;line-height:1.55;font-size:15px">
  {paras}
  <p style="color:#7a8499;font-size:12px;margin-top:28px;border-top:1px solid #e6eaf2;
            padding-top:14px">
    {_html.escape(entity)}{(' · ' + _html.escape(address)) if address else ''}<br>
    Not interested? <a href="{unsubscribe_url(to_email)}" style="color:#7a8499">Unsubscribe</a>
    and we will not email you again.
  </p>
</div>'''


def sms_text(body):
    """Say who it is from and how to stop, whatever was typed."""
    body = (body or '').strip()
    if product.name().lower() not in body.lower():
        body = f'{product.name()}: {body}'
    if 'stop' not in body.lower():
        body = f'{body} {STOP_LINE}'
    return body


def send_email(engine, lead, subject, body_template, sent_by):
    """(ok, detail). Checked, sent on the product's key, and written down."""
    import control_plane
    import notifications
    block = email_block(lead)
    body = fill(body_template, lead, 'email')
    subject = fill(subject, lead, 'email').strip() or default_email()[0]
    if block:
        return False, block
    to = lead['email'].strip().lower()
    ok, detail = notifications.send_email(
        to, lead.get('name') or '', subject, email_html(body, to),
        from_name=product.name(),
        from_email=product.outreach_from_email() or None,
        reply_to=product.outreach_reply_to() or None,
        api_key=product.resend_api_key() or None)
    control_plane.record_lead_message(engine, lead['id'], 'email', to, subject,
                                      body, ok, detail, sent_by)
    return ok, detail


def send_text(engine, lead, body_template, sent_by, now_utc=None):
    """(ok, detail). Checked, sent from the product's own number, written down."""
    import control_plane
    block = sms_block(lead) or control_plane.number_text_block(engine, lead.get('phone'))
    if block:
        return False, block
    creds = sms_credentials()
    if not creds:
        return False, ('texting is not set up for the console -- set '
                       'PRODUCT_TWILIO_ACCOUNT_SID, PRODUCT_TWILIO_AUTH_TOKEN '
                       'and PRODUCT_TWILIO_PHONE')
    closed = quiet_hours(now_utc)
    if closed:
        return False, closed
    body = sms_text(fill(body_template, lead, 'sms'))
    if len(body) > SMS_MAX_CHARS:
        return False, f'the text is {len(body)} characters; keep it under {SMS_MAX_CHARS}'
    digits = ''.join(ch for ch in lead['phone'] if ch.isdigit())
    to = lead['phone'] if lead['phone'].strip().startswith('+') else '+1' + digits[-10:]
    sid, token, from_phone = creds
    try:
        from twilio.rest import Client
        msg = Client(sid, token).messages.create(body=body, from_=from_phone, to=to)
        ok, detail = True, f'accepted by Twilio (id {msg.sid})'
    except Exception as e:
        ok, detail = False, f'Twilio error: {e}'
    control_plane.record_lead_message(engine, lead['id'], 'sms', to, None,
                                      body, ok, detail, sent_by)
    return ok, detail


def send_many(engine, leads, channel, subject, body_template, sent_by, now_utc=None):
    """Send to a list, skipping whoever cannot be reached. Returns
    {'sent': n, 'failed': n, 'skipped': {reason: n}}."""
    out = {'sent': 0, 'failed': 0, 'skipped': {}}
    now = now_utc or datetime.utcnow()
    if channel == 'sms':
        closed = quiet_hours(now)
        if closed:
            out['skipped'][closed] = len(leads)
            return out
    # The limit counts sends, not ticks: the people skipped (already reached
    # this week, opted out) do not use it up, so pressing send again with the
    # same leads ticked moves on to whoever is left.
    attempted = 0
    waiting = 0
    for lead in leads:
        block = (email_block if channel == 'email' else sms_block)(lead, now, bulk=len(leads) > 1)
        if not block and channel == 'sms':
            # Fresh, and by number: the rows this send was started with can be
            # stale by the time their turn comes. send_text checks again too.
            import control_plane
            block = control_plane.number_text_block(engine, lead.get('phone'))
        if block:
            out['skipped'][block] = out['skipped'].get(block, 0) + 1
            continue
        if attempted >= MAX_BULK:
            waiting += 1
            continue
        attempted += 1
        if channel == 'email':
            ok, _ = send_email(engine, lead, subject, body_template, sent_by)
        else:
            ok, _ = send_text(engine, lead, body_template, sent_by, now_utc=now)
        out['sent' if ok else 'failed'] += 1
    if waiting:
        out['skipped'][f'over the {MAX_BULK}-per-click limit -- press send again '
                       f'for the rest'] = waiting
    return out
