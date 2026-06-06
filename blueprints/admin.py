import json
from flask import Blueprint, render_template, request, session, redirect, url_for
from auth import login_required, check_credentials
from models import Booking, Client, Lead
from extensions import db
from sqlalchemy import func
from datetime import datetime, date, timedelta

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/')
@login_required
def dashboard():
    today = date.today().isoformat()
    total_bookings = Booking.query.count()
    pending = Booking.query.filter_by(status='pending').count()
    confirmed = Booking.query.filter_by(status='confirmed').count()
    completed = Booking.query.filter_by(status='completed').count()
    total_clients = Client.query.count()
    today_bookings = Booking.query.filter_by(preferred_date=today).all()
    recent = Booking.query.order_by(Booking.created_at.desc()).limit(8).all()
    return render_template(
        'admin/dashboard.html',
        total_bookings=total_bookings,
        pending=pending,
        confirmed=confirmed,
        completed=completed,
        total_clients=total_clients,
        today_bookings=today_bookings,
        recent=recent,
    )


@admin_bp.route('/reports')
@login_required
def reports():
    today = date.today()

    # Build last 6 months list
    monthly_data = []
    for i in range(5, -1, -1):
        year, month = today.year, today.month - i
        while month <= 0:
            month += 12
            year -= 1
        m_start = datetime(year, month, 1)
        m_end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
        rev = db.session.query(func.sum(Booking.price)).filter(
            Booking.status.in_(['completed', 'confirmed']),
            Booking.created_at >= m_start,
            Booking.created_at < m_end,
        ).scalar() or 0
        monthly_data.append({'month': m_start.strftime('%b %Y'), 'revenue': round(float(rev), 2)})

    this_month_start = datetime(today.year, today.month, 1)
    last_month_start = datetime(today.year, today.month - 1, 1) if today.month > 1 else datetime(today.year - 1, 12, 1)
    this_year_start = datetime(today.year, 1, 1)

    revenue_this_month = db.session.query(func.sum(Booking.price)).filter(
        Booking.status.in_(['completed', 'confirmed']),
        Booking.created_at >= this_month_start,
    ).scalar() or 0

    revenue_last_month = db.session.query(func.sum(Booking.price)).filter(
        Booking.status.in_(['completed', 'confirmed']),
        Booking.created_at >= last_month_start,
        Booking.created_at < this_month_start,
    ).scalar() or 0

    revenue_ytd = db.session.query(func.sum(Booking.price)).filter(
        Booking.status.in_(['completed', 'confirmed']),
        Booking.created_at >= this_year_start,
    ).scalar() or 0

    balance_outstanding = db.session.query(func.sum(Booking.balance_due)).filter(
        Booking.balance_collected == False,
        Booking.status.in_(['confirmed', 'completed', 'pending']),
    ).scalar() or 0

    deposits_collected = db.session.query(func.count(Booking.id)).filter(
        Booking.deposit_paid == True,
    ).scalar() or 0

    # Top services
    service_rows = db.session.query(
        Booking.service_type,
        func.count(Booking.id).label('jobs'),
        func.sum(Booking.price).label('revenue'),
    ).filter(Booking.status.in_(['completed', 'confirmed'])).group_by(Booking.service_type).all()

    service_data = sorted([
        {'type': Booking.SERVICE_LABELS.get(r.service_type, r.service_type.title()),
         'jobs': r.jobs, 'revenue': round(float(r.revenue or 0), 2)}
        for r in service_rows
    ], key=lambda x: x['revenue'], reverse=True)

    # Leads funnel
    leads_total = Lead.query.count()
    leads_converted = Lead.query.filter_by(status='converted').count()
    leads_this_month = Lead.query.filter(Lead.created_at >= this_month_start).count()
    conversion_rate = round(leads_converted / leads_total * 100, 1) if leads_total else 0

    # Upcoming 14 days
    today_str = today.isoformat()
    end_str = (today + timedelta(days=14)).isoformat()
    upcoming = Booking.query.filter(
        Booking.preferred_date >= today_str,
        Booking.preferred_date <= end_str,
        Booking.status.in_(['confirmed', 'pending']),
    ).order_by(Booking.preferred_date).all()

    return render_template('admin/reports.html',
        monthly_labels=json.dumps([d['month'] for d in monthly_data]),
        monthly_values=json.dumps([d['revenue'] for d in monthly_data]),
        revenue_this_month=round(float(revenue_this_month), 2),
        revenue_last_month=round(float(revenue_last_month), 2),
        revenue_ytd=round(float(revenue_ytd), 2),
        balance_outstanding=round(float(balance_outstanding), 2),
        deposits_collected=deposits_collected,
        service_data=service_data,
        leads_total=leads_total,
        leads_converted=leads_converted,
        leads_this_month=leads_this_month,
        conversion_rate=conversion_rate,
        upcoming=upcoming,
    )


@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if check_credentials(request.form['username'], request.form['password']):
            session['logged_in'] = True
            return redirect(url_for('admin.dashboard'))
        error = 'Wrong username or password.'
    return render_template('admin/login.html', error=error)


@admin_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('admin.login'))
