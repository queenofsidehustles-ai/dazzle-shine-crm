import secrets
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from entitlements import requires_plan
from auth import owner_required
from models import CommercialQuote, CommercialAccount, Prospect
from extensions import db
from notifications import send_email
import brands
import branding

quotes_bp = Blueprint('quotes', __name__, url_prefix='/quotes')

PROPERTY_TYPES = ['Apartment Complex', 'Student Housing', 'Office Building',
                  'Retail / Commercial', 'Restaurant / Food Service',
                  'Gym / Fitness Center', 'Church / House of Worship',
                  'Property Management Portfolio', 'Other']

SERVICES = [
    'Common Area Cleaning', 'Individual Unit Cleaning', 'Office Cleaning',
    'Restroom Sanitation', 'Lobby & Hallway Cleaning', 'Parking Garage',
    'Window Cleaning', 'Carpet Cleaning', 'Move-Out / Turnover Cleaning',
    'Deep Cleaning', 'Post-Construction Cleanup',
    # What a walkthrough ticks (prospecting.WALKTHROUGH_SERVICES), so a quote
    # written from one says exactly what was agreed on site.
    'Floor Care (Sweep & Mop)', 'Kitchen / Break Room', 'Hood & Vent Degreasing',
    'Equipment Cleaning', 'Dusting & Surfaces', 'Trash Removal',
    'High-Touch Disinfection', 'Floor Stripping & Waxing',
    'Kitchen Floor Degreasing', 'Kitchen Equipment Degreasing (Fryers, Grills, Cooktops)',
]

# What a kind of property is mostly quoted for, shown first so the services
# that matter are not lost among apartment and office lines.
SERVICES_FIRST = {
    'Restaurant / Food Service': [
        'Floor Care (Sweep & Mop)', 'Kitchen Floor Degreasing',
        'Kitchen Equipment Degreasing (Fryers, Grills, Cooktops)', 'Hood & Vent Degreasing',
        'Kitchen / Break Room', 'Restroom Sanitation', 'Trash Removal',
        'High-Touch Disinfection', 'Window Cleaning', 'Deep Cleaning',
    ],
}


def _service_extras():
    """Quote service line -> the commercial calculator add-on it is priced as.
    Lines not here (floors, windows, dusting...) are part of the base clean."""
    import prospecting
    out = {line: addon for _k, _l, line, addon in prospecting.WALKTHROUGH_SERVICES if addon}
    out.update({'Restroom Sanitation': 'restrooms', 'Deep Cleaning': 'deep',
                'Post-Construction Cleanup': 'post_construction'})
    return out


def _estimate_args():
    """What the quote form's estimate helper sends to /commercial/quote.json."""
    import commercial_pricing as cp
    return dict(service_extras=_service_extras(), category_map=_CAT_MAP, freq_map=_FREQ_MAP,
                extra_labels={e['key']: (e['label'], e['pct']) for e in cp.get_config()['extras']})


def _editor_args(q=None, pre=None):
    """What the work-area editor starts from: the quote's own areas, or the
    walkthrough's for a new one, and the catalog of work items to pick from."""
    import commercial_pricing as cp
    cfg = cp.get_config()
    priced = _priced(q) if q is not None else None
    areas = (priced or {}).get('areas') or ((pre or {}).get('line_items') or [])
    show = (q.show_line_prices is not False) if q is not None else True
    return dict(work_items=cfg['work_items'], area_presets=cfg['area_presets'],
                areas_init=areas, show_prices_init=show)


def _services_for(property_type):
    first = SERVICES_FIRST.get(property_type or '', [])
    return first + [s for s in SERVICES if s not in first]

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

# property_type (from the quote form) → CommercialAccount category
_CAT_MAP = {
    'apartment complex': 'apartment',
    'student housing': 'apartment',
    'office building': 'office',
    'retail / commercial': 'other',
    'property management portfolio': 'property_manager',
    'restaurant / food service': 'restaurant',
    'gym / fitness center': 'gym',
    'church / house of worship': 'church',
}
# quote frequency → account frequency
_FREQ_MAP = {'daily': 'nightly', 'weekly': 'weekly', 'biweekly': 'biweekly',
             'monthly': 'monthly', 'as_needed': 'custom'}


def _account_from_quote(q):
    """When a quote is accepted, create the ongoing Commercial Account (won customer)."""
    existing = CommercialAccount.query.filter_by(business_name=q.company, email=q.email).first()
    if existing:
        return existing
    acc = CommercialAccount(
        business_name=q.company, contact_name=q.contact_name, email=q.email, phone=q.phone,
        address=q.property_address, city='',
        category=_CAT_MAP.get((q.property_type or '').lower(), 'office'),
        frequency=_FREQ_MAP.get(q.frequency, 'weekly'),
        billing_type='monthly' if q.monthly_price else 'per_visit',
        billing_amount=(q.monthly_price or q.price_per_visit or 0),
        status='active', source='quote',
        notes=f'Created from accepted quote (brand: {q.brand or "lm"}).',
    )
    db.session.add(acc)
    db.session.commit()
    return acc


# call-list category → the quote form's property type
_PROPERTY_FOR_CATEGORY = {
    'apartment': 'Apartment Complex',
    'property_manager': 'Property Management Portfolio',
    'office': 'Office Building',
    'medical_office': 'Office Building',
    'daycare': 'Office Building',
    'restaurant': 'Restaurant / Food Service',
    'gym': 'Gym / Fitness Center',
    'church': 'Church / House of Worship',
}


def _lead_for(q):
    """The call-list lead a quote was written for, or None."""
    if not getattr(q, 'prospect_id', None):
        return None
    return Prospect.query.get(q.prospect_id)


def _lead_moved(q, stage, status, next_action, days, note):
    """See prospecting.quote_moved. Callers commit."""
    import prospecting
    return prospecting.quote_moved(getattr(q, 'prospect_id', None), stage, status,
                                   next_action, days, note)


@quotes_bp.route('/')
@owner_required
@requires_plan('commercial')
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
@owner_required
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
            brand=(request.form.get('brand') or brands.brand_for_property(request.form.get('property_type', ''))),
        )
        _apply_lines(q)
        lead = Prospect.query.get(request.form.get('prospect_id', type=int) or 0)
        if lead:
            q.prospect_id = lead.id
            # What the quote learned about them is worth keeping on the lead,
            # where the next call will be made from.
            lead.contact_name = lead.contact_name or q.contact_name or None
            lead.email = lead.email or q.email or None
            lead.phone = lead.phone or q.phone or None
        db.session.add(q)
        db.session.commit()
        flash('Draft saved — nothing has been sent. Review it, then press Send when it is ready.', 'success')
        if request.form.get('next') == 'review':
            return redirect(url_for('quotes.review', quote_id=q.id))
        return redirect(url_for('quotes.detail', quote_id=q.id))

    # Started from a lead on the call list: fill in what is already known
    # rather than make somebody copy it across by hand.
    lead = Prospect.query.get(request.args.get('prospect_id', type=int) or 0)
    pre = {}
    if lead:
        # Google's addresses already end in the city; typed ones often do not.
        address = lead.address or ''
        if lead.city and lead.city.lower() not in address.lower():
            address = ', '.join(x for x in (address, lead.city) if x)
        pre = {
            'company': lead.business_name, 'contact_name': lead.contact_name or '',
            'email': lead.email or '', 'phone': lead.phone or '',
            'property_type': _PROPERTY_FOR_CATEGORY.get(lead.category, 'Other'),
            'brand': brands.normalize_lens(lead.brand) if lead.brand else '',
            'property_address': address or '',
        }
        # And what the walkthrough found: size, how often, what is included,
        # and a starting price from the calculator. Hers to change.
        import prospecting
        pre.update(prospecting.walkthrough_quote_prefill(lead))
    return render_template('admin/quote_form.html', quote=None, lead=lead, pre=pre,
                           selected_services=pre.get('services') or [],
                           property_types=PROPERTY_TYPES,
                           services=_services_for(pre.get('property_type')),
                           frequencies=FREQUENCIES, contract_terms=CONTRACT_TERMS,
                           **_estimate_args(), **_editor_args(pre=pre))


def _apply_form(q):
    """The quote form's fields onto a quote. Shared by Save and Send, so
    Send emails what is on the screen rather than what was last saved."""
    f = request.form
    q.company = (f.get('company') or q.company or '').strip()
    q.contact_name = (f.get('contact_name', q.contact_name) or '').strip()
    q.email = (f.get('email', q.email) or '').strip()
    q.phone = (f.get('phone', q.phone) or '').strip()
    q.property_type = f.get('property_type', q.property_type)
    q.property_address = (f.get('property_address', q.property_address) or '').strip()
    q.units = (f.get('units', q.units) or '').strip()
    q.sqft = (f.get('sqft', q.sqft) or '').strip()
    q.services = ', '.join(f.getlist('services'))
    q.frequency = f.get('frequency', q.frequency)
    q.contract_term = f.get('contract_term', q.contract_term)
    q.price_per_visit = f.get('price_per_visit') or None
    q.monthly_price = f.get('monthly_price') or None
    q.scope_notes = (f.get('scope_notes', q.scope_notes) or '').strip()
    q.brand = f.get('brand') or q.brand or brands.brand_for_property(q.property_type)
    _apply_lines(q)


def _apply_lines(q):
    """The work-area editor's areas and lines onto a quote, priced on the
    server and kept as a snapshot: what was quoted stays what was quoted when
    a rate in Settings changes next month. With lines, they set the price a
    visit and a month -- the two can no longer disagree with the table the
    customer reads. Without the editor in the post (an older form, a send from
    the review page) nothing changes."""
    import json
    import commercial_pricing as cp
    raw = request.form.get('line_items_json')
    if raw is None:
        return
    q.show_line_prices = request.form.get('show_line_prices') == '1'
    try:
        areas = json.loads(raw) if raw.strip() else []
    except ValueError:
        areas = []
    priced = cp.area_quote(areas if isinstance(areas, list) else [], q.frequency or 'weekly')
    if any(a['lines'] for a in priced['areas']):
        q.line_items = json.dumps(priced)
        q.price_per_visit = priced['per_visit']
        q.monthly_price = priced['monthly']
    else:
        q.line_items = None


def _priced(q):
    """The quote's priced work areas, or None for a quote priced the old way."""
    import json
    try:
        data = json.loads(q.line_items) if getattr(q, 'line_items', None) else None
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get('areas') else None


@quotes_bp.route('/lines.json', methods=['POST'])
@owner_required
def lines_json():
    """Price the work-area editor's lines as they are typed. The arithmetic
    lives on the server, once -- see commercial.quote_json for why."""
    from flask import jsonify
    import commercial_pricing as cp
    d = request.get_json(silent=True) or {}
    areas = d.get('areas') if isinstance(d.get('areas'), list) else []
    return jsonify(cp.area_quote(areas, d.get('frequency') or 'weekly', keep_empty=True))


@quotes_bp.route('/<int:quote_id>', methods=['GET', 'POST'])
@owner_required
def detail(quote_id):
    q = CommercialQuote.query.get_or_404(quote_id)
    if request.method == 'POST':
        _apply_form(q)
        db.session.commit()
        flash('Draft saved — nothing has been sent.' if q.status == 'draft' else 'Quote updated.', 'success')
        return redirect(url_for('quotes.detail', quote_id=quote_id))

    selected_services = [s.strip() for s in (q.services or '').split(',') if s.strip()]
    return render_template('admin/quote_form.html', quote=q, lead=_lead_for(q), pre={},
                           property_types=PROPERTY_TYPES, services=_services_for(q.property_type),
                           frequencies=FREQUENCIES, contract_terms=CONTRACT_TERMS,
                           selected_services=selected_services, **_estimate_args(),
                           **_editor_args(q=q))


def _quote_url(q):
    return f"{request.host_url.rstrip('/')}/quotes/view/{q.token}"


def _doc_ctx(q):
    """What the proposal document needs -- the customer's page and the review."""
    return dict(
        priced=_priced(q),
        show_line_prices=getattr(q, 'show_line_prices', True) is not False,
        freq_label=dict(FREQUENCIES).get(q.frequency, q.frequency),
        term_label=dict(CONTRACT_TERMS).get(q.contract_term, q.contract_term),
        services_list=[s.strip() for s in (q.services or '').split(',') if s.strip()],
    )


def _areas_email_html(priced, show_prices, accent):
    """The work-area table for the email, in the inline styles mail clients
    keep. Same rule as the page: every line's price, or each area's total."""
    from markupsafe import escape as e
    td = 'padding:7px 0;border-top:1px solid #e4dfef;vertical-align:top'
    num = td + ';text-align:right;white-space:nowrap;padding-left:10px'
    qty = td + ';color:#6b6585;text-align:right;white-space:nowrap;padding-left:10px'
    money = lambda v: f'${float(v or 0):,.2f}'
    rows = []
    for a in priced.get('areas') or []:
        if not a.get('lines'):
            continue
        rows.append(f'<tr><td colspan="2" style="padding:14px 0 4px;font-weight:700;color:{accent}">{e(a["name"])}</td>'
                    f'<td style="padding:14px 0 4px;text-align:right;font-weight:700">'
                    f'{"" if show_prices else money(a.get("subtotal"))}</td></tr>')
        for l in a['lines']:
            q_txt = f'{float(l.get("qty") or 0):,g} {e(l.get("unit") or "")}' if l.get('qty') else ''
            rows.append(f'<tr><td style="{td}">{e(l.get("label") or "")}</td><td style="{qty}">{q_txt}</td>'
                        f'<td style="{num}">{money(l.get("price")) if show_prices else ""}</td></tr>')
        if show_prices:
            rows.append(f'<tr><td colspan="2" style="{td};font-weight:700">{e(a["name"])} total</td>'
                        f'<td style="{num};font-weight:700">{money(a.get("subtotal"))}</td></tr>')
    if priced.get('minimum') or priced.get('travel'):
        rows.append(f'<tr><td colspan="3" style="padding:14px 0 4px;font-weight:700;color:{accent}">Each visit</td></tr>')
        if priced.get('minimum'):
            rows.append(f'<tr><td colspan="2" style="{td}">Minimum visit charge (visits are at least '
                        f'${float(priced.get("min_visit") or 0):,.0f})</td><td style="{num}">{money(priced["minimum"])}</td></tr>')
        if priced.get('travel'):
            rows.append(f'<tr><td colspan="2" style="{td}">Travel to and from your site</td>'
                        f'<td style="{num}">{money(priced["travel"])}</td></tr>')
    return ('<table style="width:100%;border-collapse:collapse;font-size:14px" cellpadding="0" cellspacing="0">'
            + ''.join(rows) + '</table>')


def _proposal_email(q, quote_url, draft=False):
    """(subject, html) of the proposal email. The one builder for the send, the
    review page's preview of it, and the draft copy circulated for review --
    so what was looked over is exactly what goes out.

    Everything typed into the quote is escaped: a company called "A&B <Ltd>"
    used to arrive as broken markup."""
    from markupsafe import escape as e
    ctx = _doc_ctx(q)
    brand = q.brand or brands.brand_for_property(q.property_type)
    b = brands.get_brand(brand)
    services_html = ''.join(f'<li>{e(s)}</li>' for s in ctx['services_list'])
    price_html = ''
    if q.price_per_visit:
        price_html += f"<p><strong>Price per visit:</strong> ${float(q.price_per_visit):,.2f}</p>"
    if q.monthly_price:
        price_html += f"<p><strong>Monthly total:</strong> ${float(q.monthly_price):,.2f}</p>"
    units_html = f'<br>Units: {e(q.units)}' if q.units else ''
    sqft_html = f' · {e(q.sqft)} sq ft' if q.sqft else ''
    scope_html = (f'<div style="background:#f6f5fb;border-radius:9px;padding:14px;margin-top:10px;white-space:pre-line">'
                  f'<strong>Scope of Work:</strong><br>{e(q.scope_notes)}</div>') if q.scope_notes else ''
    address = (' · ' + str(e(q.property_address))) if q.property_address else ''
    draft_html = ('<div style="background:#fff4e5;border:1px dashed #d97706;color:#92400e;border-radius:9px;'
                  'padding:12px 14px;margin-bottom:16px;font-weight:600">DRAFT for review — this has not been '
                  'sent to the customer, and it has no Accept button.</div>') if draft else ''
    inner = (
        f'{draft_html}'
        f'<p>Dear {e(q.contact_name or "")},</p>'
        f'<p>Thank you for the opportunity to quote cleaning services for <strong>{e(q.company)}</strong>. '
        f'Please find your customized proposal below.</p>'
        f'<h3 style="color:{b["accent"]};margin:18px 0 6px">Property</h3>'
        f'<p>{e(q.property_type or "")}{address}{units_html}{sqft_html}</p>'
        + (f'<h3 style="color:{b["accent"]};margin:18px 0 6px">Scope of Work by Area</h3>'
           + _areas_email_html(ctx['priced'], ctx['show_line_prices'], b['accent'])
           if ctx['priced'] else
           f'<h3 style="color:{b["accent"]};margin:18px 0 6px">Services Included</h3>'
           f'<ul style="padding-left:20px;line-height:1.9">{services_html}</ul>') +
        f'<h3 style="color:{b["accent"]};margin:18px 0 6px">Schedule &amp; Pricing</h3>'
        f'<p><strong>Frequency:</strong> {e(ctx["freq_label"] or "")}<br>'
        f'<strong>Contract term:</strong> {e(ctx["term_label"] or "")}</p>'
        f'{price_html}{scope_html}'
        + ('' if draft else '<p style="text-align:center;margin-top:16px">Ready to move forward? Review and accept below.</p>')
    )
    html = brands.email_shell(brand, 'Your Cleaning Proposal', inner,
                              cta_text=None if draft else 'Review &amp; Accept Quote →',
                              cta_url=None if draft else quote_url)
    return f'Cleaning Services Proposal — {b["name"]}', html


_VISITS = {'daily': 22, 'weekly': 4.33, 'biweekly': 2.17, 'monthly': 1}


def _send_checks(q):
    """What to look at before this goes to a customer: (blocking, warnings).
    Blocking ones stop the Send button; the rest are worth a second look."""
    import re
    blocking, warnings = [], []
    if not (q.contact_name or '').strip():
        blocking.append('No contact name — the email would open "Dear ,".')
    if not (q.email or '').strip():
        blocking.append('No email address to send it to.')
    elif not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', q.email.strip()):
        blocking.append(f'"{q.email}" does not look like an email address.')
    if not (q.monthly_price or q.price_per_visit):
        warnings.append('No price on it — they would be asked to accept without a figure.')
    priced = _priced(q)
    if priced:
        for a in priced['areas']:
            if not a['lines']:
                warnings.append(f'"{a["name"]}" has no lines — it will not appear on the proposal.')
            for l in a['lines']:
                if not l.get('price'):
                    warnings.append(f'"{l["label"]}" in {a["name"]} is priced at $0.')
                elif not l.get('qty') and l.get('item') != 'custom':
                    warnings.append(f'"{l["label"]}" in {a["name"]} has no quantity.')
    elif not (q.services or '').strip():
        warnings.append('No services ticked — the "Services Included" section is empty.')
    if not (q.property_address or '').strip():
        warnings.append('No property address.')
    visits = _VISITS.get(q.frequency)
    if visits and q.monthly_price and q.price_per_visit:
        expected = float(q.price_per_visit) * visits
        if expected and abs(float(q.monthly_price) - expected) / expected > 0.10:
            warnings.append(
                f'The monthly total (${float(q.monthly_price):,.2f}) does not match '
                f'${float(q.price_per_visit):,.2f} a visit × about {visits:g} visits a month '
                f'(${expected:,.2f}).')
    return blocking, warnings


@quotes_bp.route('/<int:quote_id>/review', methods=['GET', 'POST'])
@owner_required
def review(quote_id):
    """The proposal as the customer will see it -- the page and the email --
    with what still needs fixing, before anything is sent. Posting the edit
    form here saves it first, so the review is of what is on the screen."""
    q = CommercialQuote.query.get_or_404(quote_id)
    if request.method == 'POST':
        if 'company' in request.form:
            _apply_form(q)
            db.session.commit()
        return redirect(url_for('quotes.review', quote_id=q.id))
    brand = q.brand or brands.brand_for_property(q.property_type)
    from_name, from_email, reply_to = brands.send_identity(brand)
    subject, email_html = _proposal_email(q, _quote_url(q))
    blocking, warnings = _send_checks(q)
    return render_template(
        'admin/quote_review.html', q=q, lead=_lead_for(q), doc_biz=branding.biz_name(),
        email_subject=subject, email_html=email_html, from_name=from_name,
        from_email=from_email, reply_to=reply_to, blocking=blocking, warnings=warnings,
        owner_email=branding.owner_email() or '', **_doc_ctx(q))


@quotes_bp.route('/<int:quote_id>/document')
@owner_required
def document(quote_id):
    """The proposal alone, on a page of its own, to print or save as a PDF --
    the copy to keep, attach, or hand over at the walkthrough."""
    q = CommercialQuote.query.get_or_404(quote_id)
    return render_template('admin/quote_print.html', q=q, doc_biz=branding.biz_name(), **_doc_ctx(q))


@quotes_bp.route('/<int:quote_id>/circulate', methods=['POST'])
@owner_required
def circulate(quote_id):
    """Email a DRAFT copy to people who should look it over first -- a partner,
    the cleaner who did the walkthrough, yourself on another device. It has no
    Accept button and no link a reader could accept from; replies come back to
    the owner, not to the business's customer inbox."""
    import re
    q = CommercialQuote.query.get_or_404(quote_id)
    raw = request.form.get('to', '')
    to = [a for a in re.split(r'[\s,;]+', raw) if a][:5]
    bad = [a for a in to if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', a)]
    if not to or bad:
        flash(f'Who should review it? {"Not an email address: " + ", ".join(bad) if bad else "Add an email address."}',
              'error')
        return redirect(url_for('quotes.review', quote_id=q.id))
    from markupsafe import escape as e
    note = (request.form.get('note') or '').strip()[:2000]
    _subject, html = _proposal_email(q, _quote_url(q), draft=True)
    review_link = url_for('quotes.review', quote_id=q.id, _external=True)
    intro = (f'<div style="font-family:Inter,Arial,sans-serif;max-width:600px;margin:0 auto 14px;color:#1f1333">'
             f'<p><strong>{e(branding.biz_name())}</strong> would like a second look at this proposal for '
             f'<strong>{e(q.company)}</strong> before it goes to the customer.</p>'
             + (f'<p style="background:#f6f5fb;border-radius:9px;padding:12px;white-space:pre-line">{e(note)}</p>' if note else '')
             + f'<p style="font-size:0.85rem;color:#6b6585">Reply to this email with any changes. '
             f'Team members can also open it in the app: <a href="{review_link}">{review_link}</a></p></div>')
    brand = q.brand or brands.brand_for_property(q.property_type)
    from_name, from_email, _reply = brands.send_identity(brand)
    owner = branding.owner_email() or _reply
    sent, failed = [], []
    for addr in to:
        ok, _detail = send_email(
            to_email=addr, to_name=addr,
            subject=f'For review (not sent to the customer): proposal for {q.company}',
            html=intro + html, from_name=from_name, from_email=from_email, reply_to=owner)
        (sent if ok else failed).append(addr)
    if sent:
        lead = _lead_for(q)
        if lead:
            import prospecting
            lead.notes = prospecting.note_entry(lead, f'Draft quote sent for review to {", ".join(sent)}')
        db.session.commit()
        flash(f'Draft sent for review to {", ".join(sent)}. The customer has not been sent anything.', 'success')
    if failed:
        flash(f'Could not email {", ".join(failed)}.', 'error')
    return redirect(url_for('quotes.review', quote_id=q.id))


@quotes_bp.route('/<int:quote_id>/send', methods=['POST'])
@owner_required
def send_quote(quote_id):
    q = CommercialQuote.query.get_or_404(quote_id)
    # The Send button sits in the edit form and posts it. Those edits used to
    # be dropped -- change the price, press Send, and the old price went out.
    if 'company' in request.form:
        _apply_form(q)
        db.session.commit()
    # A draft can be saved before anybody's name or email is known (half-way
    # through a walkthrough); it cannot be sent like that.
    if q.status == 'accepted':
        # Re-sending would put a signed customer back to "sent" and restart
        # the follow-up emails at somebody who already said yes.
        flash('This quote was accepted — it is not sent again.', 'error')
        return redirect(url_for('quotes.review', quote_id=q.id))
    blocking, _warnings = _send_checks(q)
    if blocking:
        flash('Not sent: ' + ' '.join(blocking), 'error')
        return redirect(url_for('quotes.review', quote_id=q.id))
    quote_url = _quote_url(q)
    brand = q.brand or brands.brand_for_property(q.property_type)
    from_name, from_email, reply_to = brands.send_identity(brand)
    subject, html = _proposal_email(q, quote_url)
    ok, detail = send_email(
        to_email=q.email, to_name=q.contact_name,
        subject=subject,
        html=html, from_name=from_name, from_email=from_email, reply_to=reply_to,
    )
    if not ok:
        flash(f"Quote could NOT be emailed to {q.email}. {detail}", 'error')
        return redirect(url_for('quotes.detail', quote_id=q.id))

    q.status = 'sent'
    q.sent_at = datetime.utcnow()
    q.drip_step = 0          # (re)start the follow-up nurture clock
    q.last_drip_at = None
    lead = _lead_moved(q, 'proposal', None, 'Follow up on the quote', 3,
                       f'Quote emailed to {q.email}')
    if lead:
        lead.last_emailed_at = datetime.utcnow()
    db.session.commit()

    # Send the owner a copy so there's always a record in your inbox
    owner_email = branding.owner_email()
    if owner_email and owner_email.lower() != (q.email or '').lower():
        try:
            send_email(
                to_email=owner_email, to_name=branding.biz_name(),
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
@owner_required
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
    # The same context as the owner's review, so the two cannot drift apart.
    return render_template('public/quote_view.html', q=q, **_doc_ctx(q))


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
        acc = _account_from_quote(q)   # accepted quote becomes an ongoing Commercial Account
        lead = _lead_moved(q, 'won', 'won', None, None, 'Accepted the quote 🎉')
        if lead and acc and not acc.prospect_id:
            acc.prospect_id = lead.id
        # Credit the account to whoever worked the lead, for their commission.
        linked = _lead_for(q)
        if acc and linked and linked.agent and not acc.agent:
            acc.agent = linked.agent
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
    notify_email = branding.owner_email()
    send_email(
        to_email=notify_email, to_name=branding.biz_name(),
        from_name=f'{branding.biz_name()} Quotes',
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
    # A declined quote is "not now", not "never" -- the same reasoning that
    # rests a "not interested" call in nurture for a quarter.
    _lead_moved(q, 'nurture', 'not_interested', 'Quarterly check-in', 90,
                'Declined the quote')
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        db.session.execute(__import__('sqlalchemy').text(
            "UPDATE commercial_quote SET status='declined' WHERE token=:t"
        ), {'t': token})
        db.session.commit()
    notify_email = branding.owner_email()
    send_email(
        to_email=notify_email, to_name=branding.biz_name(),
        from_name=f'{branding.biz_name()} Quotes',
        subject=f'Quote declined: {q.company}',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#991b1b">Quote Declined</h2>
  <p><strong>{q.contact_name}</strong> at <strong>{q.company}</strong> declined your proposal.</p>
  <p>Consider following up to understand their concerns or offer an adjusted price.</p>
</div>""",
    )
    return render_template('public/quote_response.html', accepted=False, q=q)
