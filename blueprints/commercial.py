"""Commercial Accounts — ongoing commercial cleaning clients (daycares, offices,
property managers…). Separate from residential Bookings. Accounts are created by
converting a 'Won' Prospect from Find Leads, or added by hand."""
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from entitlements import requires_plan
from auth import login_required
from extensions import db
from models import CommercialAccount, Prospect, User
import commercial_pricing as cpricing

commercial_bp = Blueprint('commercial', __name__, url_prefix='/commercial')

FREQUENCIES = ['nightly', 'weekly', 'biweekly', 'monthly', 'custom']
CATEGORIES = ['property_manager', 'apartment', 'daycare', 'medical_office',
              'office', 'realtor', 'airbnb', 'other']


def _money(v):
    try:
        return float(str(v).replace('$', '').replace(',', '').strip() or 0)
    except (ValueError, TypeError):
        return 0.0


def _int(v):
    try:
        return int(float(str(v).replace(',', '').strip() or 0))
    except (ValueError, TypeError):
        return None


def _agent_from():
    """Who gets credited: an explicit form choice, else the logged-in team member."""
    a = (request.form.get('agent') or '').strip()
    if a:
        return a
    if session.get('role') == 'team':
        return session.get('user_name')
    return None


def _tmpl_args(**extra):
    base = dict(frequencies=FREQUENCIES, categories=CATEGORIES,
                category_labels=Prospect.CATEGORY_LABELS,
                freq_labels=CommercialAccount.FREQ_LABELS,
                status_labels=CommercialAccount.STATUS_LABELS,
                pricing_config=cpricing.get_config())
    base.update(extra)
    return base


@commercial_bp.route('/')
@login_required
@requires_plan('commercial')
def index():
    status_filter = request.args.get('status', '')
    q = CommercialAccount.query.order_by(CommercialAccount.created_at.desc())
    if status_filter:
        q = q.filter_by(status=status_filter)
    accounts = q.all()
    active = CommercialAccount.query.filter_by(status='active').all()
    monthly_total = round(sum(a.monthly_value for a in active), 2)
    counts = {
        'all': CommercialAccount.query.count(),
        'active': CommercialAccount.query.filter_by(status='active').count(),
        'paused': CommercialAccount.query.filter_by(status='paused').count(),
        'lead': CommercialAccount.query.filter_by(status='lead').count(),
    }
    return render_template('admin/commercial.html', **_tmpl_args(
        accounts=accounts, counts=counts, status_filter=status_filter,
        monthly_total=monthly_total))


@commercial_bp.route('/calculator')
@login_required
def calculator():
    return render_template('admin/commercial_calculator.html', **_tmpl_args())


@commercial_bp.route('/quote.json')
@login_required
def quote_json():
    """The one place a commercial price is worked out.

    The calculators used to do the arithmetic themselves, in JavaScript, in two
    separate copies — and the copies had already drifted. One of them ignored
    scope add-ons entirely, so a medical office priced from the account form
    came out at office rates. The Python function that this file's docstring
    called "the pricing brain" was not called by anything at all, which meant
    every correction made to it changed nothing anybody was ever quoted.

    One implementation, on the server, asked over the wire. A price is also
    not a thing to compute in a place the customer's browser can edit.
    """
    from flask import jsonify
    return jsonify(cpricing.quote(
        request.args.get('sqft'),
        category=request.args.get('category') or 'office',
        frequency=request.args.get('frequency') or 'weekly',
        extras=request.args.getlist('extras'),
        drive_mins=request.args.get('drive_minutes'),
    ))


@commercial_bp.route('/new', methods=['POST'])
@login_required
def new():
    name = (request.form.get('business_name') or '').strip()
    if not name:
        flash('Please enter a business name.', 'error')
        return redirect(url_for('commercial.index'))
    a = CommercialAccount(
        business_name=name,
        contact_name=(request.form.get('contact_name') or '').strip(),
        email=(request.form.get('email') or '').strip(),
        phone=(request.form.get('phone') or '').strip(),
        address=(request.form.get('address') or '').strip(),
        city=(request.form.get('city') or '').strip(),
        square_footage=_int(request.form.get('square_footage')),
        drive_minutes=_int(request.form.get('drive_minutes')),
        category=request.form.get('category', 'office'),
        frequency=request.form.get('frequency', 'weekly'),
        billing_type=request.form.get('billing_type', 'monthly'),
        billing_amount=_money(request.form.get('billing_amount')),
        status=request.form.get('status', 'active'),
        notes=(request.form.get('notes') or '').strip(),
        source='manual',
        agent=_agent_from(),
    )
    db.session.add(a)
    db.session.commit()
    flash(f'Commercial account created for {name}. 🏢', 'success')
    return redirect(url_for('commercial.detail', account_id=a.id))


@commercial_bp.route('/convert/<int:prospect_id>', methods=['GET', 'POST'])
@login_required
def convert(prospect_id):
    p = Prospect.query.get_or_404(prospect_id)
    existing = CommercialAccount.query.filter_by(prospect_id=p.id).first()
    if existing:
        flash('That business is already a commercial account.', 'error')
        return redirect(url_for('commercial.detail', account_id=existing.id))
    if request.method == 'POST':
        a = CommercialAccount(
            business_name=p.business_name,
            contact_name=(request.form.get('contact_name') or '').strip(),
            email=(request.form.get('email') or '').strip(),
            phone=(request.form.get('phone') or p.phone or '').strip(),
            address=p.address or '',
            city=p.city or '',
            square_footage=_int(request.form.get('square_footage')),
            drive_minutes=_int(request.form.get('drive_minutes')),
            category=p.category or 'office',
            frequency=request.form.get('frequency', 'weekly'),
            billing_type=request.form.get('billing_type', 'monthly'),
            billing_amount=_money(request.form.get('billing_amount')),
            status='active',
            notes=(request.form.get('notes') or p.notes or '').strip(),
            source='find_leads',
            prospect_id=p.id,
            agent=_agent_from(),
        )
        p.status = 'won'
        db.session.add(a)
        db.session.commit()
        flash(f'🎉 {p.business_name} is now a commercial account!', 'success')
        return redirect(url_for('commercial.detail', account_id=a.id))
    return render_template('admin/commercial_convert.html', **_tmpl_args(p=p))


@commercial_bp.route('/<int:account_id>', methods=['GET', 'POST'])
@login_required
def detail(account_id):
    a = CommercialAccount.query.get_or_404(account_id)
    if request.method == 'POST':
        a.business_name = (request.form.get('business_name') or a.business_name).strip()
        a.contact_name = (request.form.get('contact_name') or '').strip()
        a.email = (request.form.get('email') or '').strip()
        a.phone = (request.form.get('phone') or '').strip()
        a.address = (request.form.get('address') or '').strip()
        a.city = (request.form.get('city') or '').strip()
        a.square_footage = _int(request.form.get('square_footage'))
        a.drive_minutes = _int(request.form.get('drive_minutes'))
        a.category = request.form.get('category', a.category)
        a.frequency = request.form.get('frequency', a.frequency)
        a.billing_type = request.form.get('billing_type', a.billing_type)
        a.billing_amount = _money(request.form.get('billing_amount'))
        a.status = request.form.get('status', a.status)
        a.notes = (request.form.get('notes') or '').strip()
        if 'agent' in request.form:
            a.agent = (request.form.get('agent') or '').strip() or None
        db.session.commit()
        flash('Account updated.', 'success')
        return redirect(url_for('commercial.detail', account_id=a.id))
    vas = User.query.filter_by(role='team').order_by(User.name).all()
    return render_template('admin/commercial_detail.html', **_tmpl_args(a=a, vas=vas))


@commercial_bp.route('/<int:account_id>/mark-first-paid', methods=['POST'])
@login_required
def mark_first_paid(account_id):
    a = CommercialAccount.query.get_or_404(account_id)
    if not a.first_paid_at:
        a.first_paid_at = datetime.utcnow()
    a.status = 'active'
    db.session.commit()
    flash('Marked paid — landing bonus + residuals now count toward commission. 💵', 'success')
    return redirect(url_for('commercial.detail', account_id=a.id))


@commercial_bp.route('/<int:account_id>/delete', methods=['POST'])
@login_required
def delete(account_id):
    a = CommercialAccount.query.get_or_404(account_id)
    db.session.delete(a)
    db.session.commit()
    flash('Commercial account removed.', 'success')
    return redirect(url_for('commercial.index'))
