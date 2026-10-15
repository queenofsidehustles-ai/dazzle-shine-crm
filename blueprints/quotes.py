import secrets
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from entitlements import requires_plan
from auth import owner_required
from models import CommercialQuote, CommercialAccount, Prospect, QuoteDelivery, QuoteResponse
from extensions import db
from notifications import send_email
import brands
import branding
import quote_evidence

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
    # A line this quote locked in (see _lock_saved) keeps its saved price
    # forever, even after a rate in Settings moves -- that's the point. But
    # nobody editing the quote would otherwise notice their rates have since
    # changed, so re-price the same areas fresh, with nothing locked, and
    # flag it if that comes out different from what's actually saved.
    rates_changed = False
    if priced:
        live = cp.area_quote(priced['areas'], q.frequency or 'weekly',
                             first_visit=bool(q.first_visit_premium))
        rates_changed = (round(live['per_visit'], 2) != round(priced['per_visit'], 2)
                         or round(live['first_visit_total'], 2) != round(priced.get('first_visit_total') or 0, 2))
    return dict(work_items=cfg['work_items'], area_presets=cfg['area_presets'],
                areas_init=areas, show_prices_init=show, rates_changed=rates_changed)


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
    """When a quote is accepted, the ongoing Commercial Account (won customer)
    it belongs to: the one it was written for (q.account_id -- carried by a
    revision or a rebid), else the one already made from the same lead, else
    a new one. By key only. Matching on company name and email joined two
    customers who shared a name or an inbox, and split one whose contact
    changed -- see the 2026-10-15 audit, F5.

    Never commits: it is one step of accepting, and accepting is all-or-nothing
    (see accept()). Committing here once left a quote accepted with no account
    whenever a later step failed."""
    existing = CommercialAccount.query.get(q.account_id) if q.account_id else None
    if existing is None and q.prospect_id:
        existing = (CommercialAccount.query.filter_by(prospect_id=q.prospect_id)
                    .order_by(CommercialAccount.id).first())
    if existing:
        return existing
    acc = CommercialAccount(
        business_name=q.company, contact_name=q.contact_name, email=q.email, phone=q.phone,
        address=q.property_address, city='',
        category=_CAT_MAP.get((q.property_type or '').lower(), 'office'),
        frequency=_FREQ_MAP.get(q.frequency, 'weekly'),
        billing_type='monthly' if q.monthly_price else 'per_visit',
        billing_amount=(q.monthly_price or q.price_per_visit or 0),
        status='active', source='quote', prospect_id=q.prospect_id,
        notes=f'Created from accepted quote #{q.id} (brand: {q.brand or "lm"}).',
    )
    db.session.add(acc)
    db.session.flush()
    return acc


def _hold(quote_id):
    """The quote, with its row locked until this request commits.

    Saving, sending and deleting all start here, so no two of them overlap on
    one quote: a save that began while it was a draft can't land after a send
    has gone out (rewriting terms under the customer's link), a draft can't be
    deleted the moment it is sent, and a customer's accept -- a conditional
    write on the same row -- waits for a send in progress instead of being
    overwritten by it."""
    return (CommercialQuote.query.filter_by(id=quote_id)
            .with_for_update().populate_existing().first_or_404())


def _lock_message(q):
    """Why this quote's terms can't be changed, and what to do instead."""
    if q.status == 'accepted':
        return 'This quote was accepted — its terms are locked. Duplicate it to send a revised offer.'
    if q.status == 'sent':
        return ('This quote was sent — its terms are fixed under the link the customer has. '
                'Revise it to change them: the sent version is withdrawn and a new draft opens with the same terms.')
    return f'This quote was {q.status} — its terms are fixed. Revise or duplicate it for a new offer.'


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
        'withdrawn': CommercialQuote.query.filter_by(status='withdrawn').count(),
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
            first_visit_premium=request.form.get('first_visit_premium') == '1',
            valid_days=_valid_days(),
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
    Send emails what is on the screen rather than what was last saved.

    A no-op once a quote is accepted: the terms a customer agreed to are
    what they agreed to, permanently -- not whatever somebody typed into
    this same form afterward. Duplicate it (see duplicate()) for a revised
    offer; that starts a new, separate record rather than rewriting this
    one's price out from under an accepted contract."""
    if q.status == 'accepted':
        return
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
    q.first_visit_premium = f.get('first_visit_premium') == '1'
    q.valid_days = _valid_days(q.valid_days)
    _apply_lines(q)


def _valid_days(current=None):
    """How many days the offer stays open once sent: 1 to 365, else 30."""
    raw = request.form.get('valid_days')
    if raw is None:
        return current or 30
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return current or 30
    return n if 1 <= n <= 365 else (current or 30)


def _apply_lines(q):
    """The work-area editor's areas and lines onto a quote, priced on the
    server and kept as a snapshot: what was quoted stays what was quoted when
    a rate in Settings changes next month. With lines, they set the price a
    visit and a month -- the two can no longer disagree with the table the
    customer reads. Without the editor in the post (an older form, a send from
    the review page) nothing changes.

    Also a no-op once accepted (see _apply_form) -- called on a new, still-
    unaccepted quote too, where the check never fires."""
    import json
    import commercial_pricing as cp
    if q.status == 'accepted':
        return
    raw = request.form.get('line_items_json')
    if raw is None:
        return
    q.show_line_prices = request.form.get('show_line_prices') == '1'
    try:
        areas = json.loads(raw) if raw.strip() else []
    except ValueError:
        areas = []
    areas = areas if isinstance(areas, list) else []
    priced = cp.area_quote(areas, q.frequency or 'weekly', first_visit=bool(q.first_visit_premium),
                           **_lock_saved(areas, _priced(q)))
    if any(a['lines'] for a in priced['areas']):
        q.line_items = json.dumps(priced)
        q.price_per_visit = priced['per_visit']
        q.monthly_price = priced['monthly']
    else:
        q.line_items = None


def _lock_saved(areas, saved):
    """Keep what a saved quote was priced at, for every line nobody changed.

    The editor posts every line on every save -- and on Review, which saves
    first -- and a calculated line is worked out from today's rates. Without
    this, raising the hourly cost next month and opening an old quote to fix a
    typo re-priced it, and a proposal already sent (or accepted) changed under
    the customer. A line still in the same area, for the same work and the
    same quantity, keeps its saved price; the travel keeps its too, and so
    does the first-visit percentage -- changing that setting in Settings
    should not silently change what an already-priced quote's premium comes
    to the next time someone saves it. A line that was changed, or added, is
    priced today.
    Mutates `areas`; returns the area_quote kwargs."""
    if not saved:
        return {}
    old = {}
    for a in saved.get('areas') or []:
        for l in a.get('lines') or []:
            if not l.get('override') and l.get('item') != 'custom':
                old.setdefault(((a.get('name') or '').strip().lower(), l.get('item'), float(l.get('qty') or 0)),
                               l.get('price'))
    for a in areas:
        if not isinstance(a, dict):
            continue
        for l in a.get('lines') or []:
            if not isinstance(l, dict) or l.get('override'):
                continue
            try:
                qty = float(str(l.get('qty') or 0).replace(',', ''))
            except ValueError:
                continue
            k = ((a.get('name') or '').strip().lower(), l.get('item'), qty)
            if k in old:
                l['locked_price'] = old[k]
    return {'fixed': {'travel': saved.get('travel'), 'first_visit_pct': saved.get('first_visit_pct')}}


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
    # Editing a saved quote: show the prices it will keep, not today's.
    saved = None
    if d.get('quote_id'):
        q = CommercialQuote.query.get(int(d['quote_id'])) if str(d['quote_id']).isdigit() else None
        saved = _priced(q) if q else None
    return jsonify(cp.area_quote(areas, d.get('frequency') or 'weekly', keep_empty=True,
                                 first_visit=bool(d.get('first_visit')),
                                 **_lock_saved(areas, saved)))


def _quote_history(q):
    """Other quotes for the same account -- the same call-list lead, or
    failing that the same company name -- so whoever is pricing a rebid
    can see what it went for elsewhere without digging through Quotes."""
    query = CommercialQuote.query.filter(CommercialQuote.id != q.id)
    if q.prospect_id:
        query = query.filter(CommercialQuote.prospect_id == q.prospect_id)
    elif q.company:
        query = query.filter(db.func.lower(CommercialQuote.company) == q.company.strip().lower())
    else:
        return []
    return query.order_by(CommercialQuote.created_at.desc()).limit(5).all()


@quotes_bp.route('/<int:quote_id>', methods=['GET', 'POST'])
@owner_required
def detail(quote_id):
    q = CommercialQuote.query.get_or_404(quote_id)
    if request.method == 'POST':
        q = _hold(quote_id)
        if q.locked:
            flash(_lock_message(q), 'error')
            return redirect(url_for('quotes.detail', quote_id=quote_id))
        _apply_form(q)
        db.session.commit()
        flash('Draft saved — nothing has been sent.' if q.status == 'draft' else 'Quote updated.', 'success')
        return redirect(url_for('quotes.detail', quote_id=quote_id))

    selected_services = [s.strip() for s in (q.services or '').split(',') if s.strip()]
    return render_template('admin/quote_form.html', quote=q, lead=_lead_for(q), pre={},
                           property_types=PROPERTY_TYPES, services=_services_for(q.property_type),
                           frequencies=FREQUENCIES, contract_terms=CONTRACT_TERMS,
                           history=_quote_history(q),
                           selected_services=selected_services, **_estimate_args(),
                           **_editor_args(q=q))


def _day(d):
    """October 15, 2026."""
    return f'{d:%B} {d.day}, {d.year}' if d else ''


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
    import commercial_pricing as cp
    td = 'padding:7px 0;border-top:1px solid #e4dfef;vertical-align:top'
    num = td + ';text-align:right;white-space:nowrap;padding-left:10px'
    qty = td + ';color:#6b6585;text-align:right;white-space:nowrap;padding-left:10px'
    money = lambda v: f'${float(v or 0):,.2f}'
    rate = cp.fmt_sqft_rate
    rows = []
    for a in priced.get('areas') or []:
        if not a.get('lines'):
            continue
        area_rate = f' ({rate(a["rate_per_sqft"])})' if show_prices and a.get('rate_per_sqft') else ''
        rows.append(f'<tr><td colspan="2" style="padding:14px 0 4px;font-weight:700;color:{accent}">{e(a["name"])}</td>'
                    f'<td style="padding:14px 0 4px;text-align:right;font-weight:700">'
                    f'{"" if show_prices else money(a.get("subtotal"))}</td></tr>')
        for l in a['lines']:
            q_txt = f'{float(l.get("qty") or 0):,g} {e(l.get("unit") or "")}' if l.get('qty') else ''
            line_rate = f' <span style="color:#9a95ad">({rate(l["rate_per_sqft"])})</span>' if show_prices and l.get('rate_per_sqft') else ''
            rows.append(f'<tr><td style="{td}">{e(l.get("label") or "")}</td><td style="{qty}">{q_txt}</td>'
                        f'<td style="{num}">{money(l.get("price")) + line_rate if show_prices else ""}</td></tr>')
        if show_prices:
            rows.append(f'<tr><td colspan="2" style="{td};font-weight:700">{e(a["name"])} total{area_rate}</td>'
                        f'<td style="{num};font-weight:700">{money(a.get("subtotal"))}</td></tr>')
    if priced.get('travel') or priced.get('minimum') or priced.get('price_per_sqft'):
        rows.append(f'<tr><td colspan="3" style="padding:14px 0 4px;font-weight:700;color:{accent}">Each visit</td></tr>')
        if priced.get('minimum'):
            # A quote saved before the minimum-visit floor was dropped from
            # this editor -- its per_visit already includes this top-up, so
            # it has to keep showing here or the lines stop adding up.
            rows.append(f'<tr><td colspan="2" style="{td}">Minimum visit charge</td>'
                        f'<td style="{num}">{money(priced["minimum"])}</td></tr>')
        if priced.get('travel'):
            rows.append(f'<tr><td colspan="2" style="{td}">Travel to and from your site</td>'
                        f'<td style="{num}">{money(priced["travel"])}</td></tr>')
        if priced.get('price_per_sqft'):
            rows.append(f'<tr><td colspan="2" style="{td};color:#6b6585">Works out to</td>'
                        f'<td style="{num};color:#6b6585">{rate(priced["price_per_sqft"])} a visit</td></tr>')
    if priced.get('first_visit_charge'):
        pct = round((priced.get('first_visit_pct') or 0) * 100)
        rows.append(f'<tr><td colspan="3" style="padding:14px 0 4px;font-weight:700;color:{accent}">First visit</td></tr>')
        rows.append(f'<tr><td colspan="2" style="{td}">One-time first-visit premium (+{pct}%) — the first clean on a '
                    f'new contract runs longer than every visit after it</td>'
                    f'<td style="{num}">{money(priced["first_visit_charge"])}</td></tr>')
        rows.append(f'<tr><td colspan="2" style="{td};font-weight:700">Your first visit total</td>'
                    f'<td style="{num};font-weight:700">{money(priced.get("first_visit_total"))}</td></tr>')
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
        f'<strong>Contract term:</strong> {e(ctx["term_label"] or "")}'
        + (f'<br><strong>Offer open until:</strong> {_day(q.expires_at)}' if q.expires_at else '')
        + '</p>'
        f'{price_html}{scope_html}'
        + ('' if draft else '<p style="text-align:center;margin-top:16px">Ready to move forward? Review and accept below.</p>')
    )
    html = brands.email_shell(brand, 'Your Cleaning Proposal', inner,
                              cta_text=None if draft else 'Review &amp; Accept Quote →',
                              cta_url=None if draft else quote_url)
    return f'Cleaning Services Proposal — {b["name"]}', html


_VISITS = {'daily': 22, 'weekly': 4.33, 'biweekly': 2.17, 'monthly': 1}


def _binding_gaps(q):
    """What an offer someone can accept must say, and this one doesn't: a
    price, what work is included, how often, and for how long. A proposal
    missing any of them is not sent -- and one sent before this was checked
    is not accepted (see view()). Takes a quote or a frozen revision."""
    gaps = []
    if not (q.monthly_price or q.price_per_visit):
        gaps.append('No price — a customer cannot accept an offer without a figure.')
    priced = _priced(q)
    if not ((priced and any(a.get('lines') for a in priced['areas']))
            or (q.services or '').strip() or (q.scope_notes or '').strip()):
        gaps.append('Nothing says what work is included — add work areas, tick services, or describe the scope.')
    if not (q.frequency or '').strip():
        gaps.append('No service frequency.')
    if not (q.contract_term or '').strip():
        gaps.append('No contract term.')
    return gaps


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
    blocking += _binding_gaps(q)
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
    elif not (q.services or '').strip() and (q.scope_notes or '').strip():
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
            q = _hold(quote_id)
            if q.locked:
                flash(_lock_message(q), 'error')
            else:
                _apply_form(q)
                db.session.commit()
        return redirect(url_for('quotes.review', quote_id=q.id))
    # Once sent, the review is of the frozen copy -- what the customer has.
    shown = quote_evidence.as_issued(q)
    brand = shown.brand or brands.brand_for_property(shown.property_type)
    from_name, from_email, reply_to = brands.send_identity(brand)
    subject, email_html = _proposal_email(shown, _quote_url(q))
    blocking, warnings = _send_checks(shown)
    return render_template(
        'admin/quote_review.html', q=shown, lead=_lead_for(q), doc_biz=branding.biz_name(),
        email_subject=subject, email_html=email_html, from_name=from_name,
        from_email=from_email, reply_to=reply_to, blocking=blocking, warnings=warnings,
        owner_email=branding.owner_email() or '', evidence=_evidence(q),
        expires_on=_day(q.expires_at), **_doc_ctx(shown))


def _evidence(q):
    """The record behind a quote: each frozen version (and whether its terms
    still match its hash), each attempt to send one, and the answer."""
    from models import QuoteRevision
    revisions = QuoteRevision.query.filter_by(quote_id=q.id).order_by(QuoteRevision.number).all()
    response = QuoteResponse.query.filter_by(quote_id=q.id).first()
    return dict(
        revisions=revisions, intact={r.id: quote_evidence.intact(r) for r in revisions},
        issued_id=q.issued_revision_id, response=response,
        response_matches=bool(response and any(r.id == response.revision_id
                                               and r.content_hash == response.content_hash
                                               for r in revisions)),
        deliveries=(QuoteDelivery.query.filter_by(quote_id=q.id)
                    .order_by(QuoteDelivery.created_at.desc()).all()),
        account=CommercialAccount.query.get(q.account_id) if q.account_id else None,
        revised_from=CommercialQuote.query.get(q.revised_from_id) if q.revised_from_id else None)


@quotes_bp.route('/<int:quote_id>/document')
@owner_required
def document(quote_id):
    """The proposal alone, on a page of its own, to print or save as a PDF --
    the copy to keep, attach, or hand over at the walkthrough."""
    shown = quote_evidence.as_issued(CommercialQuote.query.get_or_404(quote_id))
    return render_template('admin/quote_print.html', q=shown, doc_biz=branding.biz_name(), **_doc_ctx(shown))


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
    # Held from here to the last commit -- email included -- so the status
    # checked below is still the status when the email goes and when "sent"
    # is written (see _hold). A customer answering meanwhile waits a moment.
    q = _hold(quote_id)
    # Checked before touching anything: re-sending would put a signed
    # customer back to "sent" and restart the follow-up emails at somebody
    # who already said yes -- and _apply_form is a no-op on an accepted
    # quote anyway (its terms are locked), so there would be nothing of
    # this form's edits to apply even if it ran first.
    if q.status == 'accepted':
        flash('This quote was accepted — it is not sent again.', 'error')
        return redirect(url_for('quotes.review', quote_id=q.id))
    if q.status not in ('draft', 'sent'):
        # Declined or withdrawn: the customer's link says so, and stays saying
        # so. A new offer is a revision -- a new draft, a new link.
        flash(_lock_message(q), 'error')
        return redirect(url_for('quotes.review', quote_id=q.id))
    # The Send button sits in the edit form and posts it. Those edits used to
    # be dropped -- change the price, press Send, and the old price went out.
    # Only a draft takes them: a sent quote is re-sent exactly as it was.
    if 'company' in request.form and q.status == 'draft':
        _apply_form(q)
    if q.expired:
        # Its closing date is one of its terms; resending would offer, under
        # the same link, something that says it is closed. A revision is a
        # fresh offer with a fresh date.
        flash(f'This offer expired on {_day(q.expires_at)}. Revise it to send a new one.', 'error')
        return redirect(url_for('quotes.review', quote_id=q.id))
    blocking, _warnings = _send_checks(quote_evidence.as_issued(q))
    if blocking:
        db.session.commit()          # the draft's edits are kept either way
        flash('Not sent: ' + ' '.join(blocking), 'error')
        return redirect(url_for('quotes.review', quote_id=q.id))
    now = datetime.utcnow()
    by = session.get('user_name') or 'owner'
    first_send = q.status == 'draft'
    # The terms are frozen before the email is built, and the email is built
    # from the frozen copy: what goes out is byte for byte what the link shows
    # and what an acceptance is checked against. A resend sends the same
    # revision again -- or, for a quote sent before revisions existed, freezes
    # it as it stands and binds its link from now on.
    if first_send:
        q.expires_at = quote_evidence.expiry_for(q, now)
    rev = quote_evidence.issued(q) or quote_evidence.freeze(
        q, by=by, origin='issued' if first_send else 'backfill')
    shown = quote_evidence.Frozen(q, rev)
    quote_url = _quote_url(q)
    from_name, from_email, reply_to = brands.send_identity(shown.brand)
    subject, html = _proposal_email(shown, quote_url)
    ok, detail = send_email(
        to_email=shown.email, to_name=shown.contact_name,
        subject=subject,
        html=html, from_name=from_name, from_email=from_email, reply_to=reply_to,
    )
    db.session.add(QuoteDelivery(
        quote_id=q.id, revision_id=rev.id, channel='email', recipient=shown.email,
        provider='resend', provider_message_id=quote_evidence.provider_message_id(detail),
        status='accepted_by_provider' if ok else 'failed', detail=(detail or '')[:400], sent_by=by))
    if not ok:
        if first_send:
            q.expires_at = None      # still a draft: nothing was offered
        db.session.commit()          # the draft's edits, and the failed attempt, are kept
        flash(f"Quote could NOT be emailed to {q.email}. {detail}", 'error')
        return redirect(url_for('quotes.detail', quote_id=q.id))

    q.status = 'sent'
    q.issued_revision_id = rev.id
    q.sent_at = now
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
    """A draft only. Once sent, a quote is what a customer was offered -- and
    once answered, what they agreed to or turned down -- so it is kept:
    withdrawn if it should not be accepted, never erased."""
    CommercialQuote.query.get_or_404(quote_id)
    # One conditional delete, checked against the row as it is now -- not as
    # it was when this request read it, a moment before a send could commit.
    gone = (CommercialQuote.query
            .filter(CommercialQuote.id == quote_id, CommercialQuote.status.in_(CommercialQuote.EDITABLE))
            .delete(synchronize_session=False))
    if not gone:
        db.session.rollback()
        q = CommercialQuote.query.get_or_404(quote_id)
        flash(f'This quote was {q.status}, so it is kept as a record of what was offered.'
              + (' Withdraw it if it should no longer be accepted.' if q.status == 'sent' else ''), 'error')
        return redirect(url_for('quotes.detail', quote_id=q.id))
    db.session.commit()
    flash('Draft deleted.', 'success')
    return redirect(url_for('quotes.index'))


def _withdraw(q, now):
    """Sent -> withdrawn, in one conditional write: if the customer accepted
    or declined a moment ago, their answer stands and this does nothing.
    True when this call withdrew it."""
    taken = (CommercialQuote.query
             .filter(CommercialQuote.id == q.id, CommercialQuote.status == 'sent')
             .update({'status': 'withdrawn', 'withdrawn_at': now}, synchronize_session=False))
    if taken:
        q.status, q.withdrawn_at = 'withdrawn', now
    return bool(taken)


@quotes_bp.route('/<int:quote_id>/withdraw', methods=['POST'])
@owner_required
def withdraw(quote_id):
    """Take a sent offer back: its link says so and can no longer be accepted."""
    q = CommercialQuote.query.get_or_404(quote_id)
    if q.status != 'sent' or not _withdraw(q, datetime.utcnow()):
        db.session.rollback()
        q = CommercialQuote.query.get_or_404(quote_id)
        flash(f'Not withdrawn — this quote is {q.status}.', 'error')
        return redirect(url_for('quotes.detail', quote_id=quote_id))
    db.session.commit()
    flash('Withdrawn — the customer\'s link now says this proposal is no longer open.', 'success')
    return redirect(url_for('quotes.detail', quote_id=quote_id))


@quotes_bp.route('/<int:quote_id>/revise', methods=['POST'])
@owner_required
def revise(quote_id):
    """Change an offer that has gone out: a new draft with exactly the same
    terms -- not re-priced -- to edit and send, while the original stays as it
    was sent. A sent original is withdrawn in the same step, so the customer
    can't accept the old terms while the new ones are being written."""
    src = CommercialQuote.query.get_or_404(quote_id)
    if src.status not in ('sent', 'declined', 'withdrawn'):
        flash('Only a sent, declined or withdrawn quote is revised. '
              + ('Duplicate an accepted one for a new offer.' if src.status == 'accepted'
                 else 'A draft is edited directly.'), 'error')
        return redirect(url_for('quotes.detail', quote_id=src.id))
    now = datetime.utcnow()
    if src.status == 'sent' and not _withdraw(src, now):
        db.session.rollback()
        src = CommercialQuote.query.get_or_404(quote_id)
        flash(f'Not revised — the customer has just {src.status} it.', 'error')
        return redirect(url_for('quotes.detail', quote_id=src.id))
    q = CommercialQuote(
        company=src.company, contact_name=src.contact_name, email=src.email,
        phone=src.phone, property_type=src.property_type,
        property_address=src.property_address, units=src.units, sqft=src.sqft,
        services=src.services, frequency=src.frequency, contract_term=src.contract_term,
        scope_notes=src.scope_notes, token=secrets.token_urlsafe(32), status='draft',
        brand=src.brand, prospect_id=src.prospect_id, line_items=src.line_items,
        show_line_prices=src.show_line_prices, first_visit_premium=src.first_visit_premium,
        price_per_visit=src.price_per_visit, monthly_price=src.monthly_price,
        revised_from_id=src.id, account_id=src.account_id, valid_days=src.valid_days,
    )
    db.session.add(q)
    db.session.commit()
    flash('A new draft with the same terms — change what needs changing, then send it. '
          + ('The version they had is withdrawn.' if src.status == 'withdrawn' else ''), 'success')
    return redirect(url_for('quotes.detail', quote_id=q.id))


@quotes_bp.route('/<int:quote_id>/duplicate', methods=['POST'])
@owner_required
def duplicate(quote_id):
    """A fresh draft with the same company, areas and lines -- for a
    repeat proposal (annual rebid, a revised ask) without retyping the
    whole thing. Priced again at today's rates rather than copying the
    old snapshot, same as any other new quote."""
    src = CommercialQuote.query.get_or_404(quote_id)
    q = CommercialQuote(
        company=src.company, contact_name=src.contact_name, email=src.email,
        phone=src.phone, property_type=src.property_type,
        property_address=src.property_address, units=src.units, sqft=src.sqft,
        services=src.services, frequency=src.frequency, contract_term=src.contract_term,
        scope_notes=src.scope_notes, token=secrets.token_urlsafe(32), status='draft',
        brand=src.brand, prospect_id=src.prospect_id,
        show_line_prices=src.show_line_prices, first_visit_premium=src.first_visit_premium,
        price_per_visit=src.price_per_visit, monthly_price=src.monthly_price,
        account_id=src.account_id, valid_days=src.valid_days,
    )
    db.session.add(q)
    db.session.flush()
    if src.line_items:
        import json
        import commercial_pricing as cp
        try:
            areas = (json.loads(src.line_items) or {}).get('areas') or []
        except ValueError:
            areas = []
        # area_quote() takes a custom line's per-unit price as "rate" but
        # hands it back as "unit_rate" -- feeding its own output back in
        # needs the rename, or a qty x rate line silently falls back to a
        # flat, un-editable price.
        for a in areas:
            for l in (a.get('lines') or []):
                if isinstance(l, dict) and l.get('unit_rate') is not None:
                    l['rate'] = l['unit_rate']
        priced = cp.area_quote(areas, q.frequency or 'weekly', first_visit=bool(q.first_visit_premium))
        if any(a['lines'] for a in priced['areas']):
            q.line_items = json.dumps(priced)
            q.price_per_visit = priced['per_visit']
            q.monthly_price = priced['monthly']
    db.session.commit()
    flash(f'Duplicated as a new draft for {q.company} — priced at today\'s rates.', 'success')
    return redirect(url_for('quotes.detail', quote_id=q.id))


# ── Public accept / decline (no login) ────────────────────────────────────────

@quotes_bp.route('/view/<token>')
def view(token):
    q = CommercialQuote.query.filter_by(token=token).first_or_404()
    # Track the first time the contact opens it — but not the owner's own preview
    is_preview = request.args.get('preview') == '1'
    if not is_preview and q.status == 'sent' and not q.viewed_at:
        q.viewed_at = datetime.utcnow()
        db.session.commit()
    return _render_view(q)


def _render_view(q, error=None, code=200):
    """The customer's page: the terms as sent (the frozen revision, never the
    row being worked on), and Accept only while the offer is open -- sent,
    not past its date, and complete enough to agree to."""
    shown = quote_evidence.as_issued(q)
    gaps = _binding_gaps(shown) if q.status == 'sent' else []
    return render_template('public/quote_view.html', q=shown, error=error, gaps=gaps,
                           expires_on=_day(q.expires_at),
                           terms_hash=quote_evidence.shown_hash(q),
                           # The same context as the owner's review, so the two cannot drift apart.
                           **_doc_ctx(shown)), code


def _answer(q, status):
    """Sent -> accepted/declined, claimed with one conditional write so that
    of two answers arriving together (a double tap, two people at the
    company) exactly one counts -- and none after the offer's closing date,
    checked in the same write. True when this request's answer is the one."""
    now = datetime.utcnow()
    taken = (CommercialQuote.query
             .filter(CommercialQuote.id == q.id, CommercialQuote.status.in_(CommercialQuote.ANSWERABLE),
                     db.or_(CommercialQuote.expires_at.is_(None), CommercialQuote.expires_at > now))
             .update({'status': status, 'responded_at': now}, synchronize_session=False))
    if taken:
        q.status, q.responded_at = status, now
    return bool(taken)


def _notify(**kw):
    """The owner's email about an answer -- sent after it is saved, and never
    able to undo it: a mail provider having a bad minute is not a reason to
    show a customer an error for a proposal they did accept."""
    try:
        send_email(**kw)
    except Exception:
        import logging
        logging.getLogger(__name__).exception('quote answer email not sent')


def _not_recorded(q):
    """Nothing was saved: say so, and that it is safe to try again."""
    import logging
    logging.getLogger(__name__).exception('quote %s: answer not recorded', q.id)
    return render_template('public/quote_response.html', q=q, failed=True), 503


def _answerable(q):
    """None if q can be answered from this request, else the response to give:
    the page again, saying why. The posted hash must be the one the page
    showed -- the customer answers the terms they read, not whatever the
    link would show now."""
    if q.status not in CommercialQuote.ANSWERABLE or q.expired:
        return redirect(url_for('quotes.view', token=q.token))
    if _binding_gaps(quote_evidence.as_issued(q)):
        return _render_view(q, code=409)
    if (request.form.get('terms_hash') or '') != quote_evidence.shown_hash(q):
        return _render_view(q, error='This proposal has changed since you opened it. '
                                     'Please read it again before you answer.', code=409)
    return None


def _answered_revision(q):
    """The revision being answered: the one the link is bound to, or -- for a
    quote sent before revisions existed -- its terms frozen now, as the page
    just showed them (_answerable checked the hash)."""
    rev = quote_evidence.issued(q)
    if rev is None:
        rev = quote_evidence.freeze(q, origin='backfill')
        q.issued_revision_id = rev.id
    return rev


def _respond(q, decision, rev, account=None):
    """The answer's record, bound to the revision the customer was shown.
    Part of the answer's transaction: it commits with it or not at all."""
    from security import client_ip
    db.session.add(QuoteResponse(
        quote_id=q.id, revision_id=rev.id, content_hash=rev.content_hash, decision=decision,
        signer_name=(request.form.get('signer_name') or '').strip()[:120] or None,
        signer_title=(request.form.get('signer_title') or '').strip()[:120] or None,
        signer_email=quote_evidence.Frozen(q, rev).email or None,
        ip_address=client_ip(), user_agent=(request.headers.get('User-Agent') or '')[:300] or None,
        account_id=account.id if account else None))
    db.session.flush()


@quotes_bp.route('/view/<token>/accept', methods=['POST'])
def accept(token):
    """Accept a sent offer -- and only a sent one: not a draft nobody sent,
    not one withdrawn, replaced or past its date, and only the exact terms the
    page showed. The customer types their name: that, the time, their IP and
    the terms' hash are kept as the record of who agreed to what.

    All of it happens together or none of it does: the quote accepted, the
    record written, the account made or joined, the lead won. If any part
    fails, the quote is still open and the customer is told to try again,
    rather than left accepted with no account behind it. The owner is
    emailed only once it is saved."""
    q = CommercialQuote.query.filter_by(token=token).first_or_404()
    refused = _answerable(q)
    if refused:
        return refused
    if not (request.form.get('signer_name') or '').strip():
        return _render_view(q, error='Please type your full name to accept.', code=400)
    if not _answer(q, 'accepted'):
        db.session.rollback()
        return redirect(url_for('quotes.view', token=token))
    try:
        rev = _answered_revision(q)
        shown = quote_evidence.Frozen(q, rev)
        # The account is set up from the terms accepted, not the working row.
        acc = _account_from_quote(shown)   # accepted quote becomes an ongoing Commercial Account
        q.account_id = acc.id
        lead = _lead_moved(q, 'won', 'won', None, None, 'Accepted the quote 🎉')
        if lead and acc and not acc.prospect_id:
            acc.prospect_id = lead.id
        # Credit the account to whoever worked the lead, for their commission.
        linked = _lead_for(q)
        if acc and linked and linked.agent and not acc.agent:
            acc.agent = linked.agent
        _respond(q, 'accepted', rev, acc)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return _not_recorded(CommercialQuote.query.filter_by(token=token).first_or_404())
    signer = (request.form.get('signer_name') or '').strip()
    _notify(
        to_email=branding.owner_email(), to_name=branding.biz_name(),
        from_name=f'{branding.biz_name()} Quotes',
        subject=f'QUOTE ACCEPTED: {shown.company} — ${float(shown.monthly_price or 0):,.2f}/mo',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#065f46">Quote Accepted ✓</h2>
  <p><strong>{_e(signer)}</strong> at <strong>{_e(shown.company)}</strong> accepted your proposal.</p>
  <p><strong>Email:</strong> {_e(shown.email)} &nbsp; <strong>Phone:</strong> {_e(shown.phone)}</p>
  <p><strong>Property:</strong> {_e(shown.property_address)}</p>
  {'<p><strong>Monthly value:</strong> $' + f'{float(shown.monthly_price):,.2f}' + '/mo</p>' if shown.monthly_price else ''}
  <p style="font-size:0.85rem;color:#6b6585">Terms reference {rev.content_hash[:12]} (version {rev.number}).</p>
  <p>Follow up to schedule the first service and collect contract details.</p>
</div>""",
    )
    return render_template('public/quote_response.html', accepted=True, q=shown, signer=signer)


@quotes_bp.route('/view/<token>/decline', methods=['POST'])
def decline(token):
    """Decline a sent offer -- the same rules as accept(), with the name
    optional: nobody has to sign to say no."""
    q = CommercialQuote.query.filter_by(token=token).first_or_404()
    refused = _answerable(q)
    if refused:
        return refused
    if not _answer(q, 'declined'):
        db.session.rollback()
        return redirect(url_for('quotes.view', token=token))
    try:
        # A declined quote is "not now", not "never" -- the same reasoning that
        # rests a "not interested" call in nurture for a quarter.
        _lead_moved(q, 'nurture', 'not_interested', 'Quarterly check-in', 90,
                    'Declined the quote')
        rev = _answered_revision(q)
        _respond(q, 'declined', rev)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return _not_recorded(CommercialQuote.query.filter_by(token=token).first_or_404())
    shown = quote_evidence.Frozen(q, rev)
    _notify(
        to_email=branding.owner_email(), to_name=branding.biz_name(),
        from_name=f'{branding.biz_name()} Quotes',
        subject=f'Quote declined: {shown.company}',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#991b1b">Quote Declined</h2>
  <p><strong>{_e(shown.contact_name)}</strong> at <strong>{_e(shown.company)}</strong> declined your proposal.</p>
  <p>Consider following up to understand their concerns or offer an adjusted price.</p>
</div>""",
    )
    return render_template('public/quote_response.html', accepted=False, q=shown)


def _e(v):
    from markupsafe import escape
    return escape(v or '')
