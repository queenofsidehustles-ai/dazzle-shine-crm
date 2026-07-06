import calendar as cal_module
from datetime import date, timedelta, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth import login_required
from models import Booking, Client, Staff
from extensions import db
from pricing import FREQUENCY_LABELS

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
        booking.preferred_date = request.form.get('preferred_date', booking.preferred_date)
        booking.preferred_time = request.form.get('preferred_time', booking.preferred_time)
        booking.internal_notes = request.form.get('internal_notes', booking.internal_notes)
        booking.assigned_cleaner = request.form.get('assigned_cleaner', booking.assigned_cleaner)
        hours_raw = request.form.get('hours_worked', '').strip()
        booking.hours_worked = float(hours_raw) if hours_raw else booking.hours_worked

        if booking.status == 'completed' and old_status != 'completed':
            from datetime import datetime as _dt
            booking.completed_at = _dt.utcnow()
            _send_followup_email(booking)
            _send_rating_request(booking)
            _create_next_recurring(booking)

        # Notify cleaner when newly assigned (compare against old value, not new)
        new_cleaner = request.form.get('assigned_cleaner', '').strip()
        if new_cleaner and new_cleaner != old_cleaner:
            notified = _notify_cleaner(booking)
            # Auto-send the job checklist to the newly assigned cleaner
            try:
                from blueprints.workorders import create_and_send_workorder
                create_and_send_workorder(booking)
            except Exception:
                pass
            if notified:
                flash(f'Booking updated — notification + checklist sent to {new_cleaner}.', 'success')
            else:
                flash(f'Booking updated — ⚠️ no email on file for {new_cleaner}, notify them manually.', 'warning')
        else:
            flash('Booking updated.', 'success')

        db.session.commit()
        return redirect(url_for('bookings.detail', booking_id=booking_id))

    active_staff = Staff.query.filter_by(is_active=True).order_by(Staff.name).all()
    return render_template('admin/booking_detail.html', booking=booking, staff=active_staff)


@bookings_bp.route('/<int:booking_id>/charge-balance', methods=['POST'])
@login_required
def charge_balance(booking_id):
    from flask import jsonify
    from payment_service import charge_balance as do_charge
    booking = Booking.query.get_or_404(booking_id)
    ok, error = do_charge(booking)
    db.session.commit()
    return jsonify({'ok': ok, 'error': error})


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
    return render_template('admin/client_detail.html', client=client)


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
    if action == 'accept':
        booking.cleaner_response = 'accepted'
        booking.internal_notes = (booking.internal_notes or '') + f'\n[Cleaner accepted job on {datetime.utcnow().strftime("%b %d %Y")}]'
        db.session.commit()
        return '<h2 style="font-family:sans-serif;text-align:center;margin-top:60px;color:#065f46">✅ Job accepted! We\'ll see you on ' + (booking.preferred_date or 'the scheduled date') + '.</h2>'
    elif action == 'decline':
        booking.cleaner_response = 'declined'
        booking.assigned_cleaner = ''
        booking.internal_notes = (booking.internal_notes or '') + f'\n[Cleaner declined job on {datetime.utcnow().strftime("%b %d %Y")} — needs reassignment]'
        db.session.commit()
        return '<h2 style="font-family:sans-serif;text-align:center;margin-top:60px;color:#991b1b">Job declined. We\'ve been notified and will reassign. Thank you for letting us know.</h2>'
    return 'Unknown action.', 400


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
    from notifications import send_email
    send_email(
        to_email=booking.email,
        to_name=booking.name,
        subject='How did we do? — Dazzle & Shine Maids',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#b98a33">Thank you for choosing Dazzle &amp; Shine!</h2>
  <p>Hi {booking.name},</p>
  <p>Your cleaning is complete — we hope everything sparkles! ✨</p>
  <p>Your feedback means the world to us. If you have 60 seconds,
     we'd love a quick Google review:</p>
  <p style="margin:20px 0">
    <a href="https://g.page/r/dazzle-and-shine-maids/review"
       style="background:#d3a84f;color:#1a1225;padding:11px 22px;border-radius:999px;
              text-decoration:none;font-weight:700">Leave a Review</a>
  </p>
  <p>Ready to book your next cleaning?
     <a href="https://www.dazzleandshinemaids.com/#book" style="color:#b98a33">Book again here →</a>
  </p>
  <hr style="border:none;border-top:1px solid #e4dfef;margin:22px 0"/>
  <p style="color:#9a95ad;font-size:13px">Dazzle &amp; Shine Maids · Orlando, FL</p>
</div>""",
    )


def _create_next_recurring(booking):
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
    staff = Staff.query.filter(Staff.name.ilike(f'%{cleaner_name.split()[0]}%')).first() if cleaner_name else None
    if not staff or not staff.email:
        return False  # No email on file

    # Calculate cleaner earnings
    price = booking.price or 0
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

    from notifications import send_triggered_email
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
        }
    )
    booking.cleaner_notified_at = datetime.utcnow()
    db.session.flush()

    if sent:
        return True

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
