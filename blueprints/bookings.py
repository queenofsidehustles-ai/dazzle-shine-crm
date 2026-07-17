import calendar as cal_module
from datetime import date, timedelta, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from auth import login_required
from models import Booking, Client, Staff
from extensions import db
from pricing import FREQUENCY_LABELS
import recurring

bookings_bp = Blueprint('bookings', __name__, url_prefix='/bookings')


@bookings_bp.route('/')
@login_required
def index():
    status_filter = request.args.get('status', '')
    query = Booking.query.order_by(Booking.created_at.desc())
    if status_filter:
        query = query.filter_by(status=status_filter)
    bookings = query.all()
    counts = {
        'all': Booking.query.count(),
        'pending': Booking.query.filter_by(status='pending').count(),
        'confirmed': Booking.query.filter_by(status='confirmed').count(),
        'completed': Booking.query.filter_by(status='completed').count(),
        'cancelled': Booking.query.filter_by(status='cancelled').count(),
    }
    return render_template('admin/bookings.html', bookings=bookings, counts=counts, status_filter=status_filter)


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
        fee = float(fee_raw) if fee_raw != '' else float(get_lead_fee())
    except ValueError:
        fee = float(get_lead_fee())

    return jsonify({'cleaning': round(cleaning or 0, 2), 'lead_fee': round(fee, 2),
                    'total': round((cleaning or 0) + fee, 2)})


@bookings_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    """Create a booking by hand — for customers who book by phone/text/in person."""
    from pricing import calculate_price, SERVICE_LABELS, EXTRAS, get_lead_fee
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

        # Lead fee — added to the customer total, excluded from contractor pay.
        fee_raw = request.form.get('lead_fee', '').strip().replace('$', '')
        try:
            lead_fee = float(fee_raw) if fee_raw != '' else float(get_lead_fee())
        except ValueError:
            lead_fee = float(get_lead_fee())
        price = round((cleaning or 0) + lead_fee, 2)   # what the customer pays

        b = Booking(
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

        # Payment: send a deposit/full link now, else just a booking confirmation.
        pay_option = request.form.get('payment_option', 'none')
        extra = ''
        try:
            if pay_option in ('deposit', 'full') and (b.email or b.phone):
                from blueprints.payments import send_payment_link
                send_payment_link(b, kind=pay_option)
                extra = ' Payment link sent 💳'
            elif request.form.get('notify_customer') and (b.email or b.phone):
                _send_booking_confirmation(b)
                extra = ' Customer confirmation sent 📩'
        except Exception:
            extra = ' (⚠️ a customer message failed to send)'

        flash(f'Booking created ✅ — now assign a cleaner below to text + email them the job.{extra}', 'success')
        return redirect(url_for('bookings.detail', booking_id=b.id))

    from pricing import FREQUENCY_LABELS as _FREQ
    return render_template('admin/booking_new.html',
                           service_labels=SERVICE_LABELS, extras=EXTRAS, frequency_labels=_FREQ,
                           default_lead_fee=get_lead_fee())


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
        booking.price = request.form.get('price') or None
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
    pay_url = payment_link_url(booking, 'full')          # ensures pay_token exists
    recurring_upcoming = recurring.upcoming_count(booking.recurring_group) if booking.recurring_group else 0
    return render_template('admin/booking_detail.html', booking=booking, staff=active_staff,
                           pay_url=pay_url, due=amount_due(booking),
                           recurring_upcoming=recurring_upcoming)


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
        html = _wrap_html(message, 'Dazzle & Shine Maids')
        ok, detail = send_email(to_email=to_email, to_name=(booking.name or 'there'),
                                subject=subject, html=html)
        if ok:
            flash(f'Email sent to {booking.email} ✅', 'success')
            return redirect(url_for('bookings.detail', booking_id=booking_id))
        flash(f'Could not send the email — {detail}', 'warning')
        return redirect(url_for('bookings.email_customer', booking_id=booking_id))
    return render_template('admin/email_customer.html', booking=booking)


@bookings_bp.route('/<int:booking_id>/notify-pay', methods=['POST'])
@login_required
def notify_pay(booking_id):
    """Text the assigned cleaner their current (corrected) pay for this job."""
    import secrets as _secrets
    from models import BusinessSetting
    from notifications import send_sms
    from translate import translate
    b = Booking.query.get_or_404(booking_id)
    name = b.assigned_cleaner or ''
    s = Staff.query.filter(db.func.lower(Staff.name) == name.lower()).first() if name else None
    if not s or not s.phone:
        flash('No assigned cleaner with a phone number to notify.', 'warning')
        return redirect(url_for('bookings.detail', booking_id=booking_id))
    if not s.agreement_token:
        s.agreement_token = _secrets.token_urlsafe(32)
        db.session.commit()
    pay = s.calc_pay(job_price=b.commissionable_price, hours_worked=b.hours_worked or 0)
    biz = BusinessSetting.get('business_name', 'Dazzle & Shine Maids')
    base = 'https://dazzle-shine-crm-production.up.railway.app'
    myday = f"{base}/contractors/my-day/{s.agreement_token}"
    first = (s.name or '').split()[0]
    msg = (f"Hi {first}! Quick update on your {b.preferred_date or ''} job — your pay is "
           f"${pay:.2f}. Full details here: {myday} — {biz}")
    if (s.language or 'en') == 'es':
        msg = translate(msg, target='es')
    ok, detail = send_sms(s.phone, msg)
    flash(f'Updated pay (${pay:.2f}) sent to {s.name}.' if ok else 'Could not send: ' + detail,
          'success' if ok else 'warning')
    return redirect(url_for('bookings.detail', booking_id=booking_id))


@bookings_bp.route('/<int:booking_id>/broadcast', methods=['POST'])
@login_required
def broadcast(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    from blueprints.claims import broadcast_job
    n = broadcast_job(booking)
    flash(f'📣 Offered to {n} cleaner(s) — first to claim it gets it.', 'success')
    return redirect(url_for('bookings.detail', booking_id=booking_id))


@bookings_bp.route('/<int:booking_id>/mark-paid', methods=['POST'])
@login_required
def mark_paid_route(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    method = request.form.get('method', 'cash')
    from blueprints.payments import mark_paid
    try:
        mark_paid(booking, method=method)
        flash(f'Marked as paid ✅ ({method}).', 'success')
    except Exception:
        db.session.rollback()
        flash('Could not mark as paid.', 'error')
    return redirect(url_for('bookings.detail', booking_id=booking_id))


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
    invoicing.issue(booking)
    payment_link_url(booking, 'full')  # ensure pay_token exists
    biz = BusinessSetting.get('business_name') or 'Dazzle & Shine Maids'
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


@bookings_bp.route('/<int:booking_id>/schedule-recurring', methods=['POST'])
@login_required
def schedule_recurring(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.frequency in ('one_time', None) or not booking.preferred_date:
        flash('Set a repeat frequency and a date first, then schedule the plan.', 'error')
        return redirect(url_for('bookings.detail', booking_id=booking_id))
    n = recurring.generate_series(booking, weeks_ahead=12)
    flash(f'📅 Recurring plan set — {n} future visit{"s" if n != 1 else ""} added to your calendar.', 'success')
    return redirect(url_for('bookings.detail', booking_id=booking_id))


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
    return render_template('admin/clients.html', clients=all_clients)


@bookings_bp.route('/clients/<int:client_id>')
@login_required
def client_detail(client_id):
    client = Client.query.get_or_404(client_id)
    from blueprints.portal import ensure_portal_token
    from blueprints.payments import CRM_BASE
    portal_url = f"{CRM_BASE}/portal/{ensure_portal_token(client)}"
    return render_template('admin/client_detail.html', client=client, portal_url=portal_url)


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
                   or os.environ.get('NOTIFY_EMAIL', 'dazzleandshinemaids@gmail.com'))
    owner_phone = BusinessSetting.get('phone') or os.environ.get('OWNER_PHONE')
    base = 'https://dazzle-shine-crm-production.up.railway.app'
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
        send_email(to_email=owner_email, to_name='Dazzle & Shine', subject=subject,
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
    from notifications import send_email
    base = 'https://dazzle-shine-crm-production.up.railway.app'
    stars_html = ''.join(
        f'<a href="{base}/rate/{token}/{i}" style="font-size:2.2rem;text-decoration:none;margin:0 4px">⭐</a>'
        for i in range(1, 6)
    )
    send_email(
        to_email=booking.email, to_name=booking.name,
        subject='How was your cleaning? — Dazzle & Shine Maids',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333;text-align:center">
  <h2 style="color:#b98a33;margin-bottom:6px">How did we do?</h2>
  <p style="color:#5f5878;margin-bottom:24px">Hi {booking.name.split()[0]}, your cleaning is complete! Tap a star to rate your experience:</p>
  <div style="margin:20px 0">{stars_html}</div>
  <p style="font-size:0.82rem;color:#9a95ad">Takes 5 seconds. Your feedback helps us improve.</p>
  <hr style="border:none;border-top:1px solid #e4dfef;margin:20px 0"/>
  <p style="color:#9a95ad;font-size:13px">Dazzle &amp; Shine Maids · Orlando, FL</p>
</div>""",
    )


def _send_followup_email(booking):
    # A pure thank-you. It intentionally does NOT link to Google reviews —
    # the ONLY path to a public review is the star-rating email, which shows
    # the Google link solely to customers who first tap 4-5 stars. This keeps
    # unhappy customers from ever being handed a public-review link.
    from notifications import send_email
    send_email(
        to_email=booking.email,
        to_name=booking.name,
        subject='Thank you from Dazzle & Shine Maids',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#b98a33">Thank you for choosing Dazzle &amp; Shine!</h2>
  <p>Hi {booking.name},</p>
  <p>Your cleaning is complete — we hope everything sparkles! ✨</p>
  <p>It was a pleasure serving you. If there's anything at all we can make
     better, just reply to this email — we're always here to help.</p>
  <p>Ready to book your next cleaning?
     <a href="https://www.dazzleandshinemaids.com/#book" style="color:#b98a33">Book again here →</a>
  </p>
  <hr style="border:none;border-top:1px solid #e4dfef;margin:22px 0"/>
  <p style="color:#9a95ad;font-size:13px">Dazzle &amp; Shine Maids · Orlando, FL</p>
</div>""",
    )


def _send_booking_confirmation(booking):
    """Confirm a hand-created booking to the customer via email + text.
    No deposit language — a simple 'you're booked' note. Best-effort."""
    from notifications import send_email, send_sms
    from models import BusinessSetting
    biz = BusinessSetting.get('business_name', 'Dazzle & Shine Maids')
    first = (booking.name or 'there').split()[0]
    date_text = booking.preferred_date or 'the scheduled date'
    time_text = booking.preferred_time or ''
    when = f"{date_text}{(' at ' + time_text) if time_text else ''}"
    price_text = f"${booking.price:.2f}" if booking.price else ''

    if booking.email:
        addr = ', '.join([p for p in [booking.address, booking.city, booking.zip_code] if p])
        send_email(
            to_email=booking.email, to_name=booking.name,
            subject=f"You're booked with {biz}! ✨",
            html=f"""
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
</div>""",
        )

    if booking.phone:
        msg = (f"Hi {first}! ✨ Your {biz} cleaning is booked for {when}."
               + (f" Total {price_text}." if price_text else "")
               + " Reply here with any questions. Reply STOP to opt out.")
        try:
            send_sms(booking.phone, msg)
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

    # Calculate cleaner earnings (on the cleaning price — excludes the lead fee)
    price = booking.commissionable_price
    if staff.pay_type == 'percent':
        earnings = round(price * staff.pay_rate / 100, 2)
        pay_label = f'{staff.pay_rate:.0f}% of ${price:.2f}'
    else:
        hours = booking.hours_worked or 0
        earnings = round(hours * staff.pay_rate, 2)
        pay_label = f'{hours}h × ${staff.pay_rate:.2f}/hr'

    base = 'https://dazzle-shine-crm-production.up.railway.app'
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
        subject=f'New Job Assigned — {booking.preferred_date or "TBD"} · Dazzle & Shine',
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
  <p style="color:#9a95ad;font-size:12px;margin-top:20px">Questions? Call Monica at (689) 999-0194 · Dazzle &amp; Shine Maids</p>
</div>""",
    )
    return True
