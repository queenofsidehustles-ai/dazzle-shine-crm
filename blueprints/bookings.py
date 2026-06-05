from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth import login_required
from models import Booking, Client
from extensions import db

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


@bookings_bp.route('/<int:booking_id>', methods=['GET', 'POST'])
@login_required
def detail(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if request.method == 'POST':
        booking.status = request.form.get('status', booking.status)
        booking.price = request.form.get('price') or None
        booking.preferred_date = request.form.get('preferred_date', booking.preferred_date)
        booking.preferred_time = request.form.get('preferred_time', booking.preferred_time)
        booking.internal_notes = request.form.get('internal_notes', booking.internal_notes)
        db.session.commit()
        flash('Booking updated.', 'success')
        return redirect(url_for('bookings.detail', booking_id=booking_id))
    return render_template('admin/booking_detail.html', booking=booking)


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
