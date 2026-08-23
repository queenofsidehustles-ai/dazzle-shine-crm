"""Two-way text messaging — a single threaded inbox for talking with cleaners,
applicants and customers. Outbound texts go through the business Twilio number;
replies come back via the /messages/incoming webhook and land in the same
thread. The owner is pinged on her personal cell for every inbound message.

The thread is keyed on the phone number alone, so it has always worked for
anyone. What it lacked was a name for customers and a way in from their pages:
a client's reply arrived looking like a wrong number, and the only route to this
screen was from a cleaner's profile or the inbox list."""
from datetime import datetime
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, Response, jsonify)
from auth import login_required
from extensions import db
from models import (Message, Staff, ContractorApplication, BusinessSetting,
                    MessageTemplate, OutboundLog, Client, Booking)
from notifications import send_sms
from translate import translate
import branding
import integrations

messages_bp = Blueprint('messages', __name__, url_prefix='/messages')

DEFAULT_OWNER_ALERT_PHONE = '9374773090'   # Monica's cell — editable via 'owner_alert_phone' setting


def norm_phone(p):
    """Reduce any phone format to its last 10 digits — the thread key."""
    digits = ''.join(ch for ch in (p or '') if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def pretty_phone(p):
    d = norm_phone(p)
    return f"({d[0:3]}) {d[3:6]}-{d[6:10]}" if len(d) == 10 else (p or '')


@messages_bp.route('/sent')
@login_required
def sent_log():
    """A single 'Sent' history of every outbound text and email the system has
    sent from anywhere in the app (pay updates, work orders, confirmations,
    reminders, payment links, custom customer emails)."""
    import os as _os
    channel = request.args.get('channel', '')
    q = OutboundLog.query
    if channel in ('sms', 'email'):
        q = q.filter(OutboundLog.channel == channel)
    logs = q.order_by(OutboundLog.created_at.desc()).limit(300).all()

    # Whether the services are even connected. Without this the page can't tell
    # you the difference between "nothing to send" and "nothing can be sent".
    sms_missing = integrations.missing_for('texting')
    health = {
        'sms_ready': not sms_missing,
        'sms_missing': sms_missing,
        'email_ready': bool(integrations.resend_api_key()),
        'failed_recently': OutboundLog.query.filter_by(status='failed').count(),
    }
    return render_template('admin/sent_log.html', logs=logs, health=health,
                           pretty_phone=pretty_phone, channel=channel)


def owner_alert_phone():
    return BusinessSetting.get('owner_alert_phone') or DEFAULT_OWNER_ALERT_PHONE


def resolve_contact(phone10):
    """Who a 10-digit phone belongs to. Returns
    dict(name, staff_id, application_id, client_id).

    Customers used to fall through this and show in the inbox as a bare phone
    number, which made a reply from a client indistinguishable from a wrong
    number. They are checked last, after the team and applicants, because a
    cleaner who is also a customer should read as a cleaner here."""
    blank = {'name': None, 'staff_id': None, 'application_id': None, 'client_id': None}

    for s in Staff.query.filter(Staff.phone.isnot(None)).all():
        if norm_phone(s.phone) == phone10:
            return {**blank, 'name': s.name, 'staff_id': s.id}
    for a in ContractorApplication.query.filter(ContractorApplication.phone.isnot(None)).all():
        if norm_phone(a.phone) == phone10:
            return {**blank, 'name': a.name, 'application_id': a.id}
    for c in Client.query.filter(Client.phone.isnot(None)).all():
        if norm_phone(c.phone) == phone10:
            return {**blank, 'name': c.name, 'client_id': c.id}
    # Not a client yet — but a booking carries a phone before one exists.
    b = (Booking.query.filter(Booking.phone.isnot(None))
         .order_by(Booking.created_at.desc()).all())
    for bk in b:
        if norm_phone(bk.phone) == phone10:
            return {**blank, 'name': bk.name}
    return blank


def record_outbound(phone10, body, contact_name=None, twilio_sid=None,
                    staff_id=None, application_id=None, translated=None):
    m = Message(phone=phone10, direction='out', body=body, body_translated=translated,
                contact_name=contact_name, twilio_sid=twilio_sid, staff_id=staff_id,
                application_id=application_id, created_at=datetime.utcnow())
    db.session.add(m)
    db.session.commit()
    return m


def thread_lang(phone10):
    """Language for the conversation. An explicit per-thread override wins;
    otherwise it follows the contact's marked language (Staff/applicant)."""
    override = BusinessSetting.get(f'lang:{phone10}')
    if override:
        return override
    contact = resolve_contact(phone10)
    if contact.get('staff_id'):
        s = Staff.query.get(contact['staff_id'])
        if s and getattr(s, 'language', None):
            return s.language
    if contact.get('application_id'):
        a = ContractorApplication.query.get(contact['application_id'])
        if a and getattr(a, 'language', None):
            return a.language
    return 'en'


def set_thread_lang(phone10, lang):
    BusinessSetting.set(f'lang:{phone10}', lang)
    db.session.commit()


def fill_placeholders(body, phone10, contact):
    """Swap {name}, {owner}, {business}, {myday_link}, {sample_link}, {start_date}
    with real values for this contact."""
    biz = branding.biz_name()
    owner = BusinessSetting.get('owner_name', 'Monica')
    full = contact.get('name') or ''
    first = full.split()[0] if full else 'there'
    sample = f"{branding.crm_base()}/contractors/sample-day"
    myday = sample
    start = 'to be confirmed'
    start_link = ''
    if contact.get('staff_id'):
        s = Staff.query.get(contact['staff_id'])
        if s:
            if not getattr(s, 'agreement_token', None):
                import secrets
                s.agreement_token = secrets.token_urlsafe(32)
                db.session.commit()
            myday = f"{branding.crm_base()}/contractors/my-day/{s.agreement_token}"
            start_link = f"{branding.crm_base()}/contractors/start-date/{s.agreement_token}"
            if getattr(s, 'roster_start_date', None):
                start = s.roster_start_date
    return (body.replace('{name}', first).replace('{owner}', owner)
                .replace('{business}', biz).replace('{myday_link}', myday)
                .replace('{sample_link}', sample).replace('{start_link}', start_link)
                .replace('{start_date}', start))


# ── Insert a template into the reply box (placeholders auto-filled) ─────────
@messages_bp.route('/thread/<phone>/fill')
@login_required
def fill_template(phone):
    phone10 = norm_phone(phone)
    tpl = MessageTemplate.query.get_or_404(request.args.get('id', type=int))
    contact = resolve_contact(phone10)
    return jsonify({'body': fill_placeholders(tpl.body, phone10, contact)})


# ── Manage reusable templates ───────────────────────────────────────────────
@messages_bp.route('/templates', methods=['GET', 'POST'])
@login_required
def templates():
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        body = (request.form.get('body') or '').strip()
        tid = request.form.get('id', type=int)
        if title and body:
            if tid:
                t = MessageTemplate.query.get(tid)
                if t:
                    t.title, t.body = title, body
            else:
                db.session.add(MessageTemplate(title=title, body=body))
            db.session.commit()
            flash('Template saved.', 'success')
        return redirect(url_for('messages.templates'))
    return render_template('admin/messages_templates.html',
                           templates=MessageTemplate.query.order_by(MessageTemplate.id).all())


@messages_bp.route('/templates/<int:tid>/delete', methods=['POST'])
@login_required
def delete_template(tid):
    t = MessageTemplate.query.get(tid)
    if t:
        db.session.delete(t)
        db.session.commit()
        flash('Template deleted.', 'success')
    return redirect(url_for('messages.templates'))


def deliver(phone10, body_en, contact):
    """Send an owner-typed (English) message, auto-translating to the thread's
    language if needed. Records the English + the translation. Returns (ok, detail)."""
    lang = thread_lang(phone10)
    translated = None
    to_send = body_en
    if lang != 'en':
        translated = translate(body_en, target=lang)
        to_send = translated or body_en
    ok, detail = send_sms(phone10, to_send)
    record_outbound(phone10, body_en, contact_name=contact.get('name'),
                    staff_id=contact.get('staff_id'), application_id=contact.get('application_id'),
                    translated=translated)
    return ok, detail


# ── Inbox — every conversation, newest reply on top ─────────────────────────
@messages_bp.route('/')
@login_required
def inbox():
    all_msgs = Message.query.order_by(Message.created_at.desc()).all()
    threads = {}   # phone -> {last, unread, name}
    for m in all_msgs:
        t = threads.get(m.phone)
        if not t:
            threads[m.phone] = t = {'phone': m.phone, 'last': m, 'unread': 0,
                                    'name': m.contact_name}
        if not t['name'] and m.contact_name:
            t['name'] = m.contact_name
        if m.direction == 'in' and not m.read_at:
            t['unread'] += 1
    thread_list = list(threads.values())   # already newest-first (dict insertion order)
    for t in thread_list:
        if not t['name']:
            t['name'] = resolve_contact(t['phone'])['name']
        t['pretty'] = pretty_phone(t['phone'])
    return render_template('admin/messages_inbox.html', threads=thread_list)


# ── One conversation ────────────────────────────────────────────────────────
@messages_bp.route('/thread/<phone>')
@login_required
def thread(phone):
    phone10 = norm_phone(phone)
    msgs = Message.query.filter_by(phone=phone10).order_by(Message.created_at.asc()).all()
    # Mark inbound as read
    now = datetime.utcnow()
    changed = False
    for m in msgs:
        if m.direction == 'in' and not m.read_at:
            m.read_at = now
            changed = True
    if changed:
        db.session.commit()

    contact = resolve_contact(phone10)
    name = contact['name'] or request.args.get('name') or pretty_phone(phone10)
    # An applicant we can nudge for a background-check re-upload?
    app_rec = None
    if contact['application_id']:
        app_rec = ContractorApplication.query.get(contact['application_id'])
    return render_template('admin/messages_thread.html', msgs=msgs, phone=phone10,
                           pretty=pretty_phone(phone10), name=name,
                           contact=contact, app_rec=app_rec, lang=thread_lang(phone10),
                           templates=MessageTemplate.query.order_by(MessageTemplate.id).all())


# ── Toggle a conversation between English and Spanish auto-translation ───────
@messages_bp.route('/thread/<phone>/lang', methods=['POST'])
@login_required
def toggle_lang(phone):
    phone10 = norm_phone(phone)
    new_lang = request.form.get('lang', 'en')
    set_thread_lang(phone10, 'es' if new_lang == 'es' else 'en')
    if new_lang == 'es':
        flash('🌐 Spanish translation ON — you type English, they get Spanish; their replies show in English.', 'success')
    else:
        flash('Translation off — messages send as-is.', 'success')
    return redirect(url_for('messages.thread', phone=phone10))


# ── Send a reply ────────────────────────────────────────────────────────────
@messages_bp.route('/thread/<phone>/send', methods=['POST'])
@login_required
def send(phone):
    phone10 = norm_phone(phone)
    body = (request.form.get('body') or '').strip()
    if not body:
        flash('Type a message first.', 'warning')
        return redirect(url_for('messages.thread', phone=phone10))
    contact = resolve_contact(phone10)
    ok, detail = deliver(phone10, body, contact)
    if not ok:
        flash('Saved, but the text may not have sent: ' + detail, 'warning')
    return redirect(url_for('messages.thread', phone=phone10))


# ── One-tap: ask an applicant to re-upload their background check ────────────
@messages_bp.route('/thread/<phone>/request-bgcheck', methods=['POST'])
@login_required
def request_bgcheck(phone):
    phone10 = norm_phone(phone)
    contact = resolve_contact(phone10)
    app_rec = ContractorApplication.query.get(contact['application_id']) if contact['application_id'] else None
    if not app_rec:
        flash('This number is not linked to an applicant, so I can’t build a re-upload link.', 'warning')
        return redirect(url_for('messages.thread', phone=phone10))
    if not app_rec.bgcheck_upload_token:
        import secrets
        app_rec.bgcheck_upload_token = secrets.token_urlsafe(32)
        db.session.commit()
    link = url_for('interviews.bgcheck_upload_page', token=app_rec.bgcheck_upload_token, _external=True)
    first = (app_rec.name or 'there').split()[0]
    body = (f"Hi {first}, it looks like your background check didn’t come through. "
            f"Could you please re-upload it here? {link} — thank you! – {branding.biz_name()}")
    ok, detail = deliver(phone10, body, contact)
    flash('Re-upload request sent.' if ok else ('Saved, but the text may not have sent: ' + detail),
          'success' if ok else 'warning')
    return redirect(url_for('messages.thread', phone=phone10))


# ── Twilio webhook: an inbound text landed on the business number ───────────
@messages_bp.route('/incoming', methods=['POST'])
def incoming():
    from_num = request.form.get('From', '')
    body = (request.form.get('Body') or '').strip()
    sid = request.form.get('MessageSid')
    phone10 = norm_phone(from_num)

    # Ignore texts from the owner's own cell (e.g. replies to alert texts) and empties.
    if not phone10 or not body or phone10 == norm_phone(owner_alert_phone()):
        return Response('<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
                        mimetype='text/xml')

    contact = resolve_contact(phone10)
    # If this conversation is bilingual, translate their reply to English.
    translated = None
    if thread_lang(phone10) != 'en':
        translated = translate(body, target='en')
    m = Message(phone=phone10, direction='in', body=body, body_translated=translated,
                contact_name=contact['name'], twilio_sid=sid, staff_id=contact['staff_id'],
                application_id=contact['application_id'], created_at=datetime.utcnow())
    db.session.add(m)
    db.session.commit()

    # Ping the owner's cell so she never has to sit in the CRM (in English).
    who = contact['name'] or pretty_phone(phone10)
    alert_body = translated or body
    snippet = alert_body if len(alert_body) <= 90 else alert_body[:90] + '…'
    link = f"{branding.crm_base()}{url_for('messages.thread', phone=phone10)}"
    try:
        send_sms(owner_alert_phone(), f"📩 {who}: {snippet}\nReply: {link}")
    except Exception:
        pass

    return Response('<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
                    mimetype='text/xml')
