"""Big Fish Finder routes — search public business listings and build a call
list of Prospects for the VA to phone. See places_finder.py (service) for the
Google Places wrapper."""
import json
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth import login_required
from extensions import db
from models import Prospect
import places_finder as finder

places_finder_bp = Blueprint('places_finder', __name__, url_prefix='/find-leads')

CATEGORIES = ['property_manager', 'realtor', 'airbnb', 'apartment',
              'daycare', 'medical_office', 'office', 'other']


def _status_counts():
    return {
        'all': Prospect.query.count(),
        'new': Prospect.query.filter_by(status='new').count(),
        'called': Prospect.query.filter_by(status='called').count(),
        'interested': Prospect.query.filter_by(status='interested').count(),
        'won': Prospect.query.filter_by(status='won').count(),
    }


@places_finder_bp.route('/')
@login_required
def dashboard():
    status_filter = request.args.get('status', '')
    q = Prospect.query.order_by(Prospect.created_at.desc())
    if status_filter:
        q = q.filter_by(status=status_filter)
    prospects = q.all()
    return render_template(
        'admin/find_leads.html',
        prospects=prospects,
        results=None,
        counts=_status_counts(),
        status_filter=status_filter,
        categories=CATEGORIES,
        category_labels=Prospect.CATEGORY_LABELS,
        status_labels=Prospect.STATUS_LABELS,
        demo=not finder.api_key_present(),
        search_category='property_manager',
        search_location='',
    )


@places_finder_bp.route('/search', methods=['POST'])
@login_required
def search():
    category = request.form.get('category', 'property_manager')
    location = request.form.get('location', '').strip()
    if not location:
        flash('Enter a city or area to search (e.g. "Orlando, FL").', 'error')
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

    return render_template(
        'admin/find_leads.html',
        prospects=Prospect.query.order_by(Prospect.created_at.desc()).all(),
        results=results,
        counts=_status_counts(),
        status_filter='',
        categories=CATEGORIES,
        category_labels=Prospect.CATEGORY_LABELS,
        status_labels=Prospect.STATUS_LABELS,
        demo=demo,
        search_category=category,
        search_location=location,
    )


@places_finder_bp.route('/import', methods=['POST'])
@login_required
def import_selected():
    selected = request.form.getlist('selected')
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
    if new_status in Prospect.STATUS_LABELS:
        p.status = new_status
        if new_status in ('called', 'no_answer', 'callback', 'interested', 'not_interested', 'won') and not p.called_at:
            p.called_at = datetime.utcnow()
    if 'notes' in request.form:
        p.notes = request.form.get('notes', '')
    db.session.commit()
    flash('Call list updated.', 'success')
    return redirect(url_for('places_finder.dashboard', status=request.args.get('status', '')))


@places_finder_bp.route('/<int:prospect_id>/delete', methods=['POST'])
@login_required
def delete(prospect_id):
    p = Prospect.query.get_or_404(prospect_id)
    db.session.delete(p)
    db.session.commit()
    flash('Removed from call list.', 'success')
    return redirect(url_for('places_finder.dashboard'))
