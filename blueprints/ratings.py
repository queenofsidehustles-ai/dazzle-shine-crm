import secrets
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for
from models import BookingRating
from extensions import db

ratings_bp = Blueprint('ratings', __name__, url_prefix='/rate')


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
            return render_template('public/rate_done.html', r=r, just_rated=True)
    return render_template('public/rate.html', r=r)
