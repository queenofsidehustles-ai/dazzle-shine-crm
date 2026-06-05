from flask import Blueprint, render_template, request, session, redirect, url_for
from auth import login_required, check_credentials
from models import Booking, Client
from extensions import db
from datetime import datetime, date

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
