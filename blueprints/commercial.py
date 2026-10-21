"""Commercial Accounts — ongoing commercial cleaning clients (daycares, offices,
property managers…). Separate from residential Bookings. Accounts are created by
converting a 'Won' Prospect from Find Leads, or added by hand."""
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from entitlements import requires_plan
from auth import owner_required
from extensions import db
from models import CommercialAccount, Prospect, User
import commercial_pricing as cpricing

commercial_bp = Blueprint('commercial', __name__, url_prefix='/commercial')

FREQUENCIES = ['nightly', 'weekly', 'biweekly', 'monthly', 'custom']
CATEGORIES = ['property_manager', 'apartment', 'daycare', 'medical_office', 'restaurant',
              'gym', 'church',
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
    if session.get('role') in ('team', 'sales'):
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
@owner_required
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
@owner_required
def calculator():
    return render_template('admin/commercial_calculator.html', **_tmpl_args())


@commercial_bp.route('/quote.json')
@owner_required
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
        hours=request.args.get('hours'),
    ))


@commercial_bp.route('/new', methods=['POST'])
@owner_required
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
@owner_required
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
            # Whoever found and worked the lead, for their commission -- the
            # owner converting it is not who earned it.
            agent=_agent_from() or p.agent,
        )
        # Won on the call list too, with nothing left due -- or somebody rings
        # a new customer to ask whether they are interested.
        import prospecting
        prospecting.quote_moved(p.id, 'won', 'won', None, None,
                                'Became a commercial account 🎉')
        p.status = 'won'
        p.contact_name = p.contact_name or a.contact_name or None
        p.email = p.email or a.email or None
        db.session.add(a)
        db.session.commit()
        flash(f'🎉 {p.business_name} is now a commercial account!', 'success')
        return redirect(url_for('commercial.detail', account_id=a.id))
    return render_template('admin/commercial_convert.html', **_tmpl_args(p=p))


@commercial_bp.route('/<int:account_id>', methods=['GET', 'POST'])
@owner_required
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
    vas = User.query.filter(User.role.in_(('team', 'sales'))).order_by(User.name).all()
    from models import Booking
    jobs = (Booking.query.filter_by(commercial_account_id=a.id)
            .order_by(Booking.id.desc()).limit(20).all())
    return render_template('admin/commercial_detail.html',
                           **_tmpl_args(a=a, vas=vas, agreements=_agreements(a), jobs=jobs))


def _agreements(a):
    """[(agreement, its quote's frozen terms, signer, replaced by)] for an
    account, newest first. The one nothing has replaced is in force."""
    from models import CommercialAgreement, CommercialQuote, QuoteResponse
    import quote_evidence
    rows = (CommercialAgreement.query.filter_by(account_id=a.id)
            .order_by(CommercialAgreement.effective_on.desc(), CommercialAgreement.id.desc()).all())
    replaced = {r.amends_agreement_id: r for r in rows if r.amends_agreement_id}
    out = []
    for ag in rows:
        q = CommercialQuote.query.get(ag.quote_id)
        response = QuoteResponse.query.get(ag.response_id)
        out.append((ag, quote_evidence.as_issued(q) if q else None,
                    response.signer_name if response else None, replaced.get(ag.id)))
    return out


# What a commercial visit usually covers. Ticked boxes become the scope of work
# the customer is sent and the cleaner works from -- the commercial stand-in for
# bedrooms and bathrooms.
SCOPE_ITEMS = [
    'Empty trash & replace liners',
    'Restrooms — clean, disinfect & restock',
    'Dust & disinfect high-touch surfaces',
    'Vacuum carpets',
    'Sweep & mop hard floors',
    'Break room / kitchen',
    'Lobby & entry',
    'Glass doors & interior windows',
]
SCOPE_DEFAULT = SCOPE_ITEMS[:5]
# The residential labels carry the recurring discount ("Weekly (15% off)"); a
# commercial price is quoted per visit and has none.
JOB_FREQUENCIES = {'one_time': 'One time', 'weekly': 'Weekly',
                   'biweekly': 'Every 2 weeks', 'monthly': 'Monthly'}
# Account frequency -> the nearest job frequency the schedule can repeat.
_JOB_FREQ_FOR = {'weekly': 'weekly', 'biweekly': 'biweekly', 'monthly': 'monthly'}


def _scope_text(items, extra):
    lines = [f'• {i}' for i in items if i]
    if extra:
        lines.append(extra)
    return '\n'.join(lines) or None


@commercial_bp.route('/<int:account_id>/book', methods=['GET', 'POST'])
@owner_required
@requires_plan('commercial')
def book(account_id):
    """Book a job for a commercial account -- scheduled, confirmed and paid
    exactly like a residential booking, priced per visit and described by its
    scope of work instead of bedrooms and bathrooms."""
    import entitlements
    import invoicing
    from models import Booking
    from blueprints.bookings import _link_client, _notify_customer, _send_invoice
    from pricing import get_labor_rate
    from notifications import looks_like_email
    a = CommercialAccount.query.get_or_404(account_id)
    if request.method == 'POST':
        back = redirect(url_for('commercial.book', account_id=a.id))
        ok, why = entitlements.check_limit('jobs_per_month')
        if not ok:
            flash(why, 'error')
            return back
        email = (request.form.get('email') or '').strip().lower()
        if email and not looks_like_email(email):
            flash(f'“{email}” doesn\'t look like a complete email address.', 'error')
            return back
        price = _money(request.form.get('price'))
        if price <= 0:
            flash('Enter the price for this visit.', 'error')
            return back
        try:
            hours = float(request.form.get('estimated_hours') or 0) or None
        except ValueError:
            hours = None
        frequency = request.form.get('frequency', 'one_time')
        if frequency not in JOB_FREQUENCIES:
            frequency = 'one_time'
        contact = (request.form.get('contact_name') or '').strip()
        b = Booking(
            service_type='commercial',
            commercial_account_id=a.id,
            name=a.business_name,
            email=email or None,
            phone=(request.form.get('phone') or '').strip(),
            address=(request.form.get('address') or '').strip(),
            city=(request.form.get('city') or '').strip(),
            zip_code=(request.form.get('zip_code') or '').strip(),
            sqft=_int(request.form.get('square_footage')),
            frequency=frequency,
            preferred_date=(request.form.get('preferred_date') or '').strip(),
            preferred_time=(request.form.get('preferred_time') or '').strip(),
            scope_of_work=_scope_text(request.form.getlist('scope'),
                                      (request.form.get('scope_notes') or '').strip()),
            access_notes=(request.form.get('access_notes') or '').strip() or None,
            notes='\n'.join(x for x in (f'Contact: {contact}' if contact else '',
                                        (request.form.get('notes') or '').strip()) if x) or None,
            status=request.form.get('status', 'confirmed'),
            price=round(price, 2),
            estimated_hours=hours,
            labor_rate_applied=get_labor_rate() if hours else None,
            source='commercial',
            agent=a.agent,
        )
        db.session.add(b)
        db.session.commit()
        _link_client(b)

        pay = request.form.get('payment_option', 'none')
        note = _notify_customer(b, confirmation=bool(request.form.get('notify_customer')),
                                pay_kind=pay if pay in ('deposit', 'full') else 'none')
        if pay == 'invoice_now':
            terms = _int(request.form.get('net_days'))
            invoicing.issue(b, net_days=invoicing.NET_DAYS_COMMERCIAL if terms is None else terms)
            sent = _send_invoice(b)
            note += (f' Sent invoice {b.invoice_number} 🧾.' if sent
                     else f' Invoice {b.invoice_number} made, but it could not be emailed.')
        flash(f'Job booked for {a.business_name} ✅ — assign a cleaner below.{note}', 'success')
        return redirect(url_for('bookings.detail', booking_id=b.id))

    jobs = (Booking.query.filter_by(commercial_account_id=a.id)
            .order_by(Booking.id.desc()).limit(5).all())
    return render_template('admin/commercial_book.html', **_tmpl_args(
        a=a, scope_items=SCOPE_ITEMS, scope_default=SCOPE_DEFAULT,
        job_frequencies=JOB_FREQUENCIES,
        default_frequency=_JOB_FREQ_FOR.get(a.frequency, 'one_time'),
        default_price=(a.billing_amount if a.billing_type == 'per_visit' else None),
        net_days=invoicing.NET_DAYS_COMMERCIAL, deposit=_deposit(), jobs=jobs))


def _deposit():
    from pricing import get_deposit
    try:
        return float(get_deposit() or 0)
    except (TypeError, ValueError):
        return 0.0


@commercial_bp.route('/<int:account_id>/mark-first-paid', methods=['POST'])
@owner_required
def mark_first_paid(account_id):
    a = CommercialAccount.query.get_or_404(account_id)
    if not a.first_paid_at:
        a.first_paid_at = datetime.utcnow()
    a.status = 'active'
    db.session.commit()
    flash('Marked paid — landing bonus + residuals now count toward commission. 💵', 'success')
    return redirect(url_for('commercial.detail', account_id=a.id))


@commercial_bp.route('/<int:account_id>/delete', methods=['POST'])
@owner_required
def delete(account_id):
    a = CommercialAccount.query.get_or_404(account_id)
    from models import QuoteResponse
    if QuoteResponse.query.filter_by(account_id=a.id, decision='accepted').first():
        # The signed proposal names this account; deleting it would leave the
        # agreement pointing at nothing. Paused keeps both.
        flash('This account has a signed proposal on record, so it is kept. '
              'Set it to Paused if the work has stopped.', 'error')
        return redirect(url_for('commercial.detail', account_id=a.id))
    from models import Booking
    if Booking.query.filter_by(commercial_account_id=a.id).first():
        flash('This account has jobs booked, so it is kept. Set it to Paused if the work has stopped.', 'error')
        return redirect(url_for('commercial.detail', account_id=a.id))
    db.session.delete(a)
    db.session.commit()
    flash('Commercial account removed.', 'success')
    return redirect(url_for('commercial.index'))
