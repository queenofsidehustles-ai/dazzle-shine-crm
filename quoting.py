"""Quoting a caller by email, and letting them book at the price they were given.

Someone rings, asks what a clean would cost, and gives an email address. Until
now there was nowhere to put that: the quote email existed but only fired from
the website form, so a phone caller got nothing unless the owner wrote it out by
hand.

The price is the point. A generic booking link drops them on a calculator, and a
calculator can easily produce a different number from the one that was said on
the phone — a custom price, a discount, a judgement call about a big house. So
the quote gets its own link carrying its own price, and booking through it uses
that figure rather than working one out again.
"""
import json
import secrets
from datetime import datetime

import branding
from extensions import db
from models import Lead, Booking, Client, ChecklistTemplate
from pricing import DEPOSIT_AMOUNT


def service_checklist(service_type):
    """The standard list for a service — what the cleaners actually work from.

    Using the same list twice over is the point: the customer is told exactly
    what was going to happen anyway, and there is one place to edit it when the
    service changes."""
    t = (ChecklistTemplate.query.filter_by(service_type=service_type).first()
         if service_type else None)
    return t.get_items() if t else []


def checklist_for(lead_or_service):
    """What this quote actually promised.

    Callers ask for one specialised thing, or say plainly they don't want the
    oven done. So a quote keeps its own list once one has been chosen, and only
    falls back to the service default when nobody has edited it — which is the
    case for every lead that came in through the website."""
    if isinstance(lead_or_service, str) or lead_or_service is None:
        return service_checklist(lead_or_service)
    lead = lead_or_service
    saved = (lead.quote_checklist or '').strip()
    if saved:
        try:
            items = json.loads(saved)
            if isinstance(items, list):
                return [str(i) for i in items if str(i).strip()]
        except ValueError:
            pass          # corrupt somehow — better the standard list than none
    return service_checklist(lead.service_type)


def set_checklist(lead, items):
    """Store the chosen lines. An empty choice clears back to the service list
    rather than promising nothing at all — a quote with no description of the
    work is worse than a generic one."""
    cleaned = [str(i).strip() for i in (items or []) if str(i).strip()]
    lead.quote_checklist = json.dumps(cleaned) if cleaned else None


def quote_url(lead):
    """Their personal link. Absolute, because it goes in an email."""
    if not lead.quote_token:
        return branding.booking_link()
    return f"{branding.crm_base().rstrip('/')}/quote/{lead.quote_token}"


def quote_lead(name, email, phone, service_type, bedrooms=None, bathrooms=None,
               extras='', frequency='one_time', price=None, notes='',
               address='', city='', zip_code=''):
    """Create (or refresh) the Lead behind a quote. Returns the Lead.

    Matched on email so quoting the same person twice updates their quote rather
    than leaving two of them in the list with different prices — and whichever
    one they happened to open would then be binding."""
    email = (email or '').strip().lower()
    lead = Lead.query.filter_by(email=email).first() if email else None
    if lead is None:
        lead = Lead(email=email, drip_step=1, status='new', source='phone')
        db.session.add(lead)

    lead.name = (name or '').strip() or lead.name
    lead.phone = (phone or '').strip() or lead.phone
    lead.service_type = service_type or lead.service_type
    lead.bedrooms = bedrooms if bedrooms not in (None, '') else lead.bedrooms
    lead.bathrooms = bathrooms if bathrooms not in (None, '') else lead.bathrooms
    lead.extras = extras or lead.extras
    lead.frequency = frequency or lead.frequency
    lead.notes = notes or lead.notes
    lead.address = address or lead.address
    lead.city = city or lead.city
    lead.zip_code = zip_code or lead.zip_code
    if price is not None:
        lead.quoted_price = round(float(price), 2)
    if not lead.quote_token:
        lead.quote_token = secrets.token_urlsafe(32)
    # Re-quoting restarts the follow-up clock. The old drip was chasing a price
    # that no longer applies.
    lead.drip_step = 1
    lead.last_drip_at = datetime.utcnow()
    db.session.commit()
    return lead


def form_context(existing=None):
    """Everything the quote form needs to render, for either way in.

    The ticked/unticked state comes from the quote itself where there is one, so
    reopening a quote shows what was actually promised rather than resetting to
    the standard list and quietly re-adding what she took off."""
    from pricing import SERVICES, EXTRAS, DEPOSIT_AMOUNT
    service = (existing.service_type if existing else '') or next(iter(SERVICES))
    standard = service_checklist(service)
    chosen = checklist_for(existing) if existing else standard
    return {
        'services': SERVICES, 'extras': EXTRAS, 'deposit': DEPOSIT_AMOUNT,
        'checklist': standard,
        'chosen': chosen,
        # Lines she added by hand last time — anything promised that isn't on
        # the standard list for the service.
        'custom_lines': [i for i in chosen if i not in standard],
    }


def handle_quote_form(form, lsa_lead=None):
    """Turn a submitted quote form into a Lead with a quote on it.

    Shared by the two ways in — off a Google Ads caller, or from scratch for
    someone who rang a number that never went through Google — so the two can't
    drift into quoting people differently.

    Returns (lead, error). One of them is always None."""
    from pricing import calculate_price

    email = (form.get('email') or '').strip()
    if not email:
        return None, 'An email address is needed to send a quote.'

    service_type = form.get('service_type', '')
    beds, baths = form.get('bedrooms', ''), form.get('bathrooms', '')
    extras = ','.join(form.getlist('extras'))
    phone = (form.get('phone') or '').strip() or (lsa_lead.phone if lsa_lead else '')

    # A typed price wins over the calculated one. She was on the call, and the
    # figure she actually said is the one that has to go out — the calculator is
    # a starting point, not a second opinion.
    typed = (form.get('price') or '').strip()
    try:
        price = float(typed) if typed else calculate_price(
            service_type=service_type, bedrooms=beds or 1, bathrooms=baths or 1,
            extras=extras, frequency=form.get('frequency', 'one_time'))
    except ValueError:
        return None, "That price doesn't look like a number."

    lead = quote_lead(
        name=form.get('name', ''), email=email, phone=phone,
        service_type=service_type, bedrooms=beds, bathrooms=baths, extras=extras,
        frequency=form.get('frequency', 'one_time'), price=price,
        notes=form.get('notes', ''), address=form.get('address', ''),
        city=form.get('city', ''), zip_code=form.get('zip_code', ''))

    # What she ticked, plus anything she typed in that they asked for on the
    # phone. Both are optional; leaving it all alone means the standard list.
    chosen = list(form.getlist('checklist'))
    for line in (form.get('checklist_custom') or '').splitlines():
        if line.strip():
            chosen.append(line.strip())
    set_checklist(lead, chosen)
    db.session.commit()
    return lead, None


def link_lsa_caller(lead, lsa_lead=None):
    """Tie a quote back to the Google Ads caller it came from, matching on phone
    when it wasn't quoted from that screen. Keeps one caller's story together,
    and takes them out of a text sequence written for people we never reached."""
    import lsa as lsa_mod
    from models import LsaLead
    rows = [lsa_lead] if lsa_lead else []
    if not rows and lead.phone:
        rows = LsaLead.query.filter_by(phone=lsa_mod.phone10(lead.phone)).all()
    for r in rows:
        r.crm_lead_id = lead.id
        r.track = lsa_mod.QUOTED
        if r.in_sequence:
            r.seq_stopped = 'quoted'
    if rows:
        db.session.commit()
    return len(rows)


def send_quote(lead):
    """Email the quote. Returns (ok, detail).

    Goes through the editable lead_quote template so the wording stays hers.
    The checklist is appended rather than required to be in the template: the
    template already exists on every running instance, and a variable added to
    the default today would never appear in a copy she had already edited."""
    from notifications import send_triggered_email
    if not lead.email:
        return False, 'No email address on this lead.'

    items = checklist_for(lead)
    checklist = ''
    if items:
        lines = '\n'.join(f'  •  {i}' for i in items)
        checklist = f"What's included in your {lead.service_label.lower()}:\n\n{lines}"

    ok = send_triggered_email(
        trigger='lead_quote',
        to_email=lead.email,
        to_name=lead.name,
        variables={
            'service_type': lead.service_label,
            'beds': lead.bedrooms or '—',
            'baths': lead.bathrooms or '—',
            'quote_amount': f'{(lead.quoted_price or 0):.2f}',
            'deposit': f'{DEPOSIT_AMOUNT:.2f}',
            'balance': f'{max(0.0, (lead.quoted_price or 0) - DEPOSIT_AMOUNT):.2f}',
            'booking_link': quote_url(lead),
            'checklist': checklist,
        },
        append_text=checklist,
        append_unless='{{checklist}}',
    )
    if not ok:
        return False, ('The "Instant Quote Email" template is missing or switched '
                       'off — check Settings → Email templates.')
    lead.quote_sent_at = datetime.utcnow()
    db.session.commit()
    return True, ''


def text_quote(lead):
    """Text the quote as well as emailing it. Returns (ok, detail).

    Email is the right place for a price and a list of what's included, but it
    is also the thing that quietly lands in spam — and the customer has no idea
    anything was sent. A text is short, arrives, and carries the same link, so
    the email being filtered stops meaning the quote never happened.

    Goes through send_marketing_sms so anyone who has texted STOP is left
    alone, even though they asked for this quote themselves."""
    from notifications import send_marketing_sms
    if not lead.phone:
        return False, 'No phone number on this lead.'
    biz = branding.biz_name()
    body = (f"Hi {(lead.name or 'there').split()[0]}, it's {biz} — here's the "
            f"quote you asked for: ${(lead.quoted_price or 0):.2f} for a "
            f"{lead.service_label.lower()}. Everything included and booking "
            f"here: {quote_url(lead)} Reply STOP to opt out.")
    return send_marketing_sms(lead.phone, body)


def deliver_quote(lead, also_text=False):
    """Send the quote by whichever channels were asked for. Returns a list of
    (message, level) for the screen to show.

    Each channel reports separately and a failure keeps its reason. One vague
    warning covering both would hide the case that actually matters — the email
    silently not going while the text did, which looks like success from the
    customer's end and like nothing from hers."""
    out = []
    ok, detail = send_quote(lead)
    if ok:
        out.append((f'Quote for ${(lead.quoted_price or 0):.2f} emailed to '
                    f'{lead.email} 📩 Check the Sent Log if they say it never '
                    f'arrived — it now records the provider\'s message id.',
                    'success'))
    else:
        out.append((f'⚠️ The email did not send: {detail}', 'warning'))

    if also_text:
        t_ok, t_detail = text_quote(lead)
        if t_ok:
            out.append((f'Also texted to {lead.phone} 📱', 'success'))
        else:
            out.append((f'⚠️ The text did not send: {t_detail}', 'warning'))
    return out


def was_delivered(lead):
    """Did the quote reach them by any channel? Decides whether she is sent back
    to the list or kept on the form to try again."""
    return bool(lead.quote_sent_at)


def accept_quote(lead, preferred_date, preferred_time='', address='', city='',
                 zip_code='', notes=''):
    """Turn an accepted quote into a booking at the quoted price.

    The price is copied from the lead, not recalculated. That is the whole
    reason this route exists rather than sending them to the public calculator:
    what they were told is what they pay."""
    price = round(float(lead.quoted_price or 0), 2)
    email = (lead.email or '').strip().lower()

    client = Client.query.filter_by(email=email).first() if email else None
    if not client:
        client = Client(name=lead.name, email=email, phone=lead.phone or '',
                        address=address or lead.address or '',
                        city=city or lead.city or '',
                        zip_code=zip_code or lead.zip_code or '')
        db.session.add(client)
        db.session.flush()

    booking = Booking(
        client_id=client.id,
        service_type=lead.service_type,
        bedrooms=lead.bedrooms, bathrooms=lead.bathrooms,
        extras=lead.extras or '', frequency=lead.frequency or 'one_time',
        preferred_date=preferred_date or '', preferred_time=preferred_time or '',
        name=lead.name, email=email, phone=lead.phone or '',
        address=address or lead.address or '',
        city=city or lead.city or '',
        zip_code=zip_code or lead.zip_code or '',
        notes=notes or lead.notes or '',
        price=price,
        balance_due=round(max(0.0, price - DEPOSIT_AMOUNT), 2),
        deposit_token=secrets.token_urlsafe(32),
        status='pending',
        source='quote',
    )
    db.session.add(booking)

    # They have booked, so stop chasing them — by email here, and by text
    # through the Google Ads lead they may have come in on.
    lead.status = 'converted'
    lead.drip_step = 9
    db.session.commit()
    _stop_lsa_followup(lead)
    return booking


def _stop_lsa_followup(lead):
    """A caller who books should not still be getting "you never booked" texts.

    The nightly match would catch this anyway once the booking exists, but that
    can be up to a day later — long enough for the next message to go out."""
    try:
        from models import LsaLead
        import lsa
        rows = LsaLead.query.filter_by(crm_lead_id=lead.id).all()
        if not rows and lead.phone:
            rows = LsaLead.query.filter_by(phone=lsa.phone10(lead.phone)).all()
        for r in rows:
            r.booked = True
            if r.in_sequence:
                r.seq_stopped = 'booked'
        if rows:
            db.session.commit()
    except Exception:
        db.session.rollback()
