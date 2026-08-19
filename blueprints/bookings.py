import calendar as cal_module
from datetime import date, timedelta, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from auth import login_required
from models import Booking, BookingCrew, Client, Staff
from extensions import db
from pricing import FREQUENCY_LABELS
import recurring
import branding

bookings_bp = Blueprint('bookings', __name__, url_prefix='/bookings')


@bookings_bp.route('/')
@login_required
def index():
    status_filter = request.args.get('status', '')
    group = (request.args.get('series') or '').strip()
    show_every_visit = group == 'all'

    query = Booking.query.order_by(Booking.created_at.desc())
    if status_filter:
        query = query.filter_by(status=status_filter)
    if group and not show_every_visit:
        query = query.filter_by(recurring_group=group)
    bookings = query.all()

    # A recurring plan is one row unless asked otherwise. Twelve months of the
    # same client, all created in the same second, otherwise sit on top of
    # everything that actually happened this week.
    if not group:
        bookings = recurring.collapse(bookings)
    if group and not show_every_visit:
        bookings = sorted(bookings, key=lambda b: b.preferred_date or '')
    counts = {
        'all': Booking.query.count(),
        'pending': Booking.query.filter_by(status='pending').count(),
        'confirmed': Booking.query.filter_by(status='confirmed').count(),
        'completed': Booking.query.filter_by(status='completed').count(),
        'cancelled': Booking.query.filter_by(status='cancelled').count(),
    }
    return render_template('admin/bookings.html', bookings=bookings, counts=counts,
                           status_filter=status_filter, series=group,
                           show_every_visit=show_every_visit)


@bookings_bp.route('/price-preview')
@login_required
def price_preview():
    """Live running total for the New Booking form — mirrors new()'s save math exactly."""
    from pricing import calculate_price, get_lead_fee
    service = request.args.get('service_type', 'standard')
    beds = request.args.get('bedrooms', '1')
    baths = request.args.get('bathrooms', '1')
    extras = request.args.get('extras', '')
    freq = request.args.get('frequency', 'one_time')

    sqft = request.args.get('sqft', '').strip()
    manual = request.args.get('cleaning_price', '').strip().replace('$', '')
    cleaning = None
    if manual:
        try:
            cleaning = float(manual)
        except ValueError:
            cleaning = None
    if cleaning is None:
        try:
            cleaning = calculate_price(service_type=service, bedrooms=beds,
                                       bathrooms=baths, extras=extras, frequency=freq, sqft=sqft)
        except Exception:
            cleaning = 0.0

    fee_raw = request.args.get('lead_fee', '').strip().replace('$', '')
    try:
        fee = float(fee_raw) if fee_raw != '' else 0.0   # blank = no lead fee (optional)
    except ValueError:
        fee = 0.0

    return jsonify({'cleaning': round(cleaning or 0, 2), 'lead_fee': round(fee, 2),
                    'total': round((cleaning or 0) + fee, 2)})


@bookings_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    """Create a booking by hand — for customers who book by phone/text/in person."""
    from pricing import calculate_price, calculate_job, SERVICE_LABELS, EXTRAS, get_lead_fee
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Customer name is required.', 'error')
            return redirect(url_for('bookings.new'))
        service_type = request.form.get('service_type', 'standard')
        bedrooms = request.form.get('bedrooms', '1')
        bathrooms = request.form.get('bathrooms', '1')
        extras = ','.join(request.form.getlist('extras'))
        frequency = request.form.get('frequency', 'one_time')
        sqft_raw = request.form.get('sqft', '').strip()
        try:
            sqft = int(sqft_raw) if sqft_raw else None
        except ValueError:
            sqft = None

        # Cleaning price: use the number she typed, else auto-calc from the matrix.
        cleaning_raw = request.form.get('cleaning_price', '').strip().replace('$', '')
        cleaning = None
        if cleaning_raw:
            try:
                cleaning = float(cleaning_raw)
            except ValueError:
                cleaning = None
        if cleaning is None:
            try:
                cleaning = calculate_price(service_type=service_type, bedrooms=bedrooms,
                                           bathrooms=bathrooms, extras=extras, frequency=frequency, sqft=sqft)
            except Exception:
                cleaning = 0.0

        # Lead fee — optional ad cost. Blank means none (added to the customer
        # total when present, always excluded from contractor pay).
        fee_raw = request.form.get('lead_fee', '').strip().replace('$', '')
        try:
            lead_fee = float(fee_raw) if fee_raw != '' else 0.0
        except ValueError:
            lead_fee = 0.0
        price = round((cleaning or 0) + lead_fee, 2)   # what the customer pays

        # Person-hours of work in this job — what the cleaner's pay is built
        # from. Taken from the bed/bath estimate unless she overrides it.
        hours_raw = request.form.get('estimated_hours', '').strip()
        est_hours = None
        if hours_raw:
            try:
                est_hours = float(hours_raw)
            except ValueError:
                est_hours = None
        if est_hours is None:
            try:
                # Pass the add-ons — each one carries its own time, and leaving
                # them out would pay the cleaner nothing for that extra work.
                est_hours = calculate_job(service_type, bedrooms, bathrooms,
                                          sqft=sqft, extras=extras).get('hours')
            except Exception:
                est_hours = None

        # Lock the rate this job was quoted at. Raising the company rate later
        # must never change what an old job was worth.
        from pricing import get_labor_rate as _rate
        b = Booking(
            estimated_hours=est_hours,
            labor_rate_applied=_rate() if est_hours else None,
            name=name,
            email=(request.form.get('email', '').strip().lower() or None),
            phone=request.form.get('phone', '').strip(),
            service_type=service_type,
            bedrooms=bedrooms, bathrooms=bathrooms, sqft=sqft, extras=extras,
            frequency=frequency,
            preferred_date=request.form.get('preferred_date', '').strip(),
            preferred_time=request.form.get('preferred_time', '').strip(),
            address=request.form.get('address', '').strip(),
            city=request.form.get('city', '').strip(),
            zip_code=request.form.get('zip_code', '').strip(),
            notes=(request.form.get('notes', '').strip() or None),
            access_notes=(request.form.get('access_notes', '').strip() or None),
            status=request.form.get('status', 'confirmed'),
            price=price,
            lead_fee=lead_fee,
        )
        db.session.add(b)
        db.session.commit()

        # Bookings made by hand never created a customer record — only ones
        # coming through the website did — so the Clients page stayed empty no
        # matter how much work went through the CRM.
        _link_client(b)

        extra = _notify_customer(
            b,
            confirmation=bool(request.form.get('notify_customer')),
            pay_kind=request.form.get('payment_option', 'none'),
        )
        flash(f'Booking created ✅ — now assign a cleaner below to text + email them the job.{extra}', 'success')
        return redirect(url_for('bookings.detail', booking_id=b.id))

    from pricing import FREQUENCY_LABELS as _FREQ
    # Booking for someone already known: bring their details with them. Looking a
    # customer up and retyping their address is how a booking ends up at the
    # wrong house.
    client = None
    last = None
    client_id = request.args.get('client', type=int)
    if client_id:
        client = Client.query.get(client_id)
        if client and client.bookings:
            # Their most recent job — same house, so the size is almost certainly
            # the same, and the service usually is too.
            last = max(client.bookings, key=lambda b: b.created_at or datetime.min)
    return render_template('admin/booking_new.html',
                           service_labels=SERVICE_LABELS, extras=EXTRAS, frequency_labels=_FREQ,
                           default_lead_fee=get_lead_fee(), client=client, last=last)


@bookings_bp.route('/calendar')
@login_required
def calendar():
    today = date.today()
    year = int(request.args.get('year', today.year))
    month = int(request.args.get('month', today.month))

    month_str = f"{year}-{month:02d}"
    bookings = Booking.query.filter(
        Booking.preferred_date.like(f"{month_str}%"),
        Booking.status != 'cancelled',
    ).all()

    # Group bookings by day number
    bookings_by_day = {}
    for b in bookings:
        if b.preferred_date:
            try:
                d = int(b.preferred_date.split('-')[2])
                bookings_by_day.setdefault(d, []).append(b)
            except (IndexError, ValueError):
                pass

    # Sort each day's bookings by time
    for d in bookings_by_day:
        bookings_by_day[d].sort(key=lambda b: b.preferred_time or '')

    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    return render_template('admin/calendar.html',
        cal=cal_module.monthcalendar(year, month),
        year=year, month=month,
        month_name=cal_module.month_name[month],
        bookings_by_day=bookings_by_day,
        today=today,
        prev_year=prev_year, prev_month=prev_month,
        next_year=next_year, next_month=next_month,
    )


@bookings_bp.route('/<int:booking_id>', methods=['GET', 'POST'])
@login_required
def detail(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if request.method == 'POST':
        old_status = booking.status
        old_cleaner = booking.assigned_cleaner or ''
        booking.status = request.form.get('status', booking.status)
        # Parse it. This used to assign the raw form string straight onto a Float
        # column — SQLAlchemy coerced it on write, but anything doing arithmetic
        # with booking.price in the same request hit 'str' - 'int' and blew up.
        price_raw = (request.form.get('price') or '').strip().replace('$', '').replace(',', '')
        if price_raw:
            try:
                booking.price = round(float(price_raw), 2)
            except ValueError:
                flash('That price is not a number — leaving it as it was.', 'warning')
        else:
            booking.price = None
        _fee = request.form.get('lead_fee', '').strip()
        if _fee != '':
            try:
                booking.lead_fee = float(_fee)
            except ValueError:
                pass
        booking.preferred_date = request.form.get('preferred_date', booking.preferred_date)
        booking.preferred_time = request.form.get('preferred_time', booking.preferred_time)
        booking.internal_notes = request.form.get('internal_notes', booking.internal_notes)
        booking.access_notes = request.form.get('access_notes', booking.access_notes)
        booking.skip_review = 'skip_review' in request.form
        booking.assigned_cleaner = request.form.get('assigned_cleaner', booking.assigned_cleaner)
        hours_raw = request.form.get('hours_worked', '').strip()
        booking.hours_worked = float(hours_raw) if hours_raw else booking.hours_worked
        # Person-hours of work — the basis for cleaner pay on this job.
        _apply_hours(booking, request.form)
        booking.below_floor_reason = (request.form.get('below_floor_reason') or '').strip() or None
        # Keep the balance in step with the price. It used to be written only by
        # the price-correction route, so editing the price here left the
        # Balance Collection card — and its charge button — showing a stale $0.
        from blueprints.payments import amount_due as _due
        booking.balance_due = _due(booking)
        newly_completed = (booking.status == 'completed' and old_status != 'completed')
        if newly_completed:
            from datetime import datetime as _dt
            booking.completed_at = _dt.utcnow()

        # 1) Save the booking FIRST so the edit always sticks, even if a
        #    notification step later errors. The save itself must never 500.
        db.session.commit()

        # 2) Notifications are best-effort. Any failure is captured and shown
        #    as a message instead of crashing the whole save.
        new_cleaner = request.form.get('assigned_cleaner', '').strip()
        newly_assigned = bool(new_cleaner) and new_cleaner != old_cleaner
        notify_err = None
        notified = False
        try:
            if newly_completed:
                _send_followup_email(booking)
                if not booking.skip_review:
                    _send_rating_request(booking)
                _create_next_recurring(booking)
            if newly_assigned:
                notified = _notify_cleaner(booking)
                from blueprints.workorders import create_and_send_workorder
                create_and_send_workorder(booking)
            db.session.commit()
        except Exception:
            import traceback
            db.session.rollback()
            notify_err = traceback.format_exc()

        if notify_err:
            flash('Booking saved ✅ — but a notification step errored: '
                  + notify_err.strip().splitlines()[-1], 'warning')
        elif newly_assigned and notified:
            flash(f'Booking updated — notification + checklist sent to {new_cleaner}.', 'success')
        elif newly_assigned:
            flash(f'Booking updated — ⚠️ no email on file for {new_cleaner}, notify them manually.', 'warning')
        else:
            flash('Booking updated.', 'success')

        return redirect(url_for('bookings.detail', booking_id=booking_id))

    active_staff = Staff.query.filter_by(is_active=True).order_by(Staff.name).all()
    from blueprints.payments import payment_link_url, amount_due
    from pricing import get_labor_rate, get_max_labor_percent
    from models import Expense, EXPENSE_CATEGORIES
    pay_url = payment_link_url(booking, 'full')          # ensures pay_token exists
    recurring_upcoming = recurring.upcoming_count(booking.recurring_group) if booking.recurring_group else 0
    # Spell out what each monthly pattern would mean for THIS booking's date,
    # so the choice reads as "the 9th" or "2nd Wednesday" rather than jargon.
    # For a one-off job, work out what an ongoing plan after it would look like,
    # so the form opens with real numbers rather than empty boxes.
    plan_suggestion = None
    if booking.frequency in ('one_time', None):
        from pricing import calculate_price, SERVICE_LABELS
        try:
            suggested = calculate_price('standard', booking.bedrooms, booking.bathrooms,
                                        extras='', frequency='biweekly', sqft=booking.sqft)
        except Exception:
            suggested = None
        try:
            first_day = date.fromisoformat(booking.preferred_date) + timedelta(days=14)
        except (ValueError, TypeError):
            first_day = date.today() + timedelta(days=14)
        plan_suggestion = {'price': suggested, 'start': first_day.isoformat(),
                           'services': SERVICE_LABELS}

    monthly_choices = None
    if booking.frequency == 'monthly' and booking.preferred_date:
        try:
            _d = date.fromisoformat(booking.preferred_date)
            monthly_choices = {'date': _d.strftime('the %-d'),
                               'weekday': recurring.describe_weekday(_d),
                               'current': booking.monthly_mode or recurring.BY_DATE}
        except ValueError:
            monthly_choices = None
    # How many visits would follow this one to a new address — shown on the
    # move form so she can see what she is about to change.
    future_visits = 0
    if booking.recurring_group:
        _today = date.today().isoformat()
        future_visits = Booking.query.filter(
            Booking.recurring_group == booking.recurring_group,
            Booking.id != booking.id,
            Booking.preferred_date > _today,
            Booking.status.in_(('pending', 'confirmed')),
        ).count()

    return render_template('admin/booking_detail.html', booking=booking, staff=active_staff,
                           future_visits=future_visits,
                           pay_url=pay_url, due=amount_due(booking),
                           recurring_upcoming=recurring_upcoming,
                           monthly_choices=monthly_choices,
                           plan_suggestion=plan_suggestion,
                           labor_rate=get_labor_rate(),
                           max_labor_pct=get_max_labor_percent(),
                           ad_expense=Expense.query.filter_by(booking_id=booking.id).first(),
                           ad_categories=[(k, l) for k, l, g, _s in EXPENSE_CATEGORIES
                                          if g == 'Advertising'])


def _link_client(b):
    """Attach this booking to a customer record, creating one if they're new.

    Matches on email first, then phone, so the same person booking twice builds
    a history instead of a second entry. Skips anyone with neither, since
    there'd be nothing to match on and every booking would make a duplicate."""
    if b.client_id:
        return None
    email = (b.email or '').strip().lower()
    phone_digits = ''.join(filter(str.isdigit, b.phone or ''))
    if not email and not phone_digits:
        return None

    client = None
    if email:
        client = Client.query.filter(db.func.lower(Client.email) == email).first()
    if not client and phone_digits:
        for cand in Client.query.filter(Client.phone.isnot(None)).all():
            if ''.join(filter(str.isdigit, cand.phone or '')) == phone_digits:
                client = cand
                break
    if not client:
        client = Client(name=b.name or 'Customer', email=email or '',
                        phone=b.phone or '', address=b.address or '',
                        city=b.city or '', zip_code=b.zip_code or '')
        db.session.add(client)
        db.session.flush()
    b.client_id = client.id
    db.session.commit()
    return client


@bookings_bp.route('/clients/rebuild', methods=['POST'])
@login_required
def rebuild_clients():
    """Build the client list from bookings that were never linked to one.

    Only adds and links — no booking is altered beyond gaining a client_id, and
    nothing is deleted."""
    made, linked = 0, 0
    before = Client.query.count()
    for b in Booking.query.filter(Booking.client_id.is_(None)).order_by(Booking.created_at).all():
        if _link_client(b):
            linked += 1
    made = Client.query.count() - before
    if linked:
        flash(f'Built your client list — {made} new client{"s" if made != 1 else ""} '
              f'from {linked} booking{"s" if linked != 1 else ""}.', 'success')
    else:
        flash('Nothing to import — every booking with contact details is already linked to a client.',
              'success')
    return redirect(url_for('bookings.clients'))


def _notify_customer(b, confirmation=True, pay_kind='none'):
    """Tell the customer about their booking — the confirmation, a payment
    request, or both. Returns a sentence for the flash message.

    Shared by booking creation and the resend button so the two can't drift
    apart. Confirmation and payment are independent: asking for money used to
    silently cancel the confirmation, which meant a failed payment link left
    the customer hearing nothing at all.

    Each send reports separately and a failure keeps its reason, rather than
    being swallowed into one vague warning that vanishes on the next click."""
    reachable = bool(b.email or b.phone)
    if not reachable:
        return ' ⚠️ No email or phone on this booking, so the customer was told nothing.'

    sent, failed = [], []
    if confirmation:
        try:
            _send_booking_confirmation(b)
            sent.append('confirmation 📩')
        except Exception as e:
            failed.append(f'confirmation ({e})')

    if pay_kind in ('deposit', 'full'):
        label = 'deposit request 💳' if pay_kind == 'deposit' else 'payment link 💳'
        try:
            from blueprints.payments import send_payment_link
            send_payment_link(b, kind=pay_kind)
            sent.append(label)
        except Exception as e:
            failed.append(f'{label} ({e})')

    for f in failed:
        flash(f'⚠️ Could not send the {f} to {b.name or "the customer"}. '
              f'Check the Sent Log for details.', 'warning')
        try:
            from notifications import _log_outbound
            _log_outbound('email', b.email or b.phone, b.name,
                          'Booking confirmation / payment request', '', False, f)
        except Exception:
            pass

    return (' Sent the ' + ' and '.join(sent) + '.') if sent else ''


@bookings_bp.route('/<int:booking_id>/send-confirmation', methods=['POST'])
@login_required
def send_confirmation(booking_id):
    """Send (or resend) the booking confirmation on an existing booking, with
    an optional deposit or full payment request alongside it.

    Previously the confirmation only ever fired the moment a booking was
    created — so if it didn't go out then, there was no way to send it at all
    short of writing the whole email by hand."""
    b = Booking.query.get_or_404(booking_id)
    note = _notify_customer(b, confirmation=True,
                            pay_kind=request.form.get('pay_kind', 'none'))
    flash(f'{b.name or "Customer"} —{note}' if note.strip()
          else 'Nothing was sent — check the Sent Log for why.',
          'success' if note.strip() else 'warning')
    return redirect(url_for('bookings.detail', booking_id=booking_id))


@bookings_bp.route('/<int:booking_id>/confirmation/preview')
@login_required
def confirmation_preview(booking_id):
    """Exactly what the customer would get — the email and the text — without
    sending anything."""
    b = Booking.query.get_or_404(booking_id)
    subject, html, sms = confirmation_content(b)
    return f'''<div style="background:#f4f2fa;padding:22px;font-family:system-ui,sans-serif">
  <div style="max-width:620px;margin:0 auto">
    <p style="font-size:0.8rem;color:#5f5878;margin:0 0 4px"><strong>Email to:</strong> {b.email or "(no email on file)"}</p>
    <p style="font-size:0.8rem;color:#5f5878;margin:0 0 14px"><strong>Subject:</strong> {subject}</p>
    <div style="background:#fff;border-radius:12px;padding:26px">{html}</div>
    <p style="font-size:0.8rem;color:#5f5878;margin:22px 0 6px"><strong>Text to:</strong> {b.phone or "(no phone on file)"}</p>
    <div style="background:#e9f7ef;border:1px solid #b7e0c4;border-radius:12px;padding:16px 18px;font-size:0.92rem;color:#1f1333;white-space:pre-wrap">{sms}</div>
    <p style="font-size:0.78rem;color:#9a95ad;margin:16px 0 0">Nothing has been sent. Close this tab and press Send when you're happy.</p>
  </div>
</div>'''


@bookings_bp.route('/<int:booking_id>/send-payment-link', methods=['POST'])
@login_required
def send_payment_link_route(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    kind = request.form.get('kind', 'full')
    from blueprints.payments import send_payment_link
    if not (booking.email or booking.phone):
        flash('This booking has no email or phone to send a link to.', 'warning')
    else:
        ok = send_payment_link(booking, kind=kind)
        flash('Payment link sent 💳' if ok else 'Could not send the link — check email/phone.',
              'success' if ok else 'warning')
    return redirect(url_for('bookings.detail', booking_id=booking_id))


@bookings_bp.route('/<int:booking_id>/email-customer', methods=['GET', 'POST'])
@login_required
def email_customer(booking_id):
    """Compose and send a custom email to the customer on this booking.
    Sends from the branded bookings@ address via Resend; replies go to
    Monica's Gmail (configured in send_email)."""
    booking = Booking.query.get_or_404(booking_id)
    if request.method == 'POST':
        to_email = (request.form.get('to_email') or '').strip()
        subject = (request.form.get('subject') or '').strip()
        message = (request.form.get('message') or '').strip()
        if not to_email or '@' not in to_email:
            flash('Please enter a valid email address to send to.', 'warning')
            return redirect(url_for('bookings.email_customer', booking_id=booking_id))
        if not subject or not message:
            flash('Please fill in both a subject and a message.', 'warning')
            return redirect(url_for('bookings.email_customer', booking_id=booking_id))
        # Keep the booking's email in sync if it was corrected or added here.
        if to_email != (booking.email or ''):
            booking.email = to_email
            db.session.commit()
        from notifications import send_email, _wrap_html
        html = _wrap_html(message, branding.biz_name())
        ok, detail = send_email(to_email=to_email, to_name=(booking.name or 'there'),
                                subject=subject, html=html)
        if ok:
            flash(f'Email sent to {booking.email} ✅', 'success')
            return redirect(url_for('bookings.detail', booking_id=booking_id))
        flash(f'Could not send the email — {detail}', 'warning')
        return redirect(url_for('bookings.email_customer', booking_id=booking_id))
    return render_template('admin/email_customer.html', booking=booking)


@bookings_bp.route('/<int:booking_id>/correct-price', methods=['GET', 'POST'])
@login_required
def correct_price(booking_id):
    """Fix a booking that went out with the wrong price, then email + text the
    customer a clear 'we corrected your quote' notice showing old → new."""
    from pricing import calculate_price
    booking = Booking.query.get_or_404(booking_id)

    # Recalculate the correct total from the current (fixed) matrix, keeping the
    # booking's existing lead fee. This is the pre-filled suggestion — editable.
    try:
        cleaning = calculate_price(
            service_type=booking.service_type or 'standard',
            bedrooms=booking.bedrooms or 1, bathrooms=booking.bathrooms or 1,
            extras=booking.extras or '', frequency=booking.frequency or 'one_time',
            sqft=booking.sqft,
        )
    except Exception:
        cleaning = 0.0
    suggested_total = round((cleaning or 0) + (booking.lead_fee or 0), 2)
    old_price = round(booking.price or 0, 2)

    if request.method == 'POST':
        raw = request.form.get('new_price', '').strip().replace('$', '').replace(',', '')
        try:
            new_price = round(float(raw), 2)
        except ValueError:
            flash('Please enter a valid corrected price.', 'warning')
            return redirect(url_for('bookings.correct_price', booking_id=booking_id))

        personal_note = (request.form.get('personal_note') or '').strip()
        channels = request.form.getlist('channel')          # ['email', 'sms']
        if not channels:
            channels = ['email', 'sms']

        # 1) Save the corrected price first so the fix always sticks.
        prev_price = old_price
        booking.price = new_price
        deposit_paid = 50 if booking.deposit_paid else 0
        booking.balance_due = round(max(0.0, new_price - deposit_paid), 2)
        stamp = datetime.utcnow().strftime('%b %d, %Y')
        booking.internal_notes = ((booking.internal_notes or '')
                                  + f'\n[Price corrected ${prev_price:.2f} → ${new_price:.2f} and customer notified on {stamp}]').strip()
        db.session.commit()

        # 2) Best-effort notify — the save above never depends on this.
        first = (booking.name or 'there').split()[0]
        when = f"{booking.preferred_date or ''}{(' at ' + booking.preferred_time) if booking.preferred_time else ''}".strip()
        results = []

        if 'email' in channels and booking.email:
            from notifications import send_email
            note_html = f'<p style="margin:0 0 10px">{personal_note}</p>' if personal_note else ''
            html = f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <div style="background:linear-gradient(135deg,#1f1333,#3b2460);padding:26px 30px;border-radius:12px 12px 0 0">
    <p style="color:#d3a84f;font-size:1.1rem;font-weight:700;margin:0">{branding.biz_name()}</p>
  </div>
  <div style="background:#fff;padding:28px 30px;border-radius:0 0 12px 12px;border:1px solid #e4dfef;border-top:none">
    <p>Hi {first},</p>
    <p>We found an error in the pricing on your recent quote and want to make it right. Here is your corrected total:</p>
    <div style="background:#f6f5fb;border-radius:10px;padding:18px 20px;margin:16px 0;text-align:center">
      <span style="color:#9a95ad;text-decoration:line-through;font-size:1.1rem">${prev_price:,.2f}</span>
      <span style="color:#9a95ad;margin:0 8px">→</span>
      <span style="color:#065f46;font-weight:800;font-size:1.7rem">${new_price:,.2f}</span>
    </div>
    <div style="background:#faf9fd;border-radius:10px;padding:14px 18px;margin:16px 0;font-size:0.95rem">
      <p style="margin:4px 0"><strong>Service:</strong> {booking.service_label}</p>
      {f'<p style="margin:4px 0"><strong>When:</strong> {when}</p>' if when else ''}
      <p style="margin:4px 0"><strong>Corrected total:</strong> ${new_price:,.2f}</p>
    </div>
    {note_html}
    <p>Sorry for the mix-up! Your booking is confirmed at the corrected total above. Just reply to this email or text us with any questions.</p>
    <p style="margin-top:16px">Thank you,<br><strong>{branding.biz_name()}</strong></p>
    <hr style="border:none;border-top:1px solid #e4dfef;margin:22px 0">
    <p style="font-size:0.78rem;color:#9a95ad;margin:0">{branding.biz_name()} · Orlando, FL · Reply to this email with any questions.</p>
  </div>
</div>"""
            ok, detail = send_email(to_email=booking.email, to_name=booking.name,
                                    subject=f'Your corrected cleaning quote — {branding.biz_name()}',
                                    html=html)
            results.append(('email', ok, detail))

        if 'sms' in channels and booking.phone:
            from notifications import send_sms
            sms = (f"Hi {first}! We corrected an error on your {branding.biz_name()} quote. "
                   f"Your updated total is ${new_price:,.2f} (was ${prev_price:,.2f})"
                   + (f" for your {when} cleaning" if when else "")
                   + ". Sorry for the mix-up! Reply with any questions.")
            if personal_note:
                sms += f' {personal_note}'
            ok, detail = send_sms(booking.phone, sms)
            results.append(('sms', ok, detail))

        sent = [c for c, ok, _ in results if ok]
        failed = [f'{c} ({d})' for c, ok, d in results if not ok]
        if sent and not failed:
            flash(f'Price corrected to ${new_price:,.2f} and customer notified by {", ".join(sent)} ✅', 'success')
        elif sent and failed:
            flash(f'Price corrected. Sent by {", ".join(sent)}, but {", ".join(failed)} failed.', 'warning')
        elif failed:
            flash(f'Price saved (${new_price:,.2f}) but nothing sent — {", ".join(failed)}', 'warning')
        else:
            flash(f'Price corrected to ${new_price:,.2f}, but this booking has no email or phone to notify.', 'warning')
        return redirect(url_for('bookings.detail', booking_id=booking_id))

    return render_template('admin/correct_price.html', booking=booking,
                           old_price=old_price, suggested_total=suggested_total,
                           cleaning=round(cleaning or 0, 2))


@bookings_bp.route('/<int:booking_id>/notify-pay', methods=['POST'])
@login_required
def notify_pay(booking_id):
    """Text the cleaner their current (corrected) pay for this job. On a crew job
    every member gets their own share, not the job total."""
    import secrets as _secrets
    from models import BusinessSetting
    from notifications import send_sms
    from translate import translate
    b = Booking.query.get_or_404(booking_id)

    if b.crew:
        targets = [(c.staff, c.pay_amount or 0) for c in b.crew if c.staff]
    else:
        name = b.assigned_cleaner or ''
        s = Staff.query.filter(db.func.lower(Staff.name) == name.lower()).first() if name else None
        targets = [(s, b.pay_for(s))] if s else []
    targets = [(s, p) for s, p in targets if s and s.phone]
    if not targets:
        flash('No assigned cleaner with a phone number to notify.', 'warning')
        return redirect(url_for('bookings.detail', booking_id=booking_id))

    biz = branding.biz_name()
    base = branding.crm_base()
    sent, failed = [], None
    for s, pay in targets:
        if not s.agreement_token:
            s.agreement_token = _secrets.token_urlsafe(32)
            db.session.commit()
        myday = f"{base}/contractors/my-day/{s.agreement_token}"
        first = (s.name or '').split()[0]
        msg = (f"Hi {first}! Quick update on your {b.preferred_date or ''} job — your pay is "
               f"${pay:.2f}. Full details here: {myday} — {biz}")
        if (s.language or 'en') == 'es':
            msg = translate(msg, target='es')
        ok, detail = send_sms(s.phone, msg)
        if ok:
            sent.append(f'{s.name} (${pay:.2f})')
        else:
            failed = detail
    if sent:
        flash('Updated pay sent to ' + ', '.join(sent) + '.', 'success')
    else:
        flash('Could not send: ' + (failed or 'unknown error'), 'warning')
    return redirect(url_for('bookings.detail', booking_id=booking_id))


@bookings_bp.route('/<int:booking_id>/broadcast', methods=['POST'])
@login_required
def broadcast(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    from blueprints.claims import broadcast_job
    n = broadcast_job(booking)
    if booking.crew or booking.is_crew_job:
        left = booking.spots_left
        if not left:
            flash(f'This job is already assigned to {booking.crew_label} — '
                  f'remove them from the Crew card first to put it back on the board.', 'warning')
        else:
            flash(f'📣 Offered to {n} cleaner(s) — the first {left} to claim get the {left} open spot(s).', 'success')
    else:
        flash(f'📣 Offered to {n} cleaner(s) — first to claim it gets it.', 'success')
    return redirect(url_for('bookings.detail', booking_id=booking_id))


def _apply_hours(booking, form):
    """Read the person-hours fields off whichever form was submitted.

    The hours box sits in the crew card but used to belong to the job-edit form
    above it, so pressing the Save button directly beneath it submitted a form
    that did not contain the hours -- they were dropped without a word and the
    box came back empty. Both buttons now save them.

    A field that is absent is left alone; a field that is present and blank is a
    deliberate clear.
    """
    changed = False
    if 'estimated_hours' in form:
        raw = (form.get('estimated_hours') or '').strip()
        if raw == '':
            booking.estimated_hours = None
            changed = True
        else:
            try:
                booking.estimated_hours = float(raw)
                # First time a job gets hours, lock in today's rate. Never
                # re-stamp after — that's what "Re-rate" is for.
                if booking.estimated_hours and not booking.labor_rate_applied:
                    from pricing import get_labor_rate as _rate
                    booking.labor_rate_applied = _rate()
                changed = True
            except ValueError:
                pass
    if 'owner_hours' in form:
        raw = (form.get('owner_hours') or '').strip()
        try:
            booking.owner_hours = max(0.0, float(raw)) if raw else 0
            changed = True
        except ValueError:
            pass
    return changed


# ── Crew & pay: who is being paid for this job, and how much ────────────────
@bookings_bp.route('/<int:booking_id>/crew', methods=['POST'])
@login_required
def save_crew(booking_id):
    """Set how many cleaners are being PAID for this job, put specific people on
    it, and set each person's pay by hand.

    This works for one cleaner as much as for a crew — if the owner is working
    the house herself alongside one cleaner, that's 1 paid cleaner at whatever
    amount she decides, which the automatic percentage can't express."""
    b = Booking.query.get_or_404(booking_id)
    msgs = []

    # 0) The hours, which live in this card and are what the pay is worked out
    #    from. Saved by the button underneath them, not only by the one two
    #    cards up the page.
    if _apply_hours(b, request.form) and b.labor_budget is not None:
        msgs.append(f'{b.estimated_hours:g} person-hours × ${b.rate_applied:.0f}/hr '
                    f'= ${b.labor_budget:.2f} to share')

    # 1) How many paid cleaners
    try:
        size = max(1, min(6, int(request.form.get('crew_size') or b.crew_size or 1)))
    except ValueError:
        size = b.crew_size or 1
    if size != (b.crew_size or 1):
        # Never shrink past the people already on it — that would strand someone,
        # and for an already-paid share it would orphan the payment record.
        if size < len(b.crew):
            extra = len(b.crew) - size
            flash(f'Remove {extra} cleaner{"s" if extra != 1 else ""} from this job first, then set it to {size}.', 'error')
            return redirect(url_for('bookings.detail', booking_id=booking_id))
        b.crew_size = size
        msgs.append(f'set to {size} paid cleaner{"s" if size != 1 else ""}')

    # 2) Put a specific cleaner on the job (no job board, no claim link)
    add_id = (request.form.get('add_staff_id') or '').strip()
    added = None
    if add_id:
        s = Staff.query.get(int(add_id))
        if not s:
            pass
        elif b.crew_row_for(s):
            msgs.append(f'{s.name} was already on this job')
        elif len(b.crew) >= (b.crew_size or 1):
            flash(f'This job is set to {b.crew_size} paid cleaner(s) and those spots are filled — '
                  f'raise the count to add another.', 'error')
            return redirect(url_for('bookings.detail', booking_id=booking_id))
        else:
            raw = (request.form.get('add_pay') or '').strip()
            try:
                amount = round(float(raw), 2) if raw else b.default_crew_pay(s)
            except ValueError:
                amount = b.default_crew_pay(s)
            db.session.add(BookingCrew(booking_id=b.id, staff_id=s.id, pay_amount=amount))
            if not b.assigned_cleaner:
                b.assigned_cleaner = s.name
            b.open_for_claim = False        # assigned directly — it's off the board
            added = s
            msgs.append(f'added {s.name} at ${amount:.2f}')
    db.session.commit()

    # 3) Pay amounts — even-split reset, or whatever she typed per person
    if request.form.get('even_split'):
        for c in b.crew:
            if c.staff and not c.paid_at:
                c.pay_amount = b.default_crew_pay(c.staff, size=len(b.crew) or 1)
        msgs.append('split evenly')
    else:
        for c in b.crew:
            raw = (request.form.get(f'pay_{c.id}') or '').strip()
            if raw == '' or c.paid_at:
                continue              # already-paid shares are locked
            try:
                c.pay_amount = round(float(raw), 2)
            except ValueError:
                pass
    db.session.commit()

    over = b.crew_allocated - b.commissionable_price
    if over > 0.01:
        flash(f'Heads up: you\'ve set ${b.crew_allocated:.2f} in pay, which is '
              f'${over:.2f} MORE than the ${b.commissionable_price:.2f} this job earns.', 'warning')

    # Send the job straight to whoever was just added, if asked.
    if added and request.form.get('send_now'):
        return _send_job_to(b, [added])

    flash('Saved — ' + ', '.join(msgs) + '.' if msgs else 'Pay saved.', 'success')
    return redirect(url_for('bookings.detail', booking_id=booking_id))


def _send_job_to(b, people):
    """Email + text these cleaners the job: address, access notes, their pay, and
    the checklist link. This is the direct alternative to the claim board — they
    get the work, not an offer to accept."""
    from blueprints.workorders import create_and_send_workorder
    sent, failed = [], []
    for s in people:
        try:
            create_and_send_workorder(b, recipient=s)
            sent.append(s.name)
        except Exception:
            failed.append(s.name)
    if sent:
        from datetime import datetime as _dt
        b.cleaner_notified_at = _dt.utcnow()
        b.cleaner_response = 'accepted'      # assigned directly, not an offer
        db.session.commit()
        flash(f'📲 Job sent to {", ".join(sent)} — address, pay, and checklist. '
              f'No claim link, it\'s already theirs.', 'success')
    if failed:
        flash(f'Could not reach {", ".join(failed)} — check their phone/email on the Team page.', 'warning')
    return redirect(url_for('bookings.detail', booking_id=b.id))


@bookings_bp.route('/<int:booking_id>/reschedule', methods=['POST'])
@login_required
def reschedule(booking_id):
    """Move a job to another date — used by dragging it on the calendar.

    Deliberately does NOT text anyone. Rearranging a week means dragging jobs
    around several times, and firing a message on every drop would spam the
    team. It reports who needs telling and hands back a one-click way to do it."""
    from datetime import datetime as _dt
    b = Booking.query.get_or_404(booking_id)
    raw = (request.form.get('date') or '').strip()
    try:
        new_date = _dt.strptime(raw[:10], '%Y-%m-%d').date().isoformat()
    except ValueError:
        return jsonify({'ok': False, 'error': 'That is not a valid date.'}), 400

    if b.status in ('completed', 'cancelled'):
        return jsonify({'ok': False,
                        'error': f'This job is {b.status} — reopen it before moving it.'}), 400

    was = b.preferred_date
    if was == new_date:
        return jsonify({'ok': True, 'moved': False})
    b.preferred_date = new_date
    db.session.commit()

    # Anyone already told the old date needs telling again.
    crew = [c.staff.name for c in b.crew if c.staff] or \
           ([b.assigned_cleaner] if b.assigned_cleaner else [])
    return jsonify({
        'ok': True, 'moved': True, 'was': was, 'now': new_date,
        'client': b.name or 'Job',
        'crew': crew,
        'notify_url': url_for('bookings.notify_moved', booking_id=b.id) if crew else None,
    })


@bookings_bp.route('/<int:booking_id>/notify-moved', methods=['POST'])
@login_required
def notify_moved(booking_id):
    """Text whoever is on this job that its date changed."""
    import secrets as _secrets
    from models import BusinessSetting
    from notifications import send_sms
    from translate import translate
    b = Booking.query.get_or_404(booking_id)
    people = [c.staff for c in b.crew if c.staff]
    if not people and b.assigned_cleaner:
        s = Staff.query.filter(db.func.lower(Staff.name) == b.assigned_cleaner.lower()).first()
        people = [s] if s else []

    biz = branding.biz_name()
    when = f"{b.preferred_date}{(' at ' + b.preferred_time) if b.preferred_time else ''}"
    told, failed = [], []
    for s in people:
        if not s.phone:
            failed.append(f'{s.name} (no phone)')
            continue
        first = (s.name or '').split()[0]
        msg = (f"Hi {first} — schedule change: the {b.name or 'job'} at "
               f"{b.address or 'your job'} has moved to {when}. Same job, new date. — {biz}")
        if (s.language or 'en') == 'es':
            msg = translate(msg, target='es')
        ok, detail = send_sms(s.phone, msg)
        (told if ok else failed).append(s.name if ok else f'{s.name} ({detail})')

    if told:
        flash(f'Told {", ".join(told)} the new date.', 'success')
    for f in failed:
        flash(f'⚠️ Could not tell {f}.', 'warning')
    return redirect(request.referrer or url_for('bookings.calendar'))


@bookings_bp.route('/<int:booking_id>/log-ad-cost', methods=['POST'])
@login_required
def log_ad_cost(booking_id):
    """Turn this job's lead fee into the ad expense that actually paid for it.

    The lead fee is a pricing device — a slice of the customer's price set aside
    to cover advertising. The money paid to Google is a separate, real expense.
    Both are correct, but typing the same figure twice is friction, so this
    writes the expense from the fee and links it to the job it bought."""
    from models import Expense
    b = Booking.query.get_or_404(booking_id)
    back = redirect(url_for('bookings.detail', booking_id=booking_id))

    if not b.lead_fee:
        flash('There is no lead fee on this job to log.', 'warning')
        return back
    if Expense.query.filter_by(booking_id=b.id).first():
        flash('The ad cost for this job is already in your expenses.', 'warning')
        return back

    raw = (request.form.get('amount') or '').strip()
    try:
        amount = round(float(raw), 2) if raw else round(b.lead_fee, 2)
    except ValueError:
        amount = round(b.lead_fee, 2)
    category = request.form.get('category', 'ads_google')

    db.session.add(Expense(
        date=b.preferred_date or date.today().isoformat(),
        category=category, amount=amount, booking_id=b.id,
        vendor=request.form.get('vendor') or None,
        note=f'Lead for {b.name or "a job"}', method='card'))
    db.session.commit()
    flash(f'Logged ${amount:.2f} of ad cost for {b.name or "this job"} — it now shows in '
          f'your Expenses and Profit & Loss.', 'success')
    return back


@bookings_bp.route('/<int:booking_id>/re-rate', methods=['POST'])
@login_required
def re_rate(booking_id):
    """Move an unpaid job onto the current hourly rate.

    Deliberately a separate, explicit action. Jobs keep the rate they were
    quoted at so raising the company rate can't quietly restate work already
    agreed — but an unpaid job sometimes should move, and this is the only way
    it does."""
    from pricing import get_labor_rate
    b = Booking.query.get_or_404(booking_id)
    back = redirect(url_for('bookings.detail', booking_id=booking_id))
    if b.cleaner_paid_at or any(c.paid_at for c in b.crew):
        flash('Someone has already been paid for this job — its rate stays as it was.', 'error')
        return back
    was, now = b.labor_rate_applied, get_labor_rate()
    b.labor_rate_applied = now
    db.session.commit()
    flash(f'Re-rated from ${was:.0f} to ${now:.0f} per hour — this job now pays '
          f'${b.labor_budget:.2f}.', 'success')
    return back


@bookings_bp.route('/<int:booking_id>/crew/send', methods=['POST'])
@login_required
def send_crew(booking_id):
    """Send the job directly to everyone on it (or one person via crew_id)."""
    b = Booking.query.get_or_404(booking_id)
    crew_id = request.form.get('crew_id')
    rows = [c for c in b.crew if c.staff and (not crew_id or str(c.id) == crew_id)]
    if not rows:
        flash('Nobody is on this job yet — add a cleaner first.', 'warning')
        return redirect(url_for('bookings.detail', booking_id=booking_id))
    return _send_job_to(b, [c.staff for c in rows])


@bookings_bp.route('/<int:booking_id>/crew/remove/<int:crew_id>', methods=['POST'])
@login_required
def remove_crew(booking_id, crew_id):
    b = Booking.query.get_or_404(booking_id)
    c = BookingCrew.query.filter_by(id=crew_id, booking_id=b.id).first_or_404()
    if c.paid_at:
        flash(f'{c.staff.name if c.staff else "That cleaner"} was already paid for this job — '
              f'removing them would orphan the payment.', 'error')
        return redirect(url_for('bookings.detail', booking_id=booking_id))
    name = c.staff.name if c.staff else 'Cleaner'
    was_lead = (b.assigned_cleaner or '').lower() == name.lower()
    db.session.delete(c)
    db.session.commit()
    if was_lead:
        b.assigned_cleaner = b.crew_names[0] if b.crew else None
        db.session.commit()
    flash(f'{name} removed from the crew — that spot is open again. Offer it to the team to refill it.', 'success')
    return redirect(url_for('bookings.detail', booking_id=booking_id))


@bookings_bp.route('/<int:booking_id>/mark-paid', methods=['POST'])
@login_required
def mark_paid_route(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    method = request.form.get('method', 'cash')
    from blueprints.payments import mark_paid
    # Revenue counts on the day the money arrived, which for cash is the day of
    # the job — not whenever she gets round to recording it.
    when = _payment_date(request.form.get('paid_on'), booking)
    # Unticked means record it and say nothing — for a payment already
    # receipted elsewhere, or a booking where another email would do harm.
    notify = bool(request.form.get('send_receipt'))
    try:
        mark_paid(booking, method=method, when=when, notify=notify)
        flash(f'Marked as paid ✅ ({method}) — dated {when.strftime("%b %-d, %Y")}.'
              + ('' if notify else ' No receipt was sent.'), 'success')
    except Exception:
        db.session.rollback()
        flash('Could not mark as paid.', 'error')
    return redirect(url_for('bookings.detail', booking_id=booking_id))


def _payment_date(raw, booking=None):
    """Parse the date money changed hands: what she typed, else the job's own
    date, else now."""
    from datetime import datetime as _dt
    for candidate in (raw, getattr(booking, 'preferred_date', None)):
        if candidate:
            try:
                return _dt.strptime(str(candidate)[:10], '%Y-%m-%d')
            except ValueError:
                continue
    return _dt.utcnow()


@bookings_bp.route('/<int:booking_id>/payment-date', methods=['POST'])
@login_required
def fix_payment_date(booking_id):
    """Correct the date a customer's payment landed, so revenue sits in the
    right month on the P&L."""
    from datetime import datetime as _dt
    b = Booking.query.get_or_404(booking_id)
    back = redirect(url_for('bookings.detail', booking_id=booking_id))
    if not b.paid_at:
        flash('That booking isn\'t marked paid yet.', 'warning')
        return back
    try:
        when = _dt.strptime((request.form.get('paid_on') or '')[:10], '%Y-%m-%d')
    except ValueError:
        flash('Enter the date as a real calendar date.', 'error')
        return back
    was = b.paid_at
    b.paid_at = when
    db.session.commit()
    moved = was.strftime('%b %Y') != when.strftime('%b %Y')
    flash(f'Payment re-dated to {when.strftime("%b %-d, %Y")}.'
          + (f' This income now counts in {when.strftime("%B")}, not {was.strftime("%B")}.' if moved else ''),
          'success')
    return back


@bookings_bp.route('/_fixdb')
@login_required
def fixdb():
    """Diagnostic + self-heal: run the column migration on-demand and report the
    real DB state / error. Visit /bookings/_fixdb while logged in."""
    import traceback
    from sqlalchemy import inspect as _inspect
    out = []
    try:
        from app import _migrate_db
        _migrate_db()
        out.append('✅ _migrate_db() ran')
    except Exception:
        out.append('❌ _migrate_db() ERROR:\n' + traceback.format_exc())
    for tbl in ('booking', 'staff'):
        try:
            cols = [c['name'] for c in _inspect(db.engine).get_columns(tbl)]
            has = 'access_notes' in cols if tbl == 'booking' else 'schedule_reminder_date' in cols
            out.append(f'{tbl}: {len(cols)} cols · key column present = {has}\n  ' + ', '.join(cols))
        except Exception:
            out.append(f'{tbl} inspect ERROR:\n' + traceback.format_exc())
    try:
        out.append(f'✅ Booking.query.count() = {Booking.query.count()}')
    except Exception:
        out.append('❌ Booking query ERROR:\n' + traceback.format_exc())
    return '<pre style="font-family:monospace;font-size:13px;padding:20px;white-space:pre-wrap">' + '\n\n'.join(out) + '</pre>'


@bookings_bp.route('/<int:booking_id>/charge-balance', methods=['POST'])
@login_required
def charge_balance(booking_id):
    from flask import jsonify
    from payment_service import charge_balance as do_charge
    booking = Booking.query.get_or_404(booking_id)
    ok, error = do_charge(booking)
    db.session.commit()
    return jsonify({'ok': ok, 'error': error})


@bookings_bp.route('/<int:booking_id>/send-invoice', methods=['POST'])
@login_required
def send_invoice(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    import invoicing
    from blueprints.payments import payment_link_url, amount_due
    from notifications import send_email
    from models import BusinessSetting
    # An invoice already issued keeps its dates unless she asks for new ones —
    # a document the customer already has shouldn't change under them silently.
    if request.form.get('reissue_dates'):
        booking.invoice_issued_at = None
        booking.invoice_due_date = None
    invoicing.issue(booking)
    payment_link_url(booking, 'full')  # ensure pay_token exists
    biz = branding.biz_name()
    inv_url = request.host_url.rstrip('/') + url_for('invoices.view', token=booking.pay_token)
    due = amount_due(booking)
    sent = False
    if booking.email:
        html = f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <div style="background:#1f1333;padding:22px;text-align:center;border-radius:12px 12px 0 0">
    <div style="color:#d3a84f;font-size:1.3rem;font-weight:800">{biz}</div>
  </div>
  <div style="padding:26px;background:#fff;border:1px solid #e4dfef;border-top:none;border-radius:0 0 12px 12px">
    <p>Hi {booking.name or 'there'},</p>
    <p>Here's your invoice <strong>{booking.invoice_number}</strong> — total due <strong>${due:,.2f}</strong>{(', by ' + booking.invoice_due_date) if booking.invoice_due_date else ''}.</p>
    <div style="text-align:center;margin:22px 0">
      <a href="{inv_url}" style="background:#d3a84f;color:#1f1333;padding:14px 30px;border-radius:999px;text-decoration:none;font-weight:800">View &amp; pay invoice →</a>
    </div>
    <p style="font-size:0.85rem;color:#9a95ad">Thank you for choosing {biz}! 💛</p>
  </div>
</div>"""
        ok, _ = send_email(booking.email, booking.name, f'Invoice {booking.invoice_number} from {biz}', html)
        sent = ok
    booking.invoice_sent_at = datetime.utcnow()
    db.session.commit()
    if sent:
        flash(f'🧾 Invoice {booking.invoice_number} sent to {booking.email}.', 'success')
    else:
        flash(f'Invoice {booking.invoice_number} created — share the link manually (no email on file, or send failed).', 'warning')
    return redirect(url_for('bookings.detail', booking_id=booking_id))


@bookings_bp.route('/<int:booking_id>/address', methods=['POST'])
@login_required
def update_address(booking_id):
    """Move a job to a different address — and the rest of the plan with it.

    A customer who moves house does not get a new booking; she keeps the
    cleaning plan she already had. But every visit in a recurring series holds
    its own copy of the address (recurring.py copies it onto each one), and the
    cleaner is texted the address of the visit she claimed. Changing one row
    would send somebody to the old house for the next eleven months.

    Visits that have already happened keep the old address on purpose. That is
    where the work was actually done, and the chargeback evidence pack quotes
    it — rewriting history to match today would make a true document false.
    """
    booking = Booking.query.get_or_404(booking_id)
    address = (request.form.get('address') or '').strip()
    city = (request.form.get('city') or '').strip()
    zip_code = (request.form.get('zip_code') or '').strip()

    if not address:
        flash('An address is needed — leave the rest blank if you only have the street.', 'error')
        return redirect(url_for('bookings.detail', booking_id=booking_id))

    old = booking.address
    booking.address, booking.city, booking.zip_code = address, city, zip_code

    moved = 0
    if request.form.get('apply_series') and booking.recurring_group:
        today = date.today().isoformat()
        for visit in Booking.query.filter_by(recurring_group=booking.recurring_group).all():
            if visit.id == booking.id:
                continue
            # Only what hasn't happened yet. A visit that is done, or is today
            # and may already have a cleaner on the doorstep, is left alone.
            if (visit.preferred_date or '') > today and visit.status in ('pending', 'confirmed'):
                visit.address, visit.city, visit.zip_code = address, city, zip_code
                moved += 1

    client_updated = False
    if request.form.get('apply_client') and booking.client_id:
        client = Client.query.get(booking.client_id)
        if client:
            client.address, client.city, client.zip_code = address, city, zip_code
            client_updated = True

    note = f'[{date.today().isoformat()}] Address changed from "{old or "blank"}" to "{address}".'
    booking.internal_notes = (note + '\n' + (booking.internal_notes or '')).strip()
    db.session.commit()

    msg = f'📍 Address updated to {address}.'
    if moved:
        msg += f' {moved} future visit{"s" if moved != 1 else ""} moved with it.'
    if client_updated:
        msg += ' Her client record was updated too.'
    flash(msg, 'success')
    return redirect(url_for('bookings.detail', booking_id=booking_id))


@bookings_bp.route('/<int:booking_id>/schedule-recurring', methods=['POST'])
@login_required
def schedule_recurring(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.frequency in ('one_time', None) or not booking.preferred_date:
        flash('Set a repeat frequency and a date first, then schedule the plan.', 'error')
        return redirect(url_for('bookings.detail', booking_id=booking_id))
    mode = request.form.get('monthly_mode')
    if booking.frequency == 'monthly' and mode in (recurring.BY_DATE, recurring.BY_WEEKDAY):
        if (booking.monthly_mode or recurring.BY_DATE) != mode:
            # She's changed how the plan repeats, so the visits already generated
            # are on the wrong days. Clear the future ones and lay them out again.
            # Only unstarted visits are touched — anything confirmed, completed
            # or in the past stays exactly where it is.
            removed = recurring.clear_future(booking)
            if removed:
                flash(f'Rescheduled — {removed} future visit'
                      f'{"s" if removed != 1 else ""} moved to the new pattern.', 'success')
        booking.monthly_mode = mode
        db.session.commit()

    n = recurring.generate_series(booking)
    if n:
        flash(f'📅 Recurring plan set — {n} future visit{"s" if n != 1 else ""} added to your calendar.', 'success')
    else:
        flash('That plan is already filled in as far ahead as we schedule — '
              'no new visits needed.', 'success')
    return redirect(url_for('bookings.detail', booking_id=booking_id))


def _proposal_content(booking):
    """(subject, html, sms) asking a customer to confirm a date and price."""
    from blueprints.confirm import proposal_url
    biz = branding.biz_name()
    first = (booking.name or 'there').split()[0]
    url = proposal_url(booking)
    # "Fri 28 Aug", not "2026-08-28". A customer reading a text should see the
    # day of the week — that is what tells them whether it works.
    try:
        day = date.fromisoformat(booking.preferred_date)
        when = day.strftime('%a %-d %b')
    except (ValueError, TypeError):
        when = booking.preferred_date or 'a date that suits you'
    if booking.preferred_time:
        when += f' at {booking.preferred_time}'
    price = f'${booking.price:.2f}' if booking.price else 'the agreed price'
    repeats = ''
    if booking.frequency and booking.frequency != 'one_time':
        word = {'weekly': 'every week', 'biweekly': 'every 2 weeks',
                'monthly': 'every month'}.get(booking.frequency, booking.frequency)
        repeats = f'<p style="margin:0 0 14px">After that we\'d come <strong>{word}</strong>.</p>'

    # Anything the owner wrote herself replaces the stock opening line — her own
    # words to someone she has spoken to will always beat a template.
    note = (booking.confirm_note or '').strip()
    if note:
        opening = ''.join(
            f'<p style="margin:0 0 14px">{line.strip()}</p>'
            for line in note.split('\n') if line.strip())
    else:
        opening = ('<p style="margin:0 0 14px">You mentioned you were after regular cleaning, '
                   "and I didn't want to keep chasing you. Here's what I have pencilled in — "
                   '<strong>nothing is booked until you say so</strong>.</p>')

    subject = f'Your next cleaning — shall we book it in?'
    html = f"""
<div style="font-family:Inter,-apple-system,sans-serif;max-width:520px;margin:0 auto;color:#1f1333;line-height:1.6">
  <h2 style="color:#b98a33;font-size:1.3rem;margin:0 0 14px">Hi {first} — shall we book this in?</h2>
  {opening}
  <div style="background:#faf9fd;border-radius:12px;padding:16px 18px;margin:18px 0">
    <p style="margin:4px 0"><strong>Service:</strong> {booking.service_label}</p>
    <p style="margin:4px 0"><strong>When:</strong> {when}</p>
    <p style="margin:4px 0"><strong>Price:</strong> {price}</p>
  </div>
  {repeats}
  <p style="margin:24px 0"><a href="{url}"
     style="background:#d3a84f;color:#1a1225;padding:14px 30px;border-radius:999px;
            text-decoration:none;font-weight:700;display:inline-block">Confirm or decline →</a></p>
  <p style="color:#5f5878;font-size:0.9rem;margin:0 0 14px">
    One tap either way. A no is completely fine — I'd just rather know than keep ringing.</p>
  <p style="margin:14px 0 0">— {biz}</p>
</div>"""
    # The page offers three answers, so the text must not promise only two —
    # somebody who wants the clean but not that day needs to know they can say so.
    sms = (f"Hi {first}! It's {biz}. I've pencilled you in for {when}, {price}. "
           f"Nothing's booked yet — confirm or pick a better time: {url} "
           f"Reply STOP to opt out.")
    return subject, html, sms


def _save_proposal(booking):
    """Save what the owner is proposing, so preview and send always agree.

    The date, time, price and frequency are edited here rather than somewhere
    else first — this is the moment she is deciding what to offer, and making
    her go and edit the booking, come back, and hope she remembered correctly is
    how the wrong price gets sent."""
    if 'confirm_note' in request.form:
        booking.confirm_note = (request.form.get('confirm_note') or '').strip() or None

    freq = request.form.get('plan_frequency')
    if freq in ('one_time', 'weekly', 'biweekly', 'monthly'):
        booking.frequency = freq

    for field, attr in (('plan_date', 'preferred_date'), ('plan_time', 'preferred_time')):
        if field in request.form:
            value = (request.form.get(field) or '').strip()
            if value:
                setattr(booking, attr, value)

    if 'plan_price' in request.form:
        raw = (request.form.get('plan_price') or '').strip().replace('$', '').replace(',', '')
        if raw:
            try:
                booking.price = round(float(raw), 2)
            except ValueError:
                flash('That price is not a number — leaving it as it was.', 'warning')
    db.session.commit()


@bookings_bp.route('/<int:booking_id>/proposal/preview', methods=['GET', 'POST'])
@login_required
def proposal_preview(booking_id):
    """See the email and the text before either reaches the customer."""
    b = Booking.query.get_or_404(booking_id)
    _save_proposal(b)
    subject, html, sms = _proposal_content(b)
    return f'''<div style="background:#f4f2fa;padding:22px;font-family:system-ui,sans-serif">
  <div style="max-width:620px;margin:0 auto">
    <p style="font-size:0.8rem;color:#5f5878;margin:0 0 4px"><strong>Email to:</strong> {b.email or "(no email on file)"}</p>
    <p style="font-size:0.8rem;color:#5f5878;margin:0 0 14px"><strong>Subject:</strong> {subject}</p>
    <div style="background:#fff;border-radius:12px;padding:26px">{html}</div>
    <p style="font-size:0.8rem;color:#5f5878;margin:22px 0 6px"><strong>Text to:</strong> {b.phone or "(no phone on file)"}</p>
    <div style="background:#e9f7ef;border:1px solid #b7e0c4;border-radius:12px;padding:16px 18px;font-size:0.92rem;white-space:pre-wrap">{sms}</div>
    <p style="font-size:0.78rem;color:#9a95ad;margin:16px 0 0">Nothing has been sent.</p>
  </div>
</div>'''


@bookings_bp.route('/<int:booking_id>/proposal/send', methods=['POST'])
@login_required
def proposal_send(booking_id):
    """Send the ask — to the customer, or to yourself first."""
    from notifications import send_email, send_sms
    b = Booking.query.get_or_404(booking_id)
    _save_proposal(b)
    to_self = request.form.get('to') != 'customer'
    subject, html, sms = _proposal_content(b)

    if to_self:
        ok, detail = send_email(to_email=branding.owner_email(), to_name=b.name or 'there',
                                subject=f'[TEST] {subject}', html=html)
        flash(f'Test sent to {branding.owner_email()}. The text would read: "{sms[:90]}…"'
              if ok else f"Couldn't send: {detail}", 'success' if ok else 'error')
        return redirect(url_for('bookings.detail', booking_id=b.id))

    sent = []
    if b.email:
        ok, _ = send_email(to_email=b.email, to_name=b.name, subject=subject, html=html)
        if ok:
            sent.append('email')
    if b.phone:
        try:
            ok, _ = send_sms(b.phone, sms)
            if ok:
                sent.append('text')
        except Exception:
            pass
    if sent:
        b.confirm_sent_at = datetime.utcnow()
        db.session.commit()
        flash(f"Asked {b.name} to confirm — sent by {' and '.join(sent)}. "
              f"You'll be told either way.", 'success')
    else:
        flash('Nothing could be sent — check the Sent Log for why.', 'warning')
    return redirect(url_for('bookings.detail', booking_id=b.id))


@bookings_bp.route('/<int:booking_id>/onsite', methods=['POST'])
@login_required
def set_onsite(booking_id):
    """Record who was actually on site.

    Kept apart from the crew on purpose. The crew decides what each cleaner is
    paid, so naming people there weeks later would rewrite a past job's payout.
    This is a statement of fact for an invoice or a dispute and touches no money."""
    b = Booking.query.get_or_404(booking_id)
    b.onsite_people = (request.form.get('onsite_people') or '').strip() or None
    db.session.commit()
    flash('Saved who was on site.', 'success')
    return redirect(url_for('bookings.dispute_evidence', booking_id=b.id))


@bookings_bp.route('/<int:booking_id>/dispute-evidence')
@login_required
def dispute_evidence(booking_id):
    """Everything the CRM knows about one job, laid out for a chargeback.

    A card network gives you days to prove a service was authorised and
    delivered. That evidence is already here — the booking, the payment, every
    message sent and when, the photos the cleaner took — but scattered across
    pages, and nobody assembles it calmly under a deadline.

    This states only what the records actually show. Where something is missing
    it says so, because a gap you have spotted yourself is survivable and one the
    bank spots for you is not."""
    import json
    from models import JobChecklist, OutboundLog
    b = Booking.query.get_or_404(booking_id)

    # Every message to this customer, on any channel, in order.
    targets = [t for t in ((b.email or '').lower(), (b.phone or '')) if t]
    messages = []
    if targets:
        rows = OutboundLog.query.order_by(OutboundLog.created_at).all()
        for r in rows:
            addr = (r.to_address or '').lower()
            digits = ''.join(ch for ch in (r.to_address or '') if ch.isdigit())
            phone_digits = ''.join(ch for ch in (b.phone or '') if ch.isdigit())
            if (b.email and addr == (b.email or '').lower()) or \
               (phone_digits and digits and digits[-10:] == phone_digits[-10:]):
                messages.append(r)

    checklist = JobChecklist.query.filter_by(booking_id=b.id).first()
    photos = {'before': [], 'after': []}
    if checklist:
        for key, field in (('before', checklist.before_photos), ('after', checklist.after_photos)):
            try:
                photos[key] = json.loads(field or '[]')
            except (ValueError, TypeError):
                photos[key] = []

    import customer_terms
    from datetime import datetime as _dt
    # The working view carries guidance on what to submit and what to check.
    # The clean view is the document itself — a bank should receive a record of
    # what happened, not a running commentary on how to argue about it.
    clean = request.args.get('clean') == '1'
    return render_template('admin/dispute_evidence.html', b=b, messages=messages,
                           checklist=checklist, photos=photos,
                           terms=customer_terms.get_terms(),
                           client=b.client, clean=clean,
                           prepared=_dt.utcnow())


@bookings_bp.route('/<int:booking_id>/start-plan', methods=['POST'])
@login_required
def start_plan(booking_id):
    """Begin ongoing cleanings that follow a one-off job.

    The common way a cleaning relationship starts is a deep clean first, then
    lighter visits on a schedule — different service, different price. Turning
    the deep clean itself into a recurring job would have repeated the deep
    clean, at the deep-clean price, forever. So the plan is a separate booking
    that carries the customer over and starts on its own date."""
    first = Booking.query.get_or_404(booking_id)

    frequency = request.form.get('frequency', 'biweekly')
    if frequency not in ('weekly', 'biweekly', 'monthly'):
        flash('Pick how often the cleanings repeat.', 'error')
        return redirect(url_for('bookings.detail', booking_id=booking_id))

    start = (request.form.get('start_date') or '').strip()
    if not start:
        flash('Pick the date of the first ongoing cleaning.', 'error')
        return redirect(url_for('bookings.detail', booking_id=booking_id))

    price_raw = (request.form.get('plan_price') or '').strip().replace('$', '').replace(',', '')
    try:
        price = round(float(price_raw), 2) if price_raw else None
    except ValueError:
        flash('That price is not a number.', 'error')
        return redirect(url_for('bookings.detail', booking_id=booking_id))

    seed = Booking(
        client_id=first.client_id,
        service_type=request.form.get('plan_service') or 'standard',
        bedrooms=first.bedrooms, bathrooms=first.bathrooms, sqft=first.sqft,
        frequency=frequency, monthly_mode=request.form.get('monthly_mode') or None,
        preferred_date=start,
        preferred_time=request.form.get('plan_time') or first.preferred_time,
        name=first.name, email=first.email, phone=first.phone,
        address=first.address, city=first.city, zip_code=first.zip_code,
        access_notes=first.access_notes, price=price,
        source=first.source, status='confirmed',
        # Carry any card on file so the plan can bill itself from visit one.
        stripe_customer_id=first.stripe_customer_id,
        stripe_payment_method_id=first.stripe_payment_method_id,
    )
    db.session.add(seed)
    db.session.commit()
    _link_client(seed)

    made = recurring.generate_series(seed)
    flash(f'📅 Ongoing {frequency} cleanings set up for {seed.name} — '
          f'{made + 1} visits on the calendar, starting {start}.', 'success')
    return redirect(url_for('bookings.detail', booking_id=seed.id))


@bookings_bp.route('/<int:booking_id>/stop-recurring', methods=['POST'])
@login_required
def stop_recurring(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.recurring_group:
        removed = recurring.stop_series(booking.recurring_group)
        flash(f'Recurring plan stopped — removed {removed} upcoming visit{"s" if removed != 1 else ""}.', 'success')
    return redirect(url_for('bookings.detail', booking_id=booking_id))


@bookings_bp.route('/<int:booking_id>/delete', methods=['POST'])
@login_required
def delete(booking_id):
    from models import JobChecklist, BookingRating
    booking = Booking.query.get_or_404(booking_id)
    # Remove child records first so the delete doesn't hit a foreign-key error
    JobChecklist.query.filter_by(booking_id=booking.id).delete()
    BookingRating.query.filter_by(booking_id=booking.id).delete()
    db.session.delete(booking)
    db.session.commit()
    flash('Booking deleted.', 'success')
    return redirect(url_for('bookings.index'))


@bookings_bp.route('/clients')
@login_required
def clients():
    all_clients = Client.query.order_by(Client.created_at.desc()).all()
    # Bookings that never got a customer record — offer to build them.
    unlinked = Booking.query.filter(
        Booking.client_id.is_(None),
        db.or_(db.and_(Booking.email.isnot(None), Booking.email != ''),
               db.and_(Booking.phone.isnot(None), Booking.phone != '')),
    ).count()
    return render_template('admin/clients.html', clients=all_clients, unlinked=unlinked)


@bookings_bp.route('/clients/<int:client_id>')
@login_required
def client_detail(client_id):
    client = Client.query.get_or_404(client_id)
    from blueprints.portal import ensure_portal_token
    portal_url = f"{branding.crm_base()}/portal/{ensure_portal_token(client)}"
    from models import BusinessSetting
    return render_template('admin/client_detail.html', client=client, portal_url=portal_url,
                           invite_sent=BusinessSetting.get(f'portal_invite_sent_{client.id}'))


def _portal_email(client, kind):
    """(subject, html, portal_url) for one of the two portal emails."""
    import portal_invite
    from blueprints.portal import ensure_portal_token
    url = f"{branding.crm_base()}/portal/{ensure_portal_token(client)}"
    if kind == 'nudge':
        return portal_invite.card_nudge_subject(client), portal_invite.card_nudge_html(client, url), url
    return portal_invite.welcome_subject(client), portal_invite.welcome_html(client, url), url


@bookings_bp.route('/clients/<int:client_id>/portal-invite/preview')
@login_required
def portal_invite_preview(client_id):
    """Show the email exactly as the customer would receive it.

    Rendered from her real booking data, not a mock-up — the whole point is that
    what's on screen is what would arrive."""
    client = Client.query.get_or_404(client_id)
    kind = 'nudge' if request.args.get('kind') == 'nudge' else 'welcome'
    subject, html, _ = _portal_email(client, kind)
    return (f'<div style="background:#f4f2fa;padding:22px;font-family:system-ui,sans-serif">'
            f'<div style="max-width:600px;margin:0 auto">'
            f'<p style="font-size:0.8rem;color:#5f5878;margin:0 0 4px">'
            f'<strong>To:</strong> {client.email or "(no email on file)"}</p>'
            f'<p style="font-size:0.8rem;color:#5f5878;margin:0 0 14px">'
            f'<strong>Subject:</strong> {subject}</p>'
            f'<div style="background:#fff;border-radius:12px;padding:26px">{html}</div>'
            f'</div></div>')


@bookings_bp.route('/clients/<int:client_id>/portal-invite/send', methods=['POST'])
@login_required
def portal_invite_send(client_id):
    """Send the welcome or the card nudge — to the customer, or to the owner
    first as a test.

    Sending to yourself first is the default path on purpose. A welcome email is
    the first thing a new client reads from the business, and it cannot be
    unsent."""
    from notifications import send_email
    client = Client.query.get_or_404(client_id)
    kind = 'nudge' if request.form.get('kind') == 'nudge' else 'welcome'
    to_self = request.form.get('to') != 'customer'

    subject, html, _ = _portal_email(client, kind)
    recipient = branding.owner_email() if to_self else (client.email or '')
    if not recipient:
        flash('No email address on file for this client.', 'error')
        return redirect(url_for('bookings.client_detail', client_id=client.id))

    ok, detail = send_email(to_email=recipient, to_name=client.name or 'there',
                            subject=(f'[TEST] {subject}' if to_self else subject),
                            html=html)
    if not ok:
        flash(f"Couldn't send: {detail}", 'error')
    elif to_self:
        flash(f'Test sent to {recipient}. Check it reads the way you want before '
              f'sending it to {client.name}.', 'success')
    else:
        from models import BusinessSetting
        BusinessSetting.set(f'portal_invite_sent_{client.id}', date.today().isoformat())
        db.session.commit()
        flash(f'Welcome email sent to {client.name} at {recipient}.', 'success')
    return redirect(url_for('bookings.client_detail', client_id=client.id))


@bookings_bp.route('/clients/<int:client_id>/delete', methods=['POST'])
@login_required
def delete_client(client_id):
    from models import JobChecklist, BookingRating
    client = Client.query.get_or_404(client_id)
    # Delete this client's bookings and their child records first
    for b in Booking.query.filter_by(client_id=client.id).all():
        JobChecklist.query.filter_by(booking_id=b.id).delete()
        BookingRating.query.filter_by(booking_id=b.id).delete()
        db.session.delete(b)
    db.session.delete(client)
    db.session.commit()
    flash('Client deleted.', 'success')
    return redirect(url_for('bookings.clients'))


# ── Cleaner accept / decline ────────────────────────────────────────────────────

@bookings_bp.route('/<int:booking_id>/cleaner-response', methods=['GET'])
def cleaner_response(booking_id):
    """Public link — cleaner accepts or declines a job."""
    booking = Booking.query.get_or_404(booking_id)
    action = request.args.get('action', '')
    token = request.args.get('token', '')
    import hashlib, os
    expected = hashlib.sha256(f"{booking_id}{os.environ.get('SECRET_KEY','secret')}".encode()).hexdigest()[:16]
    if token != expected:
        return 'Invalid link.', 400
    who = booking.assigned_cleaner or 'The cleaner'
    if action == 'accept':
        booking.cleaner_response = 'accepted'
        booking.internal_notes = (booking.internal_notes or '') + f'\n[Cleaner accepted job on {datetime.utcnow().strftime("%b %d %Y")}]'
        db.session.commit()
        _alert_owner_response(booking, who, accepted=True)
        return '<h2 style="font-family:sans-serif;text-align:center;margin-top:60px;color:#065f46">✅ Job accepted! We\'ll see you on ' + (booking.preferred_date or 'the scheduled date') + '.</h2>'
    elif action == 'decline':
        booking.cleaner_response = 'declined'
        booking.internal_notes = (booking.internal_notes or '') + f'\n[{who} declined job on {datetime.utcnow().strftime("%b %d %Y")} — needs reassignment]'
        db.session.commit()
        _alert_owner_response(booking, who, accepted=False)
        booking.assigned_cleaner = ''      # unassign after the alert so we know who declined
        db.session.commit()
        return '<h2 style="font-family:sans-serif;text-align:center;margin-top:60px;color:#991b1b">Job declined. We\'ve let the office know and will reassign. Thank you for telling us!</h2>'
    return 'Unknown action.', 400


def _alert_owner_response(booking, cleaner_name, accepted):
    """Text + email the owner when a cleaner accepts or (importantly) declines a job."""
    import os
    from models import BusinessSetting
    from notifications import send_email, send_sms
    owner_email = (BusinessSetting.get('email') or os.environ.get('OWNER_EMAIL')
                   or branding.owner_email())
    owner_phone = BusinessSetting.get('phone') or os.environ.get('OWNER_PHONE')
    base = branding.crm_base()
    link = f"{base}/bookings/{booking.id}"
    when = f"{booking.preferred_date or 'TBD'} {booking.preferred_time or ''}".strip()
    if accepted:
        subject = f"✅ {cleaner_name} accepted the {when} job"
        line = f"{cleaner_name} accepted the job for {booking.name} on {when}. They're locked in — nothing to do."
        sms = f"✅ {cleaner_name} accepted the {when} job for {booking.name}."
        color = '#276749'
    else:
        subject = f"⚠️ {cleaner_name} DECLINED — reassign the {when} job"
        line = f"{cleaner_name} declined the job for {booking.name} on {when}. It's now unassigned and needs a new cleaner."
        sms = f"⚠️ {cleaner_name} DECLINED the {when} job for {booking.name}. Reassign: {link}"
        color = '#c53030'
    try:
        send_email(to_email=owner_email, to_name=branding.biz_name(), subject=subject,
                   html=f'<div style="font-family:Inter,sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#1f1333">'
                        f'<h2 style="color:{color}">{subject}</h2><p>{line}</p>'
                        f'<p><a href="{link}" style="color:#d3a84f;font-weight:700">Open the booking →</a></p></div>')
    except Exception:
        pass
    if owner_phone:
        try:
            send_sms(owner_phone, sms)
        except Exception:
            pass


# ── Helpers ────────────────────────────────────────────────────────────────────

def _send_rating_request(booking):
    import secrets as _secrets
    from models import BookingRating
    token = _secrets.token_urlsafe(32)
    r = BookingRating(booking_id=booking.id, token=token)
    db.session.add(r)
    db.session.flush()
    from notifications import send_email, send_sms
    base = branding.crm_base()
    stars_html = ''.join(
        f'<a href="{base}/rate/{token}/{i}" style="font-size:2.2rem;text-decoration:none;margin:0 4px">⭐</a>'
        for i in range(1, 6)
    )
    if booking.email:
        send_email(
            to_email=booking.email, to_name=booking.name,
            subject=f'How was your cleaning? — {branding.biz_name()}',
            html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333;text-align:center">
  <h2 style="color:#b98a33;margin-bottom:6px">How did we do?</h2>
  <p style="color:#5f5878;margin-bottom:24px">Hi {booking.name.split()[0]}, your cleaning is complete! Tap a star to rate your experience:</p>
  <div style="margin:20px 0">{stars_html}</div>
  <p style="font-size:0.82rem;color:#9a95ad">Takes 5 seconds. Your feedback helps us improve.</p>
  <hr style="border:none;border-top:1px solid #e4dfef;margin:20px 0"/>
  <p style="color:#9a95ad;font-size:13px">{branding.biz_name()}{" · " + branding.city_line() if branding.city_line() else ""}</p>
</div>""",
        )

    # Text it too. A cleaning gets rated from a phone, minutes after the cleaner
    # leaves; an email to the same person is read days later if at all. No
    # rating read means no rating given — and no chance to offer a tip either.
    if booking.phone:
        first = (booking.name or 'there').split()[0]
        msg = (f"Hi {first}! How did we do today? Tap to rate your cleaning: "
               f"{base}/rate/{token} — {branding.biz_name()}. Reply STOP to opt out.")
        try:
            send_sms(booking.phone, msg)
        except Exception as e:
            # Never let a failed text stop a job being marked complete — but
            # record it. A bare `pass` here hid a broken send completely.
            from notifications import _log_outbound
            _log_outbound('sms', booking.phone, booking.name,
                          'Rating request', msg, False, str(e))


def _send_followup_email(booking):
    # A pure thank-you. It intentionally does NOT link to Google reviews —
    # the ONLY path to a public review is the star-rating email, which shows
    # the Google link solely to customers who first tap 4-5 stars. This keeps
    # unhappy customers from ever being handed a public-review link.
    from notifications import send_email
    send_email(
        to_email=booking.email,
        to_name=booking.name,
        subject=f'Thank you from {branding.biz_name()}',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#b98a33">Thank you for choosing {branding.biz_name()}!</h2>
  <p>Hi {booking.name},</p>
  <p>Your cleaning is complete — we hope everything sparkles! ✨</p>
  <p>It was a pleasure serving you. If there's anything at all we can make
     better, just reply to this email — we're always here to help.</p>
  <p>Ready to book your next cleaning?
     <a href="{branding.booking_link()}" style="color:#b98a33">Book again here →</a>
  </p>
  <hr style="border:none;border-top:1px solid #e4dfef;margin:22px 0"/>
  <p style="color:#9a95ad;font-size:13px">{branding.biz_name()}{" · " + branding.city_line() if branding.city_line() else ""}</p>
</div>""",
        )



def confirmation_content(booking):
    """(subject, html, sms) for the booking confirmation.

    Built here rather than inside the sender so the owner can look at the exact
    words before they reach a customer. A preview built from a separate copy of
    the wording would drift from the real thing and be worth less than nothing."""
    biz = branding.biz_name()
    first = (booking.name or 'there').split()[0]
    date_text = booking.preferred_date or 'the scheduled date'
    time_text = booking.preferred_time or ''
    when = f"{date_text}{(' at ' + time_text) if time_text else ''}"
    price_text = f"${booking.price:.2f}" if booking.price else ''
    addr = ', '.join([p for p in [booking.address, booking.city, booking.zip_code] if p])

    subject = f"You're booked with {biz}! ✨"
    html = f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#b98a33">You're all set, {first}! ✨</h2>
  <p>Thank you for booking with {biz}. Here are your details:</p>
  <div style="background:#f6f5fb;border-radius:10px;padding:16px 18px;margin:16px 0">
    <p style="margin:4px 0"><strong>Service:</strong> {booking.service_label}</p>
    <p style="margin:4px 0"><strong>When:</strong> {when}</p>
    {f'<p style="margin:4px 0"><strong>Address:</strong> {addr}</p>' if addr else ''}
    {f'<p style="margin:4px 0"><strong>Total:</strong> {price_text}</p>' if price_text else ''}
  </div>
  <p style="font-size:0.82rem;color:#9a95ad;background:#f6f5fb;border-radius:8px;padding:10px 12px">💡 Your price is based on an average-size home for this many bedrooms. Larger homes may have a small size adjustment — always confirmed with you first. No surprises!</p>
  <p>If anything changes or you have questions, just reply to this email or text us — we're happy to help.</p>
  <p style="margin-top:18px">See you soon!<br><strong>{biz}</strong></p>
</div>"""
    sms = (f"Hi {first}! ✨ Your {biz} cleaning is booked for {when}."
           + (f" Total {price_text}." if price_text else "")
           + " Reply here with any questions. Reply STOP to opt out.")
    return subject, html, sms


def _send_booking_confirmation(booking):
    """Confirm a hand-created booking to the customer via email + text.
    No deposit language — a simple 'you're booked' note. Best-effort."""
    from notifications import send_email, send_sms
    subject, html, sms = confirmation_content(booking)

    if booking.email:
        send_email(to_email=booking.email, to_name=booking.name,
                   subject=subject, html=html)

    if booking.phone:
        try:
            send_sms(booking.phone, sms)
        except Exception:
            pass


def _create_next_recurring(booking):
    # Proactively-scheduled series already fill the calendar ahead — don't also
    # create a one-off next visit (that would double-book).
    if booking.recurring_group:
        return
    if booking.frequency in ('one_time', None) or not booking.preferred_date:
        return
    try:
        last_date = date.fromisoformat(booking.preferred_date)
    except ValueError:
        return

    days = {'weekly': 7, 'biweekly': 14, 'monthly': 30}
    delta = days.get(booking.frequency)
    if not delta:
        return

    next_date = last_date + timedelta(days=delta)
    next_booking = Booking(
        client_id=booking.client_id,
        service_type=booking.service_type,
        bedrooms=booking.bedrooms,
        bathrooms=booking.bathrooms,
        extras=booking.extras,
        frequency=booking.frequency,
        preferred_date=next_date.isoformat(),
        preferred_time=booking.preferred_time,
        name=booking.name,
        email=booking.email,
        phone=booking.phone,
        address=booking.address,
        city=booking.city,
        zip_code=booking.zip_code,
        access_notes=booking.access_notes,
        assigned_cleaner=booking.assigned_cleaner,
        status='pending',
        price=booking.price,
        balance_due=booking.balance_due,
    )
    db.session.add(next_booking)


def _notify_cleaner(booking):
    """Email the assigned cleaner with job details, earnings, and accept/decline links."""
    import hashlib, os
    from models import Staff
    from notifications import send_email
    from pricing import SERVICES

    cleaner_name = booking.assigned_cleaner or ''
    staff = None
    if cleaner_name:
        # Exact full-name match first (reliable), then loose first-name fallback
        staff = Staff.query.filter(db.func.lower(Staff.name) == cleaner_name.lower()).first()
        if not staff:
            staff = Staff.query.filter(Staff.name.ilike(f'%{cleaner_name.split()[0]}%')).first()
    if not staff:
        return False  # cleaner not found

    # One source of truth for pay (models.Booking.pay_for) — this used to
    # reimplement the formula inline, which meant it could drift out of step
    # with payroll and quote the cleaner a different number than she was paid.
    earnings = booking.pay_for(staff)
    hrs = booking.hours_each()
    if hrs:
        from pricing import get_labor_rate
        pay_label = f'{hrs:g} hrs × ${get_labor_rate():.0f}/hr'
    elif staff.pay_type == 'percent':
        pay_label = f'{staff.pay_rate:.0f}% of ${booking.commissionable_price:.2f}'
    else:
        pay_label = f'{booking.hours_worked or 0}h × ${staff.pay_rate:.2f}/hr'

    base = branding.crm_base()
    token = hashlib.sha256(f"{booking.id}{os.environ.get('SECRET_KEY','secret')}".encode()).hexdigest()[:16]
    accept_url = f"{base}/bookings/{booking.id}/cleaner-response?action=accept&token={token}"
    decline_url = f"{base}/bookings/{booking.id}/cleaner-response?action=decline&token={token}"
    svc_label = SERVICES.get(booking.service_type, {}).get('label', booking.service_type.title())

    # Each cleaner's personal "My Day" job board link (auto-shared, no manual copy)
    if not staff.agreement_token:
        import secrets as _secrets
        staff.agreement_token = _secrets.token_urlsafe(32)
    myday_link = f"{base}/contractors/my-day/{staff.agreement_token}"

    from notifications import send_triggered_email, send_sms
    sent = False
    if staff.email:
        sent = send_triggered_email(
            trigger='cleaner_job_assigned',
            to_email=staff.email,
            to_name=staff.name,
            variables={
                'job_date': booking.preferred_date or 'TBD',
                'booking_time': booking.preferred_time or 'TBD',
                'service_type': svc_label,
                'job_address': f'{booking.address}, {booking.city}' if booking.address else 'See work order',
                'earnings': f'{earnings:.2f}',
                'beds': booking.bedrooms,
                'baths': booking.bathrooms,
                'myday_link': myday_link,
            }
        )
    booking.cleaner_notified_at = datetime.utcnow()
    db.session.flush()

    # Text the cleaner the job + tappable Accept/Decline links — fires even with no email on file
    sent_sms = False
    if staff.phone:
        try:
            ok, _ = send_sms(staff.phone,
                     f"New job {booking.preferred_date or 'TBD'} {booking.preferred_time or ''} — "
                     f"{booking.name}. You earn ${earnings:.0f}.\n"
                     f"Accept: {accept_url}\nDecline: {decline_url}")
            sent_sms = bool(ok)
        except Exception:
            pass

    if sent:
        return True
    if not staff.email:
        return sent_sms   # no email on file — at least the text may have gone out

    send_email(
        to_email=staff.email, to_name=staff.name,
        subject=f'New Job Assigned — {booking.preferred_date or "TBD"} · {branding.biz_name()}',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#b98a33">You have a new job! 🧹</h2>
  <p>Hi {staff.name.split()[0]}, a job has been assigned to you. Please confirm below.</p>
  <hr style="border:none;border-top:1px solid #e4dfef;margin:16px 0"/>
  <table style="width:100%;font-size:0.95rem;border-collapse:collapse">
    <tr><td style="padding:6px 0;color:#5f5878;width:40%">Date</td><td style="font-weight:700">{booking.preferred_date or 'TBD'}</td></tr>
    <tr><td style="padding:6px 0;color:#5f5878">Time</td><td style="font-weight:700">{booking.preferred_time or 'To be confirmed'}</td></tr>
    <tr><td style="padding:6px 0;color:#5f5878">Service</td><td style="font-weight:700">{svc_label}</td></tr>
    <tr><td style="padding:6px 0;color:#5f5878">Address</td><td style="font-weight:700">{booking.address or ''}{', ' + booking.city if booking.city else ''}</td></tr>
    <tr><td style="padding:6px 0;color:#5f5878">Your Earnings</td><td style="font-weight:700;color:#065f46;font-size:1.1rem">${earnings:.2f} <span style="font-size:0.8rem;color:#9a95ad">({pay_label})</span></td></tr>
  </table>
  <hr style="border:none;border-top:1px solid #e4dfef;margin:20px 0"/>
  <div style="display:flex;gap:12px;flex-wrap:wrap">
    <a href="{accept_url}" style="background:#065f46;color:#fff;padding:12px 24px;border-radius:999px;text-decoration:none;font-weight:700;font-size:0.95rem">✅ Accept Job</a>
    <a href="{decline_url}" style="background:#fee2e2;color:#991b1b;padding:12px 24px;border-radius:999px;text-decoration:none;font-weight:700;font-size:0.95rem">❌ Decline</a>
  </div>
  <p style="color:#9a95ad;font-size:12px;margin-top:20px">Questions? {branding.phone_line("Call us at ")} · {branding.biz_name()}</p>
</div>""",
    )
    return True
