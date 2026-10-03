"""Short-term rentals: the properties we watch, and the turnovers they produce.

The host pastes the iCal link their listing already publishes; everything after
that is automatic. The screen's job is to make two things obvious — which feeds
are being read, and which turnovers are same-day — because those are the two
ways this goes wrong in a way somebody notices.
"""
from datetime import date, datetime

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, abort)

from auth import login_required
from extensions import db
from models import RentalProperty, RentalTurnover, Client
import rentals

rentals_bp = Blueprint('rentals', __name__, url_prefix='/rentals')


@rentals_bp.route('/')
@login_required
def index():
    props = RentalProperty.query.order_by(RentalProperty.name).all()
    today = date.today().isoformat()
    upcoming = (RentalTurnover.query
                .filter(RentalTurnover.checkout_on >= today)
                .order_by(RentalTurnover.checkout_on)
                .limit(60).all())
    return render_template('admin/rentals.html', props=props, upcoming=upcoming,
                           clients=Client.query.order_by(Client.name).limit(500).all(),
                           today=today)


@rentals_bp.route('/add', methods=['POST'])
@login_required
def add():
    url = (request.form.get('ical_url') or '').strip()
    name = (request.form.get('name') or '').strip()
    if not url or not name:
        flash('A name and the calendar link are both needed.', 'error')
        return redirect(url_for('rentals.index'))
    if not url.lower().startswith(('http://', 'https://', 'webcal://')):
        flash('That does not look like a calendar link. Copy it from the listing '
              'and paste the whole thing.', 'error')
        return redirect(url_for('rentals.index'))
    # webcal:// is just https with a different coat on.
    if url.lower().startswith('webcal://'):
        url = 'https://' + url[9:]

    cid = (request.form.get('client_id') or '').strip()
    price = (request.form.get('price') or '').strip()
    p = RentalProperty(
        name=name[:120], ical_url=url[:600],
        client_id=int(cid) if cid.isdigit() else None,
        address=(request.form.get('address') or '').strip()[:200],
        city=(request.form.get('city') or '').strip()[:80],
        zip_code=(request.form.get('zip_code') or '').strip()[:10],
        service_type=(request.form.get('service_type') or 'standard')[:50],
        clean_time=(request.form.get('clean_time') or '11:00 AM')[:20],
        price=float(price) if price.replace('.', '', 1).isdigit() else None,
        is_active=True, created_at=datetime.utcnow())
    db.session.add(p)
    db.session.commit()

    made, _skipped, err = rentals.sync_property(p)
    if err:
        flash(f'Added, but the calendar could not be read: {err}', 'error')
    else:
        flash(f'{p.name} added — {made} turnover{"s" if made != 1 else ""} booked in.',
              'success')
    return redirect(url_for('rentals.index'))


@rentals_bp.route('/<int:pid>/sync', methods=['POST'])
@login_required
def sync_one(pid):
    p = RentalProperty.query.get_or_404(pid)
    made, skipped, err = rentals.sync_property(p)
    if err:
        flash(f'Could not read that calendar: {err}', 'error')
    else:
        flash(f'{p.name}: {made} new, {skipped} already booked.', 'success')
    return redirect(url_for('rentals.index'))


@rentals_bp.route('/<int:pid>/toggle', methods=['POST'])
@login_required
def toggle(pid):
    p = RentalProperty.query.get_or_404(pid)
    p.is_active = not p.is_active
    db.session.commit()
    flash(f'{p.name} is {"on" if p.is_active else "paused"}.', 'success')
    return redirect(url_for('rentals.index'))


@rentals_bp.route('/<int:pid>/delete', methods=['POST'])
@login_required
def delete(pid):
    p = RentalProperty.query.get_or_404(pid)
    # The jobs already created stay. Somebody is cleaning that flat on Tuesday
    # whether or not we are still reading the calendar.
    RentalTurnover.query.filter_by(property_id=p.id).delete()
    db.session.delete(p)
    db.session.commit()
    flash('Property removed. Jobs already on the calendar were left alone.', 'success')
    return redirect(url_for('rentals.index'))
