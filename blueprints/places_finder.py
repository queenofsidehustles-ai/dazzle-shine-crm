"""The prospecting funnel — find businesses, call them, and keep every one of
them moving.

Search and import come from places_finder.py (the Google Places wrapper). What
happens after a call — the stage, the next action and the date it is due —
lives in prospecting.py. This module is the routes joining the two.

The default view is Today rather than everything ever imported, because a call
list that shows all two hundred rows in import order answers a question nobody
asked."""
import csv
import io
import json
from datetime import datetime, timedelta
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, Response)
from markupsafe import escape
from entitlements import requires_plan
from auth import login_required
from extensions import db
from models import Prospect
import places_finder as finder
import prospecting
from scheduling import local_today

places_finder_bp = Blueprint('places_finder', __name__, url_prefix='/find-leads')

CATEGORIES = ['property_manager', 'realtor', 'airbnb', 'apartment',
              'daycare', 'medical_office', 'general_contractor', 'office', 'other']


def _call_scripts():
    """Scripts for the call drawer, as {brand: {category: [scripts]}}.

    Rendered once per brand rather than once per prospect: the same script says
    a different company name and phone number depending on which side of the
    business is being called, and the drawer swaps them client-side so a call
    doesn't wait on a page load.
    """
    from models import Script
    import brands
    import call_scripts

    rows = Script.query.order_by(Script.sort_order, Script.id).all()
    out = {}
    for key in (brands.PRIMARY, brands.COMMERCIAL):
        vals = call_scripts.tokens(key)
        per_cat = {}
        for s in rows:
            per_cat.setdefault(s.category, []).append({
                'title': s.title,
                'content': call_scripts.render(s.content, vals),
            })
        out[key] = per_cat
    return out


def _status_counts():
    return {
        'all': Prospect.query.count(),
        'new': Prospect.query.filter_by(status='new').count(),
        'called': Prospect.query.filter_by(status='called').count(),
        'interested': Prospect.query.filter_by(status='interested').count(),
        'won': Prospect.query.filter_by(status='won').count(),
    }


def _backfilled():
    """Every prospect, with anything predating the funnel filled in.

    Done on read rather than in a migration because the app has no migration
    step that can run Python — and a prospect with no stage would otherwise sit
    invisible in a list that only shows what's due.
    """
    import brands
    rows = Prospect.query.all()
    touched = [prospecting.backfill(p) for p in list(rows)]
    touched += [brands.backfill(p, brands.brand_for_prospect) for p in list(rows)]
    if any(touched):
        db.session.commit()
    # Only the side of the business currently on screen. Done here rather than
    # in each view so Today, Pipeline and Contacts can't disagree about it.
    return brands.filter_rows(rows, brands.brand_for_prospect)


def _view_args(view, prospects, **extra):
    """Everything find_leads.html needs, whichever view is on screen."""
    from models import Script
    import brands
    live = [p for p in prospects if p.is_open]
    emails = _email_templates()
    args = dict(
        view=view,
        prospects=prospects,
        results=None,
        counts=_status_counts(),
        due=prospecting.due_counts(prospects),
        stage_counts={key: sum(1 for p in prospects if (p.stage or 'new') == key)
                      for key, _ in Prospect.STAGE_LABELS},
        stages=Prospect.STAGE_LABELS,
        live_count=len(live),
        status_filter='',
        categories=CATEGORIES,
        category_labels=Prospect.CATEGORY_LABELS,
        status_labels=Prospect.STATUS_LABELS,
        quick_actions=prospecting.QUICK_ACTIONS,
        next_rules={k: {'action': v[1], 'days': v[2]}
                    for k, v in prospecting.RULES.items()},
        max_attempts=prospecting.MAX_ATTEMPTS,
        today=local_today().isoformat(),
        demo=not finder.api_key_present(),
        search_category='property_manager',
        search_location='',
        search_brand=(brands.active() if brands.active() != brands.ALL else brands.PRIMARY),
        scripts=_call_scripts(),
        email_templates=emails,
        # Titles are the same whichever brand renders them — only the name and
        # number inside the body differ — so the picker is built from one list.
        email_template_titles=[t['title'] for t in emails[brands.PRIMARY]],
        brand_lens=brands.active(),
        brand_choices=brands.lens_choices(),
        default_brand=brands.PRIMARY,
        script_map=Script.PROSPECT_CATEGORY_MAP,
        script_always=Script.ALWAYS_SHOW,
        script_labels=dict(Script.CATEGORIES),
    )
    args.update(extra)
    return args


def _email_templates():
    """The outreach emails, ready for the drawer to pre-fill a message with.

    Subject comes off the first 'Subject:' line and the coaching note is
    dropped — useful while you're learning the script, not something to mail to
    a property manager.
    """
    from models import Script
    import brands
    import call_scripts

    rows = Script.query.filter_by(category='email_outreach') \
                       .order_by(Script.sort_order, Script.id).all()
    out = {}
    for key in (brands.PRIMARY, brands.COMMERCIAL):
        vals = call_scripts.tokens(key)
        items = []
        for s in rows:
            body = call_scripts.render(s.content, vals)
            subject = ''
            lines = []
            for line in body.split('\n'):
                if not subject and line.lower().startswith('subject:'):
                    subject = line.split(':', 1)[1].strip()
                    continue
                if line.strip().startswith('💡'):
                    continue
                lines.append(line)
            items.append({'title': s.title, 'subject': subject,
                          'body': '\n'.join(lines).strip()})
        out[key] = items
    return out


@places_finder_bp.route('/')
@login_required
@requires_plan('lead_finder')
def dashboard():
    """Today by default — what is due, not everything ever imported."""
    view = request.args.get('view', 'today')
    if view not in ('today', 'pipeline', 'contacts', 'find'):
        view = 'today'
    rows = _backfilled()

    if view == 'today':
        today = local_today().isoformat()
        shown = sorted([p for p in rows
                        if p.is_open and (not p.next_action_date
                                          or p.next_action_date <= today)],
                       key=prospecting.due_sort_key)
    elif view == 'pipeline':
        order = [k for k, _ in Prospect.STAGE_LABELS]
        shown = sorted(rows, key=lambda p: (order.index(p.stage)
                                            if p.stage in order else 99,
                                            prospecting.due_sort_key(p)))
    elif view == 'contacts':
        shown = sorted(rows, key=lambda p: (p.business_name or '').lower())
    else:
        shown = sorted(rows, key=prospecting.due_sort_key)

    return render_template('admin/find_leads.html', **_view_args(view, rows, shown=shown))


@places_finder_bp.route('/search', methods=['POST'])
@login_required
def search():
    import brands
    category = request.form.get('category', 'property_manager')
    # Which side of the business this batch is being hunted for. Carried
    # through to the import so it is recorded from the search rather than
    # reverse-engineered from the category afterwards.
    picked_brand = brands.normalize_lens(request.form.get('brand'))
    if picked_brand == brands.ALL:
        picked_brand = brands.PRIMARY
    location = request.form.get('location', '').strip()
    if not location:
        flash('Enter a city or area to search — a town and state.', 'error')
        return redirect(url_for('places_finder.dashboard'))

    demo = not finder.api_key_present()
    if demo:
        results, error = finder.demo_listings(category, location), ''
    else:
        ok, results, error = finder.search_businesses(category, location)
        if not ok:
            flash(f'Search failed: {error}', 'error')
            results = []

    # Flag which results are already in the call list (so we don't double-add).
    existing_ids = {p.place_id for p in Prospect.query.with_entities(Prospect.place_id).all()}
    for r in results:
        r['already'] = r['place_id'] in existing_ids
        r['category'] = category

    rows = _backfilled()
    return render_template('admin/find_leads.html',
                           **_view_args('find', rows,
                                        shown=sorted(rows, key=prospecting.due_sort_key),
                                        results=results, demo=demo,
                                        search_category=category,
                                        search_brand=picked_brand,
                                        search_location=location))


@places_finder_bp.route('/import', methods=['POST'])
@login_required
def import_selected():
    import brands
    selected = request.form.getlist('selected')
    # Recorded from the search that found them rather than worked out later.
    # The category alone is not enough: "property management" turned out to be
    # residential managers buying turnover cleaning, not commercial janitorial.
    picked_brand = brands.normalize_lens(request.form.get('brand'))
    added = 0
    for pid in selected:
        raw = request.form.get(f'payload_{pid}')
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        # De-dupe by Google place id (falls back to name+city for demo rows).
        exists = None
        if data.get('place_id'):
            exists = Prospect.query.filter_by(place_id=data['place_id']).first()
        if not exists:
            exists = Prospect.query.filter_by(
                business_name=data.get('business_name'), city=data.get('city')
            ).first()
        if exists:
            continue
        db.session.add(Prospect(
            business_name=data.get('business_name', 'Unknown'),
            category=data.get('category', 'property_manager'),
            phone=data.get('phone', ''),
            website=data.get('website', ''),
            address=data.get('address', ''),
            city=data.get('city', ''),
            rating=data.get('rating'),
            place_id=data.get('place_id', ''),
            status='new',
            source='google_places',
            # ALL means the search wasn't run under one brand, so fall back to
            # working it out from the category rather than storing "all".
            brand=(picked_brand if picked_brand != brands.ALL
                   else brands.brand_for_prospect(data)),
        ))
        added += 1
    db.session.commit()
    flash(f'Added {added} business{"es" if added != 1 else ""} to your call list.', 'success')
    return redirect(url_for('places_finder.dashboard'))


@places_finder_bp.route('/<int:prospect_id>/status', methods=['POST'])
@login_required
def update_status(prospect_id):
    p = Prospect.query.get_or_404(prospect_id)
    new_status = request.form.get('status')
    logged = request.form.get('mode') == 'log'

    if new_status in Prospect.STATUS_LABELS:
        p.status = new_status
        if new_status != 'new' and not p.called_at:
            p.called_at = datetime.utcnow()

    if logged:
        # Details worth having as fields rather than buried in prose: you can't
        # email a note, and "call them before the renewal" needs a date.
        for field, attr in (('contact', 'contact_name'), ('email', 'email'),
                            ('renewal', 'renewal_note')):
            val = (request.form.get(field) or '').strip()
            if val:
                setattr(p, attr, val)

        # Each save prepends a dated entry instead of overwriting, so the
        # renewal date and what they actually said survive the next call.
        p.notes = _prepend_log(p, request.form)

        # Where they are now, and what happens next. A blank action here means
        # the caller took the suggestion; an explicit one overrules it.
        prospecting.apply_outcome(
            p, new_status,
            next_action=(request.form.get('next_action') or '').strip() or None,
            next_action_date=(request.form.get('next_action_date') or '').strip() or None,
        )
    elif 'notes' in request.form:
        # The quick inline edit in the table still replaces outright.
        p.notes = request.form.get('notes', '')

    db.session.commit()
    if logged:
        if p.next_action and p.next_action_date:
            when = 'today' if p.next_action_date == local_today().isoformat() \
                else f'on {p.next_action_date}'
            flash(f'Logged. Next: {p.next_action} — {when}.', 'success')
        else:
            flash(f'Logged. {p.business_name} is closed for now.', 'success')
    else:
        flash('Call list updated.', 'success')
    return redirect(url_for('places_finder.dashboard', view=request.args.get('view', 'today')))


@places_finder_bp.route('/<int:prospect_id>/snooze', methods=['POST'])
@login_required
def snooze(prospect_id):
    """Push a due prospect out without pretending a call happened.

    Without this the only way to clear something off Today is to log a call you
    didn't make, which puts a lie in the notes and inflates the attempt count.
    """
    p = Prospect.query.get_or_404(prospect_id)
    try:
        days = max(1, min(365, int(request.form.get('days', 3))))
    except (TypeError, ValueError):
        days = 3
    p.next_action = p.next_action or 'Follow-up call'
    p.next_action_date = (local_today() + timedelta(days=days)).isoformat()
    db.session.commit()
    flash(f'{p.business_name} moved to {p.next_action_date}.', 'success')
    return redirect(url_for('places_finder.dashboard', view=request.args.get('view', 'today')))


@places_finder_bp.route('/<int:prospect_id>/email', methods=['POST'])
@login_required
def send_outreach(prospect_id):
    """Send one of the outreach emails to a prospect and log it as a touch."""
    p = Prospect.query.get_or_404(prospect_id)
    subject = (request.form.get('subject') or '').strip()
    body = (request.form.get('body') or '').strip()
    to = (request.form.get('email') or p.email or '').strip()
    view = request.args.get('view', 'today')

    if not to:
        flash('No email address for this business yet — ask for one on the call.', 'error')
        return redirect(url_for('places_finder.dashboard', view=view))
    if not subject or not body:
        flash('The email needs a subject and a body.', 'error')
        return redirect(url_for('places_finder.dashboard', view=view))

    p.email = to
    from notifications import send_email
    import brands
    from_name, from_email, reply_to = brands.send_identity(brands.COMMERCIAL)
    html = ('<div style="font-family:Inter,Arial,sans-serif;font-size:15px;'
            'line-height:1.65;color:#1f1333;white-space:pre-wrap">'
            + escape(body) + '</div>')
    ok, detail = send_email(to, p.contact_name or p.business_name, subject, html,
                            from_name=from_name, from_email=from_email,
                            reply_to=reply_to)

    if ok:
        p.last_emailed_at = datetime.utcnow()
        p.notes = _prepend_entry(p, f'Emailed — {subject}')
        if p.stage in (None, 'new'):
            p.stage = 'working'
        # An email is a touch like any other: it earns a follow-up date, or it
        # is just another thing sent into a void.
        p.next_action = 'Follow up on the email'
        p.next_action_date = (local_today() + timedelta(days=4)).isoformat()
        db.session.commit()
        flash(f'Sent to {to}. Follow up {p.next_action_date}.', 'success')
    else:
        db.session.commit()
        flash(f'Could not send: {detail}', 'error')
    return redirect(url_for('places_finder.dashboard', view=view))


@places_finder_bp.route('/export.csv')
@login_required
def export_csv():
    """The whole call list as a spreadsheet — every contact detail and where
    each one is in the funnel. Hers to keep, and the thing to hand a VA."""
    rows = _backfilled()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['Business', 'Category', 'Stage', 'Last outcome', 'Attempts',
                'Contact', 'Phone', 'Email', 'Website', 'Address', 'City',
                'Rating', 'Next action', 'Next action date', 'Contract renewal',
                'Last called', 'Last emailed', 'Added', 'Notes'])
    for p in sorted(rows, key=lambda x: (x.business_name or '').lower()):
        w.writerow([
            p.business_name, p.category_label, p.stage_label, p.status_label,
            p.attempts or 0, p.contact_name or '', p.phone or '', p.email or '',
            p.website or '', p.address or '', p.city or '',
            f'{p.rating:.1f}' if p.rating else '',
            p.next_action or '', p.next_action_date or '', p.renewal_note or '',
            p.called_at.strftime('%Y-%m-%d') if p.called_at else '',
            p.last_emailed_at.strftime('%Y-%m-%d') if p.last_emailed_at else '',
            p.created_at.strftime('%Y-%m-%d') if p.created_at else '',
            (p.notes or '').replace('\r', ' '),
        ])
    stamp = local_today().isoformat()
    return Response(buf.getvalue(), mimetype='text/csv', headers={
        'Content-Disposition': f'attachment; filename=call-list-{stamp}.csv'})


def _prepend_entry(prospect, header):
    """One dated line above the existing notes."""
    from scheduling import local_now
    stamp = local_now().strftime('[%b %d] ')
    return (stamp + header + '\n\n' + (prospect.notes or '')).strip()


def _prepend_log(prospect, form):
    """Build one dated call-log entry and put it above the existing notes."""
    from scheduling import local_now

    facts = []
    if form.get('contact', '').strip():
        facts.append('Contact: ' + form['contact'].strip())
    if form.get('renewal', '').strip():
        facts.append('Renewal: ' + form['renewal'].strip())
    if form.get('sqft', '').strip():
        facts.append('Size: ' + form['sqft'].strip())

    header = local_now().strftime('[%b %d] ') + Prospect.STATUS_LABELS.get(
        prospect.status, prospect.status or 'New')
    if facts:
        header += ' · ' + ' · '.join(facts)

    entry = header
    body = form.get('log_note', '').strip()
    if body:
        entry += '\n' + body

    return (entry + '\n\n' + (prospect.notes or '')).strip()


@places_finder_bp.route('/<int:prospect_id>/delete', methods=['POST'])
@login_required
def delete(prospect_id):
    p = Prospect.query.get_or_404(prospect_id)
    db.session.delete(p)
    db.session.commit()
    flash('Removed from call list.', 'success')
    return redirect(url_for('places_finder.dashboard'))
