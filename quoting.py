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
from pricing import DEPOSIT_AMOUNT, get_deposit


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
               address='', city='', zip_code='', sqft=None):
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
    if sqft not in (None, ''):
        try:
            lead.sqft = int(sqft)
        except (TypeError, ValueError):
            pass       # a typo in an optional box shouldn't lose the whole quote
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


def resolve_discount(form, full_price):
    """Work out the discount on a quote. Returns (amount_off, code, label, error).

    Two ways to give one, because she gives them both ways. A saved code from
    the Discounts page carries its own rules — percent or fixed, expiry, a usage
    limit — and those are checked here rather than trusted, so an expired code
    cannot quietly come off a price. Or she types an amount and what to call it,
    for the ones that were never going to be a code: a neighbour, an apology, a
    big job she wants.

    The discount is capped at the price. A quote that owes the customer money is
    a typo every time, and a negative price would be carried into the booking,
    the deposit and the balance before anybody noticed.
    """
    from models import DiscountCode
    code = (form.get('discount_code') or '').strip()
    label = (form.get('discount_label') or '').strip()

    if code:
        dc = DiscountCode.query.filter(db.func.upper(DiscountCode.code) == code.upper()).first()
        if not dc:
            return 0.0, '', '', f'No discount code called “{code}”.'
        ok, why = dc.check_valid()
        if not ok:
            return 0.0, '', '', f'{code}: {why}'
        off = round(full_price - dc.apply(full_price), 2)
        return (min(off, full_price), dc.code, label or dc.code, None)

    raw = (form.get('discount_amount') or '').strip().replace('$', '').replace(',', '')
    if not raw:
        return 0.0, '', '', None
    try:
        off = round(float(raw), 2)
    except ValueError:
        return 0.0, '', '', "That discount doesn't look like a number."
    if off <= 0:
        return 0.0, '', '', None
    # A discount with no name reads as an unexplained deduction, which is worth
    # less than no discount at all — the whole point is that they can see it.
    return min(off, full_price), '', label or 'Discount', None


def form_context(existing=None):
    """Everything the quote form needs to render, for either way in.

    The ticked/unticked state comes from the quote itself where there is one, so
    reopening a quote shows what was actually promised rather than resetting to
    the standard list and quietly re-adding what she took off."""
    from pricing import SERVICES, EXTRAS, POSTCON_TYPES, POSTCON_WITH_DEBRIS, get_deposit
    from models import DiscountCode
    service = (existing.service_type if existing else '') or next(iter(SERVICES))
    standard = service_checklist(service)
    chosen = checklist_for(existing) if existing else standard
    return {
        'services': SERVICES, 'extras': EXTRAS, 'deposit': get_deposit(),
        # So the form can put the haul-off box in front of her on the services
        # that involve one, and keep it out of the way on the ones that don't.
        'postcon_types': list(POSTCON_TYPES),
        'debris_types': list(POSTCON_WITH_DEBRIS),
        # Only codes that could actually be honoured today. Offering an expired
        # one on the form and refusing it on submit wastes a call she is on.
        'discount_codes': [d for d in DiscountCode.query
                           .filter_by(is_active=True)
                           .order_by(DiscountCode.code).all()
                           if d.check_valid()[0]],
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
    sqft = (form.get('sqft') or '').strip()
    extras = ','.join(form.getlist('extras'))
    phone = (form.get('phone') or '').strip() or (lsa_lead.phone if lsa_lead else '')

    # A typed price wins over the calculated one. She was on the call, and the
    # figure she actually said is the one that has to go out — the calculator is
    # a starting point, not a second opinion. On post-construction it is barely
    # even a starting point: those get walked before they get priced, and the
    # matrix number is there to stop her quoting from a blank page.
    typed = (form.get('price') or '').strip()
    try:
        price = float(typed) if typed else calculate_price(
            service_type=service_type, bedrooms=beds or 1, bathrooms=baths or 1,
            extras=extras, frequency=form.get('frequency', 'one_time'), sqft=sqft)
    except ValueError:
        return None, "That price doesn't look like a number."

    # Hauling the builder's debris away, quoted separately from cleaning it.
    # Dump fees and load count are what this costs and neither follows from
    # bedroom count, so it is a figure she sets per job after seeing the site.
    debris_raw = (form.get('debris_fee') or '').strip()
    try:
        debris = round(float(debris_raw), 2) if debris_raw else 0.0
    except ValueError:
        return None, "That debris removal amount doesn't look like a number."
    if debris < 0:
        return None, 'A debris removal charge cannot be negative.'

    # The price she typed is the FULL price when a discount is being given —
    # she says "it's $290, but I'll do $250 for you", so she types 290 and the
    # discount, not 250. Quoting the discounted figure with nothing to show for
    # it is what this replaces: the customer could not see they had been given
    # anything, and nothing recorded that anything had been.
    #
    # The discount is worked out against the cleaning alone. Disposal is money
    # she pays a landfill, not margin she can decide to give away — taking a
    # friends-and-family discount out of a dump fee is taking it out of pocket.
    off, code, label, derr = resolve_discount(form, price)
    if derr:
        return None, derr
    final = round(max(0.0, price - off) + debris, 2)

    lead = quote_lead(
        name=form.get('name', ''), email=email, phone=phone,
        service_type=service_type, bedrooms=beds, bathrooms=baths, extras=extras,
        frequency=form.get('frequency', 'one_time'), price=final,
        notes=form.get('notes', ''), address=form.get('address', ''),
        city=form.get('city', ''), zip_code=form.get('zip_code', ''), sqft=sqft)

    # Written after quote_lead so re-quoting the same person replaces the old
    # discount rather than leaving last week's reason on this week's price.
    # Full price carries the haul-off too, so the struck-through figure and what
    # they pay differ by the discount and nothing else.
    lead.quote_full_price = round(price + debris, 2) if off > 0 else None
    lead.discount_amount = off
    lead.discount_code = code or None
    lead.discount_label = label or None
    lead.debris_fee = debris if debris > 0 else None
    lead.debris_note = (form.get('debris_note') or '').strip()[:120] or None

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


def price_breakdown(lead):
    """The money on a quote written out line by line, or '' if it is one number.

    A single figure is fine when it really is a single figure. Once a haul-off or
    a discount is inside it, a customer holding three quotes cannot see what they
    are comparing — and neither can she, a month later, when they ring up asking
    why this one was dearer. So anything that moved the price says so by name,
    and the lines add up to what they actually pay."""
    total = float(lead.quoted_price or 0)
    fee = float(lead.debris_fee or 0) if lead.has_debris_fee else 0.0
    off = float(lead.discount_amount or 0) if lead.has_discount else 0.0
    if not fee and not off:
        return ''
    # What the cleaning came to before anything was taken off it. The discount
    # only ever applied to the cleaning, so adding it back gives that figure.
    cleaning = total - fee + off
    lines = []
    if fee:
        lines.append(f'Cleaning:  ${cleaning:.2f}')
        lines.append(f'{lead.debris_display}:  ${fee:.2f}')
    if off:
        lines.append(f'{"Subtotal" if fee else "Your price"}:  ${cleaning + fee:.2f}')
        lines.append(f'{lead.discount_display}:  −${off:.2f}')
    lines.append(f'{"You pay" if off else "Total"}:  ${total:.2f}')
    return '\n'.join(lines)


def scope_note(lead):
    """What a post-construction quote has to say in writing, or ''.

    Two things sink these jobs when they are left to be understood rather than
    written down. The final phase is a second visit on a second day, and a
    builder's handover date slips as a matter of routine — uncapped, "we'll come
    back after the dust settles" is an unpaid third and fourth trip. And on the
    rungs that do not include the haul-off, the debris being someone else's job
    is the whole reason the price is lower; a customer who never read that
    expects a cleared site and is disappointed by a quote they were given
    correctly."""
    from pricing import (POSTCON_TYPES, POSTCON_WITH_FINAL, POSTCON_WITH_DEBRIS,
                         TOUCHUP_WINDOW_DAYS)
    service = lead.service_type or ''
    if service not in POSTCON_TYPES:
        return ''
    bits = []
    if service in POSTCON_WITH_FINAL:
        bits.append(f'Final phase included: one touch-up visit within '
                    f'{TOUCHUP_WINDOW_DAYS} days of the detail clean, once the '
                    f'dust has settled. Dust keeps falling after a build and one '
                    f'pass cannot catch it all. Any visit after that is quoted '
                    f'separately.')
    else:
        bits.append('This is the detail clean only — no return visit. A '
                    'final-phase touch-up after the dust settles can be added at '
                    'any time.')
    if service not in POSTCON_WITH_DEBRIS and not lead.has_debris_fee:
        bits.append('Removing construction debris, packaging and jobsite trash '
                    'is not included — the site should be cleared before we '
                    'arrive. We can quote the haul-off if you would like it added.')
    bits.append('Price assumes the build is finished and all trades are off '
                'site. Active work areas are excluded.')
    return '\n\n'.join(bits)


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

    # A discount nobody can see is money given away for nothing, and a haul-off
    # folded into one number is a quote that looks expensive next to one that
    # excluded it. Both go in the same breakdown. The template is hers to edit
    # and most copies predate this, so the working is appended as well as offered
    # as {discount_line} — same reasoning as the checklist.
    discount_line = price_breakdown(lead)
    terms = scope_note(lead)

    appended = '\n\n'.join(p for p in (discount_line, checklist, terms) if p)

    ok = send_triggered_email(
        trigger='lead_quote',
        to_email=lead.email,
        to_name=lead.name,
        variables={
            'service_type': lead.service_label,
            'beds': lead.bedrooms or '—',
            'baths': lead.bathrooms or '—',
            'quote_amount': f'{(lead.quoted_price or 0):.2f}',
            'full_price': f'{float(lead.quote_full_price or lead.quoted_price or 0):.2f}',
            'discount_amount': f'{float(lead.discount_amount or 0):.2f}',
            'discount_label': lead.discount_display if lead.has_discount else '',
            'discount_line': discount_line,
            'debris_amount': f'{float(lead.debris_fee or 0):.2f}',
            'debris_label': lead.debris_display if lead.has_debris_fee else '',
            'scope_note': terms,
            'deposit': f'{get_deposit():.2f}',
            'balance': f'{max(0.0, (lead.quoted_price or 0) - get_deposit()):.2f}',
            'booking_link': quote_url(lead),
            'checklist': checklist,
        },
        append_text=appended,
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
        # Carried over so the crew sees the size they were priced against — the
        # job is scheduled off the hours in it, and on a build those hours came
        # from the floor area rather than the bedroom count.
        sqft=lead.sqft,
        extras=lead.extras or '', frequency=lead.frequency or 'one_time',
        preferred_date=preferred_date or '', preferred_time=preferred_time or '',
        name=lead.name, email=email, phone=lead.phone or '',
        address=address or lead.address or '',
        city=city or lead.city or '',
        zip_code=zip_code or lead.zip_code or '',
        notes=notes or lead.notes or '',
        price=price,
        balance_due=round(max(0.0, price - get_deposit()), 2),
        deposit_token=secrets.token_urlsafe(32),
        status='pending',
        source='quote',
        # Carry the discount onto the job. Booking has had these columns all
        # along and the quote route never filled them, so Job Economics reported
        # no discounting on jobs that had plainly been discounted — the money
        # given away simply vanished from the books.
        discount_code=lead.discount_code or '',
        discount_amount=round(float(lead.discount_amount or 0), 2),
    )
    db.session.add(booking)

    # A saved code counts as used when it turns into a job, not when it is
    # quoted. Counting at quote time would let a limited code be exhausted by
    # people who were told a price and never booked.
    if lead.discount_code:
        from models import DiscountCode
        dc = DiscountCode.query.filter(
            db.func.upper(DiscountCode.code) == lead.discount_code.upper()).first()
        if dc:
            dc.times_used = (dc.times_used or 0) + 1

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
