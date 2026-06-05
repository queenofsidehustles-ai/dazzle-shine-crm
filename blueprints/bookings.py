import calendar as cal_module
from datetime import date, timedelta
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
        booking.status = request.form.get('status', booking.status)
        booking.price = request.form.get('price') or None
        booking.preferred_date = request.form.get('preferred_date', booking.preferred_date)
        booking.preferred_time = request.form.get('preferred_time', booking.preferred_time)
        booking.internal_notes = request.form.get('internal_notes', booking.internal_notes)
        booking.assigned_cleaner = request.form.get('assigned_cleaner', booking.assigned_cleaner)

        if booking.status == 'completed' and old_status != 'completed':
            _send_followup_email(booking)
            _create_next_recurring(booking)

        db.session.commit()
        flash('Booking updated.', 'success')
        return redirect(url_for('bookings.detail', booking_id=booking_id))

    active_staff = Staff.query.filter_by(is_active=True).order_by(Staff.name).all()
    return render_template('admin/booking_detail.html', booking=booking, staff=active_staff)


@bookings_bp.route('/<int:booking_id>/delete', methods=['POST'])
@login_required
def delete(booking_id):
    booking = Booking.query.get_or_404(booking_id)
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


# ── Helpers ────────────────────────────────────────────────────────────────────

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
