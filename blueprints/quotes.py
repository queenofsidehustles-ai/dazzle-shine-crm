import os
import secrets
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from auth import login_required
from models import CommercialQuote
from extensions import db
from notifications import send_email

quotes_bp = Blueprint('quotes', __name__, url_prefix='/quotes')

PROPERTY_TYPES = ['Apartment Complex', 'Student Housing', 'Office Building',
                  'Retail / Commercial', 'Property Management Portfolio', 'Other']

SERVICES = [
    'Common Area Cleaning', 'Individual Unit Cleaning', 'Office Cleaning',
    'Restroom Sanitation', 'Lobby & Hallway Cleaning', 'Parking Garage',
    'Window Cleaning', 'Carpet Cleaning', 'Move-Out / Turnover Cleaning',
    'Deep Cleaning', 'Post-Construction Cleanup',
]

FREQUENCIES = [
    ('daily', 'Daily'), ('weekly', 'Weekly'), ('biweekly', 'Bi-Weekly'),
    ('monthly', 'Monthly'), ('as_needed', 'As Needed / One-Time'),
]

CONTRACT_TERMS = [
    ('month_to_month', 'Month-to-Month'),
    ('3_months', '3-Month Contract'),
    ('6_months', '6-Month Contract'),
    ('annual', 'Annual Contract'),
]


@quotes_bp.route('/')
@login_required
def index():
    status_filter = request.args.get('status', '')
    query = CommercialQuote.query.order_by(CommercialQuote.created_at.desc())
    if status_filter:
        query = query.filter_by(status=status_filter)
    all_quotes = query.all()
    counts = {
        'all': CommercialQuote.query.count(),
        'draft': CommercialQuote.query.filter_by(status='draft').count(),
        'sent': CommercialQuote.query.filter_by(status='sent').count(),
        'accepted': CommercialQuote.query.filter_by(status='accepted').count(),
        'declined': CommercialQuote.query.filter_by(status='declined').count(),
    }
    return render_template('admin/quotes.html', quotes=all_quotes,
                           counts=counts, status_filter=status_filter)


@quotes_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    if request.method == 'POST':
        services_selected = request.form.getlist('services')
        q = CommercialQuote(
            company=request.form.get('company', '').strip(),
            contact_name=request.form.get('contact_name', '').strip(),
            email=request.form.get('email', '').strip(),
            phone=request.form.get('phone', '').strip(),
            property_type=request.form.get('property_type', ''),
            property_address=request.form.get('property_address', '').strip(),
            units=request.form.get('units', '').strip(),
            sqft=request.form.get('sqft', '').strip(),
            services=', '.join(services_selected),
            frequency=request.form.get('frequency', ''),
            contract_term=request.form.get('contract_term', ''),
            price_per_visit=request.form.get('price_per_visit') or None,
            monthly_price=request.form.get('monthly_price') or None,
            scope_notes=request.form.get('scope_notes', '').strip(),
            token=secrets.token_urlsafe(32),
            status='draft',
        )
        db.session.add(q)
        db.session.commit()
        flash('Quote created!', 'success')
        return redirect(url_for('quotes.detail', quote_id=q.id))
    return render_template('admin/quote_form.html', quote=None,
                           property_types=PROPERTY_TYPES, services=SERVICES,
                           frequencies=FREQUENCIES, contract_terms=CONTRACT_TERMS)


@quotes_bp.route('/<int:quote_id>', methods=['GET', 'POST'])
@login_required
def detail(quote_id):
    q = CommercialQuote.query.get_or_404(quote_id)
    if request.method == 'POST':
        services_selected = request.form.getlist('services')
        q.company = request.form.get('company', q.company).strip()
        q.contact_name = request.form.get('contact_name', q.contact_name).strip()
        q.email = request.form.get('email', q.email).strip()
        q.phone = request.form.get('phone', q.phone).strip()
        q.property_type = request.form.get('property_type', q.property_type)
        q.property_address = request.form.get('property_address', q.property_address).strip()
        q.units = request.form.get('units', q.units).strip()
        q.sqft = request.form.get('sqft', q.sqft).strip()
        q.services = ', '.join(services_selected)
        q.frequency = request.form.get('frequency', q.frequency)
        q.contract_term = request.form.get('contract_term', q.contract_term)
        q.price_per_visit = request.form.get('price_per_visit') or None
        q.monthly_price = request.form.get('monthly_price') or None
        q.scope_notes = request.form.get('scope_notes', q.scope_notes).strip()
        db.session.commit()
        flash('Quote updated.', 'success')
        return redirect(url_for('quotes.detail', quote_id=quote_id))

    selected_services = [s.strip() for s in (q.services or '').split(',') if s.strip()]
    return render_template('admin/quote_form.html', quote=q,
                           property_types=PROPERTY_TYPES, services=SERVICES,
                           frequencies=FREQUENCIES, contract_terms=CONTRACT_TERMS,
                           selected_services=selected_services)


@quotes_bp.route('/<int:quote_id>/send', methods=['POST'])
@login_required
def send_quote(quote_id):
    q = CommercialQuote.query.get_or_404(quote_id)
    crm_url = request.host_url.rstrip('/')
    quote_url = f"{crm_url}/quotes/view/{q.token}"

    freq_label = dict(FREQUENCIES).get(q.frequency, q.frequency)
    term_label = dict(CONTRACT_TERMS).get(q.contract_term, q.contract_term)
    services_html = ''.join(f'<li>{s}</li>' for s in (q.services or '').split(',') if s.strip())
    price_html = ''
    if q.price_per_visit:
        price_html += f"<p><strong>Price per visit:</strong> ${float(q.price_per_visit):,.2f}</p>"
    if q.monthly_price:
        price_html += f"<p><strong>Monthly total:</strong> ${float(q.monthly_price):,.2f}</p>"

    ok, detail = send_email(
        to_email=q.email, to_name=q.contact_name,
        subject=f'Cleaning Services Proposal — Dazzle & Shine Maids',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;color:#1f1333">
  <div style="background:#1f1333;padding:24px;text-align:center;border-radius:12px 12px 0 0">
    <h1 style="font-family:Georgia,serif;color:#d3a84f;margin:0;font-size:1.8rem">Dazzle &amp; Shine Maids</h1>
    <p style="color:rgba(255,255,255,0.6);margin:4px 0 0;font-size:0.85rem;letter-spacing:0.15em;text-transform:uppercase">Professional Cleaning Proposal</p>
  </div>
  <div style="padding:30px;background:#fff;border:1px solid #e4dfef;border-top:none;border-radius:0 0 12px 12px">
    <p>Dear {q.contact_name},</p>
    <p>Thank you for your interest in Dazzle &amp; Shine Maids. Please find your customized cleaning proposal below.</p>
    <hr style="border:none;border-top:1px solid #e4dfef;margin:20px 0"/>
    <h3 style="color:#b98a33;margin-bottom:10px">Property Details</h3>
    <p><strong>Property:</strong> {q.company}</p>
    <p><strong>Type:</strong> {q.property_type}</p>
    <p><strong>Address:</strong> {q.property_address}</p>
    {'<p><strong>Units:</strong> ' + q.units + '</p>' if q.units else ''}
    {'<p><strong>Square Footage:</strong> ' + q.sqft + ' sq ft</p>' if q.sqft else ''}
    <h3 style="color:#b98a33;margin:20px 0 10px">Services Included</h3>
    <ul style="padding-left:20px;line-height:2">{services_html}</ul>
    <h3 style="color:#b98a33;margin:20px 0 10px">Schedule &amp; Pricing</h3>
    <p><strong>Frequency:</strong> {freq_label}</p>
    <p><strong>Contract Term:</strong> {term_label}</p>
    {price_html}
    {'<div style="background:#f6f5fb;border-radius:9px;padding:14px;margin-top:10px"><strong>Scope of Work:</strong><br>' + q.scope_notes + '</div>' if q.scope_notes else ''}
    <hr style="border:none;border-top:1px solid #e4dfef;margin:24px 0"/>
    <p style="text-align:center;font-size:1rem">Ready to move forward?</p>
    <div style="text-align:center;margin:20px 0">
      <a href="{quote_url}" style="background:#d3a84f;color:#1a1225;padding:14px 32px;border-radius:999px;text-decoration:none;font-weight:700;font-size:1rem">Review &amp; Accept Quote →</a>
    </div>
    <p style="font-size:0.85rem;color:#9a95ad;text-align:center">You can review the full proposal, accept, or decline at the link above.</p>
    <hr style="border:none;border-top:1px solid #e4dfef;margin:20px 0"/>
    <p style="font-size:0.85rem;color:#9a95ad">Questions? Contact us at (689) 999-0194 or reply to this email.<br>Dazzle &amp; Shine Maids · Orlando, FL</p>
  </div>
</div>""",
    )
    if not ok:
        flash(f"Quote could NOT be emailed to {q.email}. {detail}", 'error')
        return redirect(url_for('quotes.detail', quote_id=q.id))

    q.status = 'sent'
    q.sent_at = datetime.utcnow()
    db.session.commit()

    # Send the owner a copy so there's always a record in your inbox
    owner_email = os.environ.get('NOTIFY_EMAIL') or os.environ.get('OWNER_EMAIL', 'dazzleandshinemaids@gmail.com')
    if owner_email and owner_email.lower() != (q.email or '').lower():
        try:
            send_email(
                to_email=owner_email, to_name='Dazzle & Shine Maids',
                subject=f'Copy: quote sent to {q.company} ({q.contact_name})',
                html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#b98a33">Quote Sent — Your Copy</h2>
  <p>A commercial proposal was just emailed to <strong>{q.contact_name}</strong> at {q.email}.</p>
  <p><strong>Company:</strong> {q.company}<br>
     <strong>Monthly:</strong> ${float(q.monthly_price or 0):,.2f}</p>
  <p><a href="{quote_url}" style="color:#d3a84f;font-weight:700">View the proposal they received →</a></p>
</div>""",
            )
        except Exception:
            pass

    flash(f'Quote sent to {q.email}! ({detail}) A copy was also sent to you.', 'success')
    return redirect(url_for('quotes.index'))


@quotes_bp.route('/<int:quote_id>/delete', methods=['POST'])
@login_required
def delete(quote_id):
    q = CommercialQuote.query.get_or_404(quote_id)
    db.session.delete(q)
    db.session.commit()
    flash('Quote deleted.', 'success')
    return redirect(url_for('quotes.index'))


# ── Public accept / decline (no login) ────────────────────────────────────────

@quotes_bp.route('/view/<token>')
def view(token):
    q = CommercialQuote.query.filter_by(token=token).first_or_404()
    # Track the first time the contact opens it — but not the owner's own preview
    is_preview = request.args.get('preview') == '1'
    if not is_preview and q.status == 'sent' and not q.viewed_at:
        q.viewed_at = datetime.utcnow()
        db.session.commit()
    freq_label = dict(FREQUENCIES).get(q.frequency, q.frequency)
    term_label = dict(CONTRACT_TERMS).get(q.contract_term, q.contract_term)
    services_list = [s.strip() for s in (q.services or '').split(',') if s.strip()]
    return render_template('public/quote_view.html', q=q,
                           freq_label=freq_label, term_label=term_label,
                           services_list=services_list)


@quotes_bp.route('/view/<token>/accept', methods=['POST'])
def accept(token):
    q = CommercialQuote.query.filter_by(token=token).first_or_404()
    if q.status not in ('sent', 'draft'):
        return redirect(url_for('quotes.view', token=token))
    q.status = 'accepted'
    try:
        q.responded_at = datetime.utcnow()
    except Exception:
        pass
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        db.session.execute(__import__('sqlalchemy').text(
            "UPDATE commercial_quote SET status='accepted' WHERE token=:t"
        ), {'t': token})
        db.session.commit()
    notify_email = __import__('os').environ.get('NOTIFY_EMAIL', 'dazzleandshinemaids@gmail.com')
    send_email(
        to_email=notify_email, to_name='Dazzle & Shine Maids',
        from_name='Dazzle & Shine Quotes',
        subject=f'QUOTE ACCEPTED: {q.company} — ${float(q.monthly_price or 0):,.2f}/mo',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#065f46">Quote Accepted ✓</h2>
  <p><strong>{q.contact_name}</strong> at <strong>{q.company}</strong> accepted your proposal.</p>
  <p><strong>Email:</strong> {q.email} &nbsp; <strong>Phone:</strong> {q.phone}</p>
  <p><strong>Property:</strong> {q.property_address}</p>
  {'<p><strong>Monthly value:</strong> $' + f'{float(q.monthly_price):,.2f}' + '/mo</p>' if q.monthly_price else ''}
  <p>Follow up to schedule the first service and collect contract details.</p>
</div>""",
    )
    return render_template('public/quote_response.html', accepted=True, q=q)


@quotes_bp.route('/view/<token>/decline', methods=['POST'])
def decline(token):
    q = CommercialQuote.query.filter_by(token=token).first_or_404()
    if q.status not in ('sent', 'draft'):
        return redirect(url_for('quotes.view', token=token))
    q.status = 'declined'
    try:
        q.responded_at = datetime.utcnow()
    except Exception:
        pass
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        db.session.execute(__import__('sqlalchemy').text(
            "UPDATE commercial_quote SET status='declined' WHERE token=:t"
        ), {'t': token})
        db.session.commit()
    notify_email = __import__('os').environ.get('NOTIFY_EMAIL', 'dazzleandshinemaids@gmail.com')
    send_email(
        to_email=notify_email, to_name='Dazzle & Shine Maids',
        from_name='Dazzle & Shine Quotes',
        subject=f'Quote declined: {q.company}',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#991b1b">Quote Declined</h2>
  <p><strong>{q.contact_name}</strong> at <strong>{q.company}</strong> declined your proposal.</p>
  <p>Consider following up to understand their concerns or offer an adjusted price.</p>
</div>""",
    )
    return render_template('public/quote_response.html', accepted=False, q=q)
