from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth import login_required
from models import Lead, Booking, Client, User
from extensions import db
from pricing import DEPOSIT_AMOUNT

leads_bp = Blueprint('leads', __name__, url_prefix='/leads')


@leads_bp.route('/')
@login_required
def index():
    status_filter = request.args.get('status', '')
    query = Lead.query.order_by(Lead.created_at.desc())
    if status_filter:
        query = query.filter_by(status=status_filter)
    leads = query.all()
    counts = {
        'all': Lead.query.count(),
        'new': Lead.query.filter_by(status='new').count(),
        'contacted': Lead.query.filter_by(status='contacted').count(),
        'converted': Lead.query.filter_by(status='converted').count(),
        'lost': Lead.query.filter_by(status='lost').count(),
    }
    return render_template('admin/leads.html', leads=leads, counts=counts, status_filter=status_filter)


@leads_bp.route('/<int:lead_id>', methods=['GET', 'POST'])
@login_required
def detail(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    if request.method == 'POST':
        lead.status = request.form.get('status', lead.status)
        lead.notes = request.form.get('notes', lead.notes)
        if 'agent' in request.form:
            lead.agent = (request.form.get('agent') or '').strip() or None
        db.session.commit()
        flash('Lead updated.', 'success')
        return redirect(url_for('leads.detail', lead_id=lead_id))
    vas = User.query.filter_by(role='team').order_by(User.name).all()
    return render_template('admin/lead_detail.html', lead=lead, vas=vas)


@leads_bp.route('/<int:lead_id>/convert', methods=['POST'])
@login_required
def convert(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    client = Client.query.filter_by(email=lead.email.lower()).first()
    if not client:
        client = Client(
            name=lead.name, email=lead.email.lower(),
            phone=lead.phone or '', address=lead.address or '',
            city=lead.city or '', zip_code=lead.zip_code or '',
        )
        db.session.add(client)
        db.session.flush()
    booking = Booking(
        client_id=client.id,
        service_type=lead.service_type or '',
        bedrooms=lead.bedrooms or '',
        bathrooms=lead.bathrooms or '',
        extras=lead.extras or '',
        frequency=lead.frequency or 'one_time',
        name=lead.name, email=lead.email,
        phone=lead.phone or '', address=lead.address or '',
        city=lead.city or '', zip_code=lead.zip_code or '',
        price=lead.quoted_price,
        balance_due=max(0, (lead.quoted_price or 0) - DEPOSIT_AMOUNT),
        status='pending',
        source=lead.source,
        agent=lead.agent,
    )
    db.session.add(booking)
    lead.status = 'converted'
    db.session.commit()
    flash('Lead converted to booking!', 'success')
    return redirect(url_for('bookings.detail', booking_id=booking.id))


@leads_bp.route('/<int:lead_id>/delete', methods=['POST'])
@login_required
def delete(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    db.session.delete(lead)
    db.session.commit()
    flash('Lead deleted.', 'success')
    return redirect(url_for('leads.index'))
