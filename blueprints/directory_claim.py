"""Claiming a directory listing on getakye.com.

The directory is 60,000-odd cleaning companies built from public records, one
page each, and the page is what outreach links to: "here is your listing, some
of it is wrong, fix it". Claiming is the moment a stranger becomes a lead, so
it lands here rather than on the static site — a claimed listing that doesn't
become an Akye account is a wasted lead, and the account lives in this app.

Routes sit under /listing/ on purpose. `claims.py` already owns
/claim/<ctoken>/<stoken>, the link a cleaner taps to take a job, and a rule like
/claim/verify/<token> would sit close enough to that to be worth nobody's time
debugging later.

Verification only works when the public record already holds a contact detail —
about 43% of listings. For the rest there is nothing to check an answer against,
so the claim is queued for a human instead of pretending. Those are also the
best prospects: a business with no email listed is the one losing work to
whoever answered first.

Nothing here writes to a cleaning company's own data. Two new tables, no
existing table touched.
"""
import csv
import re
import secrets
from datetime import datetime, timedelta

from flask import (Blueprint, render_template, request, abort, url_for,
                   redirect, flash, current_app)

from auth import login_required
from extensions import db
from notifications import send_email
import product

directory_bp = Blueprint('directory', __name__)

CODE_TTL = timedelta(minutes=30)
MAX_ATTEMPTS = 5


# ── the two tables ──────────────────────────────────────────────────────────
class DirectoryListing(db.Model):
    """One public-record cleaning company. `id` is the Overture place id, so a
    re-import updates a row rather than duplicating it."""
    __tablename__ = 'directory_listing'
    id = db.Column(db.String(64), primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    city = db.Column(db.String(100))
    state = db.Column(db.String(2), index=True)
    email = db.Column(db.String(200))
    phone = db.Column(db.String(40))
    url = db.Column(db.String(400))
    visibility = db.Column(db.Integer, default=0)
    claimed_at = db.Column(db.DateTime)
    claimed_by = db.Column(db.String(200))

    @property
    def is_claimed(self):
        return self.claimed_at is not None


class DirectoryClaim(db.Model):
    """Somebody saying a listing is theirs, and how far they got proving it."""
    __tablename__ = 'directory_claim'
    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.String(64), index=True)
    listing_name = db.Column(db.String(200))
    name = db.Column(db.String(120))
    email = db.Column(db.String(200), index=True)
    phone = db.Column(db.String(40))
    note = db.Column(db.String(500))
    # 'sent'     — code emailed, waiting on them
    # 'review'   — nothing on record to verify against, a human decides
    # 'verified' — proved it
    # 'expired'  — too many wrong codes, or too slow
    status = db.Column(db.String(20), default='review', index=True)
    code = db.Column(db.String(6))
    code_sent_at = db.Column(db.DateTime)
    attempts = db.Column(db.Integer, default=0)
    token = db.Column(db.String(64), unique=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    verified_at = db.Column(db.DateTime)


# ── helpers ─────────────────────────────────────────────────────────────────
def _norm_email(v):
    return (v or '').strip().lower()


def _norm_phone(v):
    return re.sub(r'\D', '', v or '')[-10:]


def _matches_record(listing, email, phone):
    """True when what they typed matches what the public record already holds.
    Last ten digits for phone, so +1 and punctuation don't decide a claim."""
    if not listing:
        return False
    if listing.email and _norm_email(listing.email) == _norm_email(email):
        return True
    if listing.phone and phone and _norm_phone(listing.phone) == _norm_phone(phone):
        return True
    return False


def _send_code(claim, listing):
    claim.code = f"{secrets.randbelow(1000000):06d}"
    claim.code_sent_at = datetime.utcnow()
    claim.status = 'sent'
    claim.attempts = 0
    db.session.commit()
    link = url_for('directory.verify', token=claim.token, _external=True)
    send_email(
        to_email=listing.email or claim.email,
        to_name=claim.name or listing.name,
        subject=f"Your code to claim {listing.name}",
        html=(f"<p>Somebody asked to claim the listing for <strong>{listing.name}"
              f"</strong> on getakye.com.</p>"
              f"<p style='font-size:28px;font-weight:700;letter-spacing:.15em'>"
              f"{claim.code}</p>"
              f"<p>Enter it here: <a href='{link}'>{link}</a><br>"
              f"The code works for the next 30 minutes.</p>"
              f"<p>If this wasn't you, ignore this email and nothing changes.</p>"),
        from_name="Akye",
        api_key=product.resend_api_key() or None)


# ── the flow ────────────────────────────────────────────────────────────────
@directory_bp.route('/listing/claim', methods=['GET', 'POST'])
def claim_start():
    """Where the button on a getakye.com listing page lands."""
    listing_id = (request.values.get('listing_id') or '').strip()
    listing = DirectoryListing.query.get(listing_id) if listing_id else None
    if not listing:
        # A listing we don't hold yet shouldn't be a dead end — take the details
        # and let a human sort it out.
        return render_template('directory/claim_form.html', listing=None,
                               listing_name=request.values.get('listing_name', ''),
                               listing_id=listing_id)
    if listing.is_claimed:
        return render_template('directory/already.html', listing=listing)
    return render_template('directory/claim_form.html', listing=listing,
                           listing_name=listing.name, listing_id=listing.id)


@directory_bp.route('/listing/claim/submit', methods=['POST'])
def claim_submit():
    listing_id = (request.form.get('listing_id') or '').strip()
    listing = DirectoryListing.query.get(listing_id) if listing_id else None
    email = _norm_email(request.form.get('email'))
    if not email:
        flash('An email address is needed to claim a listing.', 'error')
        return redirect(url_for('directory.claim_start', listing_id=listing_id))

    claim = DirectoryClaim(
        listing_id=listing_id,
        listing_name=(listing.name if listing else request.form.get('listing_name')),
        name=(request.form.get('name') or '').strip(),
        email=email,
        phone=(request.form.get('phone') or '').strip(),
        note=(request.form.get('note') or '').strip()[:500],
        token=secrets.token_urlsafe(32))
    db.session.add(claim)
    db.session.commit()

    if listing and _matches_record(listing, email, claim.phone):
        _send_code(claim, listing)
        return redirect(url_for('directory.verify', token=claim.token))

    claim.status = 'review'
    db.session.commit()
    return render_template('directory/queued.html', claim=claim)


@directory_bp.route('/listing/verify/<token>', methods=['GET', 'POST'])
def verify(token):
    claim = DirectoryClaim.query.filter_by(token=token).first_or_404()
    listing = DirectoryListing.query.get(claim.listing_id)

    if claim.status == 'verified':
        return render_template('directory/done.html', claim=claim, listing=listing)
    if claim.status != 'sent':
        return render_template('directory/queued.html', claim=claim)

    stale = (claim.code_sent_at or datetime.utcnow()) + CODE_TTL < datetime.utcnow()
    if stale or (claim.attempts or 0) >= MAX_ATTEMPTS:
        claim.status = 'expired'
        db.session.commit()
        return render_template('directory/expired.html', claim=claim)

    if request.method == 'POST':
        given = re.sub(r'\D', '', request.form.get('code') or '')
        if claim.code and secrets.compare_digest(given, claim.code):
            claim.status = 'verified'
            claim.verified_at = datetime.utcnow()
            if listing:
                listing.claimed_at = claim.verified_at
                listing.claimed_by = claim.email
            db.session.commit()
            return render_template('directory/done.html', claim=claim, listing=listing)
        claim.attempts = (claim.attempts or 0) + 1
        db.session.commit()
        left = MAX_ATTEMPTS - claim.attempts
        flash(f"That code didn't match. {left} tr{'y' if left == 1 else 'ies'} left."
              if left > 0 else "That's too many tries.", 'error')

    return render_template('directory/verify.html', claim=claim, listing=listing)


# ── the queue the owner actually works ──────────────────────────────────────
@directory_bp.route('/admin/listings/claims')
@login_required
def claims_queue():
    status = request.args.get('status') or 'review'
    q = DirectoryClaim.query
    if status != 'all':
        q = q.filter_by(status=status)
    claims = q.order_by(DirectoryClaim.created_at.desc()).limit(300).all()
    counts = dict(db.session.query(DirectoryClaim.status,
                                   db.func.count(DirectoryClaim.id))
                  .group_by(DirectoryClaim.status).all())
    return render_template('directory/queue.html', claims=claims,
                           counts=counts, status=status)


@directory_bp.route('/admin/listings/claims/<int:claim_id>/approve', methods=['POST'])
@login_required
def approve_claim(claim_id):
    claim = DirectoryClaim.query.get_or_404(claim_id)
    claim.status = 'verified'
    claim.verified_at = datetime.utcnow()
    listing = DirectoryListing.query.get(claim.listing_id)
    if listing:
        listing.claimed_at = claim.verified_at
        listing.claimed_by = claim.email
    db.session.commit()
    flash(f'{claim.listing_name} marked claimed by {claim.email}.', 'success')
    return redirect(url_for('directory.claims_queue'))


# ── loading the directory in ────────────────────────────────────────────────
@directory_bp.cli.command('import-listings')
def import_listings():
    """flask directory import-listings < data/fl_urls.csv

    Re-running updates rows in place — the Overture id is the key — so a refreshed
    export never duplicates a listing or drops who claimed it."""
    import sys
    added = updated = 0
    for row in csv.DictReader(sys.stdin):
        lid = (row.get('id') or '').strip()
        if not lid:
            continue
        rec = DirectoryListing.query.get(lid)
        if rec is None:
            rec = DirectoryListing(id=lid)
            db.session.add(rec)
            added += 1
        else:
            updated += 1
        rec.name = (row.get('name') or '')[:200]
        rec.city = (row.get('city') or '')[:100]
        rec.state = (row.get('state') or row.get('url', '').split('/')[3][:2].upper())[:2]
        rec.email = (row.get('email') or None)
        rec.phone = (row.get('phone') or None)
        rec.url = (row.get('url') or None)
        try:
            rec.visibility = int(row.get('visibility') or 0)
        except ValueError:
            rec.visibility = 0
    db.session.commit()
    print(f'{added} added, {updated} updated')
