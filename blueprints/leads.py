from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth import login_required, owner_required
from models import Lead, Booking, Client, User
from extensions import db
from pricing import get_deposit
import entitlements

leads_bp = Blueprint('leads', __name__, url_prefix='/leads')


@leads_bp.route('/')
@login_required
def index():
    import brands
    status_filter = request.args.get('status', '')

    # Give anything predating the brand split a brand once, from its service
    # type, so the answer is stored and correctable rather than re-guessed on
    # every page load.
    everything = Lead.query.order_by(Lead.created_at.desc()).all()
    if any(brands.backfill(l, brands.brand_for_lead) for l in everything):
        db.session.commit()

    # Counts describe the brand you are looking at, not the whole database —
    # a tab reading "New (14)" that shows four rows is worse than no count.
    in_brand = brands.filter_rows(everything, brands.brand_for_lead)
    counts = {
        'all': len(in_brand),
        'new': sum(1 for l in in_brand if l.status == 'new'),
        'contacted': sum(1 for l in in_brand if l.status == 'contacted'),
        'converted': sum(1 for l in in_brand if l.status == 'converted'),
        'lost': sum(1 for l in in_brand if l.status == 'lost'),
    }
    leads = [l for l in in_brand if not status_filter or l.status == status_filter]
    return render_template('admin/leads.html', leads=leads, counts=counts, status_filter=status_filter)


@leads_bp.route('/quote/new', methods=['GET', 'POST'])
@login_required
def new_quote():
    """Quote someone who rang, without needing them to be in a CSV first.

    Most callers can be quoted straight off the Google Ads screen, but not every
    caller is on it — the export is downloaded now and then, and people ring the
    number directly. Waiting for the next import to quote somebody who is on the
    phone right now would make the import the point, when the quote is."""
    import quoting
    from flask import request
    if request.method == 'POST':
        lead, err = quoting.handle_quote_form(request.form)
        if err:
            flash(err, 'warning')
            return redirect(url_for('leads.new_quote'))
        # If they happen to be in the Google Ads list, tie the two together so
        # she isn't looking at the same person in two places.
        linked = quoting.link_lsa_caller(lead)
        prospect = _prospect(request.form.get('prospect_id', type=int))
        if prospect:
            lead.prospect_id = prospect.id
            db.session.commit()
        for msg, level in quoting.deliver_quote(
                lead, also_text=bool(request.form.get('also_text'))):
            flash(msg, level)
        if linked:
            flash('Matched to their Google Ads call, so the follow-up texts '
                  'for people we never reached have stopped.', 'success')
        if prospect and quoting.was_delivered(lead):
            import prospecting
            prospecting.quote_moved(
                prospect.id, 'proposal', None, 'Follow up on the quote', 3,
                f'Residential quote ${float(lead.quoted_price or 0):,.2f} sent to {lead.email}')
            prospect.contact_name = prospect.contact_name or lead.name or None
            prospect.email = prospect.email or lead.email or None
            db.session.commit()
            return redirect(url_for('places_finder.dashboard', view='everyone'))
        return redirect(url_for('leads.index') if quoting.was_delivered(lead)
                        else url_for('leads.new_quote', prospect_id=prospect.id if prospect else None))

    # Started from a residential lead on the call list -- a property manager
    # buying turnovers, a realtor's listings, an Airbnb host. Fill in what the
    # call list already knows rather than make somebody copy it across.
    prospect = _prospect(request.args.get('prospect_id', type=int))
    pre = {}
    if prospect:
        pre = {
            'name': prospect.contact_name or prospect.business_name,
            'email': prospect.email or '', 'phone': prospect.phone or '',
            'address': prospect.address or '', 'city': prospect.city or '',
            'service_type': _RESIDENTIAL_SERVICE.get(prospect.category, 'standard'),
            'notes': f'For {prospect.business_name}' if prospect.contact_name else '',
        }
    return render_template('admin/lsa_quote.html', lead=None, existing=None,
                           prospect=prospect, pre=pre, **quoting.form_context())


# What a residential lead on the call list is most likely buying. A starting
# point for the service picker, nothing more: she changes it on the form.
_RESIDENTIAL_SERVICE = {
    'property_manager': 'moveout',
    'apartment': 'moveout',
    'realtor': 'moveout',
    'airbnb': 'standard',
    'general_contractor': 'postcon_clean',
}


def _prospect(prospect_id):
    from models import Prospect
    return Prospect.query.get(prospect_id) if prospect_id else None


@leads_bp.route('/checklist.json')
@login_required
def checklist_json():
    """The standard checklist for a service, so the quote form can swap the
    tick-list when the service changes without a page reload."""
    from flask import jsonify, request
    import quoting
    return jsonify({'items': quoting.service_checklist(
        request.args.get('service_type', ''))})


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
    import quoting
    vas = User.query.filter_by(role='team').order_by(User.name).all()
    # Only a lead that was actually quoted has a link worth showing -- quote_url
    # falls back to the generic booking form, which is not this lead's quote.
    return render_template('admin/lead_detail.html', lead=lead, vas=vas,
                           quote_link=quoting.quote_url(lead) if lead.quote_token else '')


@leads_bp.route('/<int:lead_id>/convert', methods=['POST'])
@login_required
def convert(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    # Same ceiling as a job typed in by hand — converting a lead is still a job.
    ok, why = entitlements.check_limit('jobs_per_month')
    if not ok:
        flash(why, 'error')
        return redirect(url_for('leads.detail', lead_id=lead_id))
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
        balance_due=max(0, (lead.quoted_price or 0) - get_deposit()),
        status='pending',
        source=lead.source,
        agent=lead.agent,
    )
    db.session.add(booking)
    lead.status = 'converted'
    import prospecting
    prospecting.quote_moved(lead.prospect_id, 'won', 'won', None, None,
                            'Booked from the residential quote 🎉')
    db.session.commit()
    flash('Lead converted to booking!', 'success')
    return redirect(url_for('bookings.detail', booking_id=booking.id))


@leads_bp.route('/<int:lead_id>/send-copy', methods=['POST'])
@login_required
def send_copy(lead_id):
    """Email this quote to somebody other than the lead.

    On a post-construction job the person who rang is the builder and the
    person paying is often the homeowner. Before this, the only way to get the
    quote to the second one was to re-send the form against their address,
    which moved the lead's own quote onto them."""
    import quoting
    lead = Lead.query.get_or_404(lead_id)
    to_email = (request.form.get('copy_email') or '').strip()
    ok, err = quoting.send_quote_copy(
        lead, to_email, request.form.get('copy_name') or '')
    if ok:
        flash(f'Copy of the quote sent to {to_email}. '
              f'{lead.name} was not emailed again.', 'success')
    else:
        flash(err, 'warning')
    return redirect(url_for('leads.detail', lead_id=lead_id))


@leads_bp.route('/<int:lead_id>/delete', methods=['POST'])
@owner_required
def delete(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    db.session.delete(lead)
    db.session.commit()
    flash('Lead deleted.', 'success')
    return redirect(url_for('leads.index'))
