import os
import secrets
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for
from models import BookingRating
from extensions import db

ratings_bp = Blueprint('ratings', __name__, url_prefix='/rate')


def _alert_low_rating(r):
    """Email the owner when a customer rates below 4 stars, so they can make it right."""
    if not r.rating or r.rating >= 4:
        return
    try:
        from models import BusinessSetting
        from notifications import send_triggered_email
        owner = (BusinessSetting.get('email') or os.environ.get('OWNER_EMAIL')
                 or os.environ.get('NOTIFY_EMAIL', 'dazzleandshinemaids@gmail.com'))
        b = r.booking
        send_triggered_email('owner_low_rating', owner, 'Dazzle & Shine', {
            'client_name': (b.name if b else '') or 'A customer',
            'stars': r.rating,
            'comment': r.comment or '—',
        })
    except Exception:
        pass


@ratings_bp.route('/<token>/<int:stars>')
def submit(token, stars):
    r = BookingRating.query.filter_by(token=token).first_or_404()
    if r.rated_at:
        return render_template('public/rate_done.html', r=r)
    if stars < 1 or stars > 5:
        return redirect(url_for('ratings.page', token=token))
    r.rating = stars
    r.rated_at = datetime.utcnow()
    comment = request.args.get('comment', '').strip()
    if comment:
        r.comment = comment
    db.session.commit()
    _alert_low_rating(r)
    return render_template('public/rate_done.html', r=r, just_rated=True)


@ratings_bp.route('/<token>', methods=['GET', 'POST'])
def page(token):
    r = BookingRating.query.filter_by(token=token).first_or_404()
    if r.rated_at:
        return render_template('public/rate_done.html', r=r)
    if request.method == 'POST':
        stars = int(request.form.get('stars', 0))
        if 1 <= stars <= 5:
            r.rating = stars
            r.comment = request.form.get('comment', '').strip()
            r.rated_at = datetime.utcnow()
            db.session.commit()
            _alert_low_rating(r)
            return render_template('public/rate_done.html', r=r, just_rated=True)
    return render_template('public/rate.html', r=r)
