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
from urllib.parse import quote

import click
from datetime import datetime, timedelta

from flask import (Blueprint, render_template, request, abort, url_for,
                   redirect, flash, current_app)

from auth import login_required
from extensions import db
from notifications import send_email
from models import BusinessSetting
import product
import branding

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


class DirectorySubmission(db.Model):
    """A business asking to be added, because the public records do not hold it.

    Separate from DirectoryListing on purpose. create_all() at boot builds a
    missing table but never alters one that exists, so adding columns to the
    listing table would silently do nothing on production. A submission is also
    genuinely a different thing: a request, not a record.

    Approved submissions are exported to the generator's extra_<state>.csv,
    which is merged on every rebuild — so an added business survives the next
    regeneration instead of being typed in once and lost.
    """
    __tablename__ = 'directory_submission'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    city = db.Column(db.String(100))
    state = db.Column(db.String(2), index=True)
    phone = db.Column(db.String(40))
    email = db.Column(db.String(200))
    website = db.Column(db.String(400))
    note = db.Column(db.String(500))
    contact_name = db.Column(db.String(120))
    # new -> approved -> exported, or rejected
    status = db.Column(db.String(20), default='new', index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime)
    exported_at = db.Column(db.DateTime)


class DirectoryTalent(db.Model):
    """Somebody looking for cleaning work, who agreed to be shown to companies.

    The pool exists because the demand side generates it. A company that
    interviews ten people hires two; the other eight want cleaning work and are
    qualified to do it, and today they get a "no" and nothing else. Asked
    properly, most will happily be shown to other companies nearby.

    Seeded from Indeed to start — one advert per target metro pointing at /work,
    rather than one advert per company, which is what makes a pool worth having.

    Consent is the whole basis for this table: nobody is listed who did not tick
    the box, and unticking it takes them out. A new table rather than columns on
    anything existing, because create_all() at boot builds a missing table but
    never alters one that is already there.
    """
    __tablename__ = 'directory_talent'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(200), index=True)
    phone = db.Column(db.String(40))
    city = db.Column(db.String(100))
    state = db.Column(db.String(2), index=True)
    zip_code = db.Column(db.String(10))
    language = db.Column(db.String(5), default='en')      # en | es
    experience = db.Column(db.String(20))                 # none | some | years
    # How they get to work, not whether they own a car. "Do you have reliable
    # transportation?" quietly disqualifies most of New York, Chicago and Boston,
    # which between them hold the densest cleaning markets in the country — 1,189
    # companies within ten miles of Manhattan alone. What an owner actually needs
    # to know is whether somebody can reach the job on time.
    travel = db.Column(db.String(20))          # car | transit | rides | walk | unsure
    travel_miles = db.Column(db.Integer)       # how far they are willing to go
    days = db.Column(db.String(120))                      # free text: when they can work
    note = db.Column(db.String(500))
    source = db.Column(db.String(30), default='web')      # web | indeed | passed-on | referral
    # shown to companies only while this is true — the person can switch it off
    share = db.Column(db.Boolean, default=True, index=True)
    status = db.Column(db.String(20), default='looking', index=True)  # looking | placed | closed
    opt_out_token = db.Column(db.String(64), unique=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class DirectoryInvite(db.Model):
    """Who has already been asked to join the pool, so nobody is asked twice.

    Lives in public alongside the rest of the directory tables, so it records
    which company the invite came from — the applications themselves live in
    each company's own schema and cannot be marked from here.
    """
    __tablename__ = 'directory_invite'
    id = db.Column(db.Integer, primary_key=True)
    company = db.Column(db.String(64), index=True)
    email = db.Column(db.String(200), index=True)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)


class DirectoryProfile(db.Model):
    """What a business wrote about itself, once it claimed its listing.

    The listing row holds what the public record knows. This holds what they
    want said — and it is the difference between correcting a phone number and
    having a page worth sending somebody. For the twenty per cent of cleaning
    companies with no website at all, this is the website.

    Kept separate from directory_listing on purpose: a re-import of the public
    data overwrites that table wholesale, and nobody's own words should be
    destroyed by a refresh of somebody else's records.
    """
    __tablename__ = 'directory_profile'
    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.String(64), unique=True, index=True, nullable=False)
    headline = db.Column(db.String(160))
    about = db.Column(db.Text)
    services = db.Column(db.Text)          # one per line
    areas = db.Column(db.String(300))      # towns they cover
    hours = db.Column(db.String(200))
    # What they want people to use, which may not be what the record holds.
    phone = db.Column(db.String(40))
    email = db.Column(db.String(200))
    website = db.Column(db.String(400))
    booking_url = db.Column(db.String(400))
    brand_color = db.Column(db.String(9))  # #RRGGBB
    founded_year = db.Column(db.String(4))
    edit_token = db.Column(db.String(64), unique=True, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    def service_lines(self):
        return [x.strip() for x in (self.services or '').splitlines() if x.strip()][:12]


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
        return render_template('directory/done.html', claim=claim, listing=listing,
                               prof=_profile_for(claim.listing_id, create=True))
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
            # Verifying is the moment they care most. Hand them the page to
            # write rather than making them come back for it.
            prof = _profile_for(claim.listing_id, create=True)
            return render_template('directory/done.html', claim=claim,
                                   listing=listing, prof=prof)
        claim.attempts = (claim.attempts or 0) + 1
        db.session.commit()
        left = MAX_ATTEMPTS - claim.attempts
        flash(f"That code didn't match. {left} tr{'y' if left == 1 else 'ies'} left."
              if left > 0 else "That's too many tries.", 'error')

    return render_template('directory/verify.html', claim=claim, listing=listing)


# ── people looking for cleaning work ────────────────────────────────────────
@directory_bp.route('/work', methods=['GET', 'POST'])
def find_work():
    """The page an Indeed advert points at. Not tied to one company: somebody
    applying here is offered to every Akye company near them, which is the only
    way one advert can serve a whole metro."""
    if request.method == 'GET':
        return render_template('directory/work.html',
                               lang=('es' if (request.args.get('lang') or '').startswith('es')
                                     else 'en'),
                               city=request.args.get('city', ''),
                               state=(request.args.get('state', '') or '').upper(),
                               prefill_name=request.args.get('name', '')[:120],
                               prefill_email=request.args.get('email', '')[:200],
                               prefill_phone=request.args.get('phone', '')[:40],
                               source=(request.args.get('src') or 'web')[:30])

    name = (request.form.get('name') or '').strip()
    email = _norm_email(request.form.get('email'))
    phone = (request.form.get('phone') or '').strip()
    if not name or not (email or phone):
        flash('A name and either an email or a phone number are needed.', 'error')
        return redirect(url_for('directory.find_work'))
    if not request.form.get('share'):
        flash('We can only pass your details on if you tick the box.', 'error')
        return redirect(url_for('directory.find_work'))

    t = DirectoryTalent(
        name=name[:120], email=email or None, phone=phone[:40] or None,
        city=(request.form.get('city') or '').strip()[:100],
        state=(request.form.get('state') or '').strip().upper()[:2],
        zip_code=(request.form.get('zip_code') or '').strip()[:10],
        language=('es' if (request.form.get('language') or '') == 'es' else 'en'),
        experience=(request.form.get('experience') or '')[:20],
        travel=(request.form.get('travel') or '')[:20],
        travel_miles=(int(request.form['travel_miles'])
                      if (request.form.get('travel_miles') or '').isdigit() else None),
        days=(request.form.get('days') or '').strip()[:120],
        note=(request.form.get('note') or '').strip()[:500],
        source=(request.form.get('source') or 'web')[:30],
        opt_out_token=secrets.token_urlsafe(32))
    db.session.add(t)
    db.session.commit()
    return render_template('directory/work_done.html', t=t)


@directory_bp.route('/work/stop/<token>', methods=['GET', 'POST'])
def stop_sharing(token):
    """One click out. A pool somebody cannot leave is not a pool, it is a list."""
    t = DirectoryTalent.query.filter_by(opt_out_token=token).first_or_404()
    if request.method == 'POST':
        t.share = False
        t.status = 'closed'
        db.session.commit()
        return render_template('directory/work_stopped.html', t=t)
    return render_template('directory/work_stop.html', t=t)


@directory_bp.route('/admin/talent')
@login_required
def talent_pool():
    """Cleaners near this company who said they are looking.

    Free on every plan for now, deliberately. The pool only becomes an upgrade
    lever once it has depth, and gating it while it is thin would just teach
    people it is empty.
    """
    here_state = (BusinessSetting.get('state') or '').upper()[:2]
    here_city = (BusinessSetting.get('city') or '').strip()
    q = DirectoryTalent.query.filter_by(share=True, status='looking')
    state = (request.args.get('state') or here_state or '').upper()[:2]
    if state:
        q = q.filter(DirectoryTalent.state == state)
    people = q.order_by(DirectoryTalent.created_at.desc()).limit(300).all()
    # nearest-feeling first: same town at the top, then the rest of the state
    people.sort(key=lambda p: (0 if (p.city or '').lower() == here_city.lower() else 1,
                               -(p.created_at or datetime.min).timestamp()))
    states = [r[0] for r in db.session.query(DirectoryTalent.state)
              .filter_by(share=True, status='looking').distinct().all() if r[0]]
    return render_template('directory/talent.html', people=people, state=state,
                           states=sorted(states), here_city=here_city,
                           biz=branding.biz_name())


@directory_bp.route('/admin/talent/ads')
@login_required
def hiring_ads():
    """Ready-made job adverts, and the link to point them at.

    A company posting its own opening is the employer, so it may post free on
    Indeed. Akye may not — third parties have to sponsor, which is Indeed's own
    rule. So the scalable version of filling the pool is not Akye advertising
    anywhere: it is every company advertising its own real job, for free, and
    the people they do not hire being invited in afterwards.

    Two versions, because 1099 and W-2 are not a wording preference. An advert
    that describes a contractor role in employment language — set shifts, we
    train you, your supervisor — is evidence of misclassification, and the
    liability lands on the cleaning company, not on us. Handing somebody the
    wrong template would be handing them a problem.
    """
    import tenancy
    slug = (tenancy.current_schema() or '').replace(tenancy.SCHEMA_PREFIX, '')
    base = branding.crm_base() or 'https://www.akyehq.com'
    apply_url = f"{base}/apply"
    model = (BusinessSetting.get('worker_model') or 'contractor')
    city = (BusinessSetting.get('city') or 'your area')
    state = (BusinessSetting.get('state') or '')
    return render_template('directory/ads.html', biz=branding.biz_name(),
                           apply_url=apply_url, model=model, city=city,
                           state=state, slug=slug)


# ── inviting your own past applicants into the pool ─────────────────────────
def _uninvited_applicants(slug):
    """People who applied here, were never hired, and have not been asked yet."""
    from models import ContractorApplication
    rows = (ContractorApplication.query
            .filter(~ContractorApplication.status.in_(('hired', 'onboarding')))
            .filter(ContractorApplication.email.isnot(None))
            .order_by(ContractorApplication.created_at.desc()).all())
    already = {e.lower() for (e,) in db.session.query(DirectoryInvite.email)
               .filter_by(company=slug).all() if e}
    return [a for a in rows if (a.email or '').lower() not in already]


@directory_bp.route('/admin/talent/invite', methods=['GET', 'POST'])
@login_required
def invite_past_applicants():
    """Ask the people who applied here and were never hired whether they want
    other cleaning companies nearby to see them.

    Runs in the app rather than as a command on somebody's laptop, because the
    mail key lives here — and because every company should be able to do this
    for itself, not just the one whose developer has a terminal open.
    """
    import tenancy
    slug = (tenancy.current_schema() or '').replace(tenancy.SCHEMA_PREFIX, '') or 'default'
    people = _uninvited_applicants(slug)
    biz = branding.biz_name()

    if request.method == 'GET':
        return render_template('directory/invite.html', people=people[:20],
                               total=len(people), biz=biz,
                               can_send=bool(product.resend_api_key()))

    key = product.resend_api_key()
    if not key:
        flash('No product mail key is configured, so nothing was sent.', 'error')
        return redirect(url_for('directory.invite_past_applicants'))

    try:
        limit = max(1, min(int(request.form.get('limit') or 10), 500))
    except ValueError:
        limit = 10

    base = product.site_url() if hasattr(product, 'site_url') else 'https://www.akyehq.com'
    sent = failed = 0
    for a in people[:limit]:
        link = (f"{base}/work?src=past-applicant"
                f"&name={quote(a.name or '')}&email={quote(a.email or '')}"
                f"&phone={quote(a.phone or '')}")
        ok, _why = send_email(
            to_email=a.email, to_name=a.name or '',
            subject='Still looking for cleaning work?',
            html=(f"<p>Hi {(a.name or '').split(' ')[0]},</p>"
                  f"<p>You applied to {biz} a while back and we weren't able to take you "
                  f"on. I'm sorry we left it there.</p>"
                  f"<p>We've since put together a list that cleaning companies near you "
                  f"can look at when they're hiring. If you'd like to be on it, it takes "
                  f"a minute and it's free:</p>"
                  f"<p><a href='{link}'>Yes, show me to cleaning companies near me</a></p>"
                  f"<p>Your details are already filled in — just check them and tick the "
                  f"box. You can take yourself off any time, and if you'd rather not, do "
                  f"nothing at all and you won't hear from us again.</p>"),
            from_name=biz, api_key=key)
        # Recorded either way: a bounce is not a reason to pester somebody again.
        db.session.add(DirectoryInvite(company=slug, email=a.email))
        sent += 1 if ok else 0
        failed += 0 if ok else 1
    db.session.commit()

    if failed:
        flash(f'{sent} invited, {failed} could not be delivered.', 'error')
    else:
        flash(f'{sent} past applicant{"s" if sent != 1 else ""} invited.', 'success')
    return redirect(url_for('directory.invite_past_applicants'))


# ── adding a business the records missed ────────────────────────────────────
@directory_bp.route('/listing/add', methods=['GET', 'POST'])
def add_listing():
    """Not on the board? Overture does not hold every real company — ours was
    missing too — and a directory that cannot show the people reading it is
    no use to them."""
    if request.method == 'GET':
        return render_template('directory/add.html',
                               name=request.args.get('name', ''),
                               city=request.args.get('city', ''))

    name = (request.form.get('name') or '').strip()
    email = _norm_email(request.form.get('email'))
    if not name or not email:
        flash('A business name and an email address are both needed.', 'error')
        return redirect(url_for('directory.add_listing'))

    sub = DirectorySubmission(
        name=name[:200],
        city=(request.form.get('city') or '').strip()[:100],
        state=(request.form.get('state') or '').strip().upper()[:2],
        phone=(request.form.get('phone') or '').strip()[:40],
        email=email,
        website=(request.form.get('website') or '').strip()[:400],
        contact_name=(request.form.get('contact_name') or '').strip()[:120],
        note=(request.form.get('note') or '').strip()[:500])
    db.session.add(sub)
    db.session.commit()
    return render_template('directory/add_done.html', sub=sub)


@directory_bp.route('/admin/listings/submissions')
@login_required
def submissions_queue():
    status = request.args.get('status') or 'new'
    q = DirectorySubmission.query
    if status != 'all':
        q = q.filter_by(status=status)
    subs = q.order_by(DirectorySubmission.created_at.desc()).limit(300).all()
    counts = dict(db.session.query(DirectorySubmission.status,
                                   db.func.count(DirectorySubmission.id))
                  .group_by(DirectorySubmission.status).all())
    return render_template('directory/submissions.html', subs=subs,
                           counts=counts, status=status)


@directory_bp.route('/admin/listings/submissions/<int:sub_id>/<action>', methods=['POST'])
@login_required
def review_submission(sub_id, action):
    sub = DirectorySubmission.query.get_or_404(sub_id)
    if action not in ('approve', 'reject'):
        abort(404)
    sub.status = 'approved' if action == 'approve' else 'rejected'
    sub.reviewed_at = datetime.utcnow()
    db.session.commit()
    flash(f'{sub.name} {sub.status}.'
          + (' Run "flask directory export-submissions" and rebuild to publish it.'
             if sub.status == 'approved' else ''), 'success')
    return redirect(url_for('directory.submissions_queue'))


@directory_bp.cli.command('invite-applicants')
@click.option('--tenant', required=True, help="the company's slug, e.g. dazzleandshine")
@click.option('--send', is_flag=True, default=False,
              help='actually send. Without it you get a preview and nothing leaves.')
@click.option('--limit', default=200, help='stop after this many')
def invite_applicants(tenant, send, limit):
    """Ask people who applied and were never hired whether they want to be shown
    to other cleaning companies nearby.

    They applied to one company, not to a shared list, so their details are NOT
    moved anywhere. The email carries a link to /work with their own details
    filled in, and they tick the consent box themselves — which is the only
    version of this that is decent as well as lawful.

    Dry run by default. Real people, real inboxes, one chance to get the tone right.
    """
    import tenancy
    from models import ContractorApplication
    base = product.site_url() if hasattr(product, 'site_url') else 'https://www.akyehq.com'

    # Refuse early rather than report "0 sent", which reads exactly like "nobody
    # qualified" and sent me looking in the wrong place for ten minutes. The key
    # lives in Railway, so running this from a laptop will always send nothing.
    key = product.resend_api_key()
    if send and not key:
        raise click.ClickException(
            'No PRODUCT_RESEND_API_KEY in this environment, so nothing could be sent.\n'
            'Run it where the key is — Railway\'s shell — or put the key in front of '
            'the command:\n'
            '    PRODUCT_RESEND_API_KEY=re_... flask directory invite-applicants '
            '--tenant <slug> --send')

    with tenancy.use_tenant(tenant):
        rows = (ContractorApplication.query
                .filter(~ContractorApplication.status.in_(('hired', 'onboarding')))
                .filter(ContractorApplication.email.isnot(None))
                .order_by(ContractorApplication.created_at.desc())
                .limit(limit).all())
        biz = branding.biz_name()

        print(f'{len(rows)} past applicants at {biz} who were never hired')
        if not send:
            print('DRY RUN — nothing sent. Add --send to actually email them.\n')
        sent = failed = 0
        for a in rows:
            link = (f"{base}/work?src=past-applicant"
                    f"&name={quote(a.name or '')}&email={quote(a.email or '')}"
                    f"&phone={quote(a.phone or '')}")
            if not send:
                if sent < 3:
                    print(f'  would email {a.email}  ({a.name})')
                sent += 1
                continue
            ok, why = send_email(
                to_email=a.email, to_name=a.name or '',
                subject=f'Still looking for cleaning work?',
                html=(f"<p>Hi {(a.name or '').split(' ')[0]},</p>"
                      f"<p>You applied to {biz} a while back and we weren't able to "
                      f"take you on. I'm sorry we left it there.</p>"
                      f"<p>We've since put together a list that cleaning companies near "
                      f"you can look at when they're hiring. If you'd like to be on it, "
                      f"it takes a minute and it's free:</p>"
                      f"<p><a href='{link}'>Yes, show me to cleaning companies near me</a></p>"
                      f"<p>Your details are already filled in — just check them and tick "
                      f"the box. You can take yourself off any time, and if you'd rather "
                      f"not, do nothing at all and you won't hear from us again.</p>"),
                from_name=biz, api_key=key or None)
            if ok:
                sent += 1
            else:
                failed += 1
                if failed <= 3:
                    print(f'  FAILED {a.email}: {why}')
        if failed:
            print(f'\n{sent} sent, {failed} failed — see the reasons above.')
        else:
            print(f'\n{sent} {"emails sent" if send else "would be emailed"}')


@directory_bp.cli.command('export-submissions')
def export_submissions():
    """Write approved submissions out as extra_<state>.csv rows.

    Printed to stdout as CSV so it can be appended to the generator's
    extra_<state>.csv and picked up by the next build. Marks them exported so
    the same business is not written twice.
    """
    import sys
    subs = DirectorySubmission.query.filter_by(status='approved').all()
    subs = [s for s in subs if not s.exported_at]
    if not subs:
        print('nothing approved and waiting', file=sys.stderr)
        return
    w = csv.writer(sys.stdout)
    w.writerow(['id', 'name', 'city', 'state', 'zip', 'street', 'phone',
                'email', 'website', 'social', 'operating_status', 'confidence'])
    for s in subs:
        w.writerow([f'akye-sub-{s.id}', s.name, s.city, s.state, '', '',
                    s.phone or '', s.email or '', s.website or '', '', 'open', '1.0'])
        s.exported_at = datetime.utcnow()
    db.session.commit()
    print(f'{len(subs)} exported', file=sys.stderr)


# ── the page a claimed business writes for itself ───────────────────────────
def _profile_for(listing_id, create=False):
    prof = DirectoryProfile.query.filter_by(listing_id=listing_id).first()
    if prof is None and create:
        prof = DirectoryProfile(listing_id=listing_id,
                                edit_token=secrets.token_urlsafe(32))
        db.session.add(prof)
        db.session.commit()
    return prof


@directory_bp.route('/listing/edit/<token>', methods=['GET', 'POST'])
def edit_profile(token):
    """No login. The token came out of a verified claim, which is the only thing
    that proved anybody owns this listing in the first place — asking them to
    make an account to fix their own opening hours would lose most of them."""
    prof = DirectoryProfile.query.filter_by(edit_token=token).first_or_404()
    listing = DirectoryListing.query.get(prof.listing_id)

    if request.method == 'POST':
        colour = (request.form.get('brand_color') or '').strip()
        if colour and not re.fullmatch(r'#[0-9A-Fa-f]{6}', colour):
            colour = ''
        prof.headline = (request.form.get('headline') or '').strip()[:160]
        prof.about = (request.form.get('about') or '').strip()[:4000]
        prof.services = (request.form.get('services') or '').strip()[:1500]
        prof.areas = (request.form.get('areas') or '').strip()[:300]
        prof.hours = (request.form.get('hours') or '').strip()[:200]
        prof.phone = (request.form.get('phone') or '').strip()[:40]
        prof.email = _norm_email(request.form.get('email'))[:200]
        prof.website = (request.form.get('website') or '').strip()[:400]
        prof.booking_url = (request.form.get('booking_url') or '').strip()[:400]
        prof.brand_color = colour
        prof.founded_year = (request.form.get('founded_year') or '').strip()[:4]
        prof.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Saved. Your page updates on the next refresh, usually within a day.',
              'success')
        return redirect(url_for('directory.edit_profile', token=token))

    return render_template('directory/edit_profile.html', prof=prof, listing=listing)


@directory_bp.cli.command('export-profiles')
def export_profiles():
    """flask directory export-profiles > profiles.json

    What claimed businesses wrote, for the generator to fold into their pages.
    """
    import json, sys
    out = {}
    for p in DirectoryProfile.query.all():
        out[p.listing_id] = {k: v for k, v in {
            'headline': p.headline, 'about': p.about,
            'services': p.service_lines(), 'areas': p.areas, 'hours': p.hours,
            'phone': p.phone, 'email': p.email, 'website': p.website,
            'booking_url': p.booking_url, 'brand_color': p.brand_color,
            'founded_year': p.founded_year,
        }.items() if v}
    json.dump(out, sys.stdout, indent=1, sort_keys=True)
    print(f'\n{len(out)} profiles', file=sys.stderr)


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
    prof = _profile_for(claim.listing_id, create=True)
    db.session.commit()
    flash(f'{claim.listing_name} claimed by {claim.email}. Their page to write: '
          f'{url_for("directory.edit_profile", token=prof.edit_token, _external=True)}',
          'success')
    return redirect(url_for('directory.claims_queue'))


# ── loading the directory in ────────────────────────────────────────────────
@directory_bp.cli.command('import-listings')
def import_listings():
    """flask directory import-listings < data/fl_urls.csv

    Re-running updates rows in place — the Overture id is the key — so a refreshed
    export never duplicates a listing or drops who claimed it.

    Reads every existing id in one query rather than asking per row. The first
    version did a SELECT per line, which is fine against a local database and
    takes the better part of an hour against a remote one over 60,000 rows.
    """
    import sys
    rows = [r for r in csv.DictReader(sys.stdin) if (r.get('id') or '').strip()]
    if not rows:
        print('nothing on stdin')
        return

    known = {r[0] for r in db.session.query(DirectoryListing.id).all()}
    added = updated = 0

    def fields(row):
        state = (row.get('state') or '').strip()
        if not state:
            parts = (row.get('url') or '').split('/')
            state = (parts[3][:2].upper() if len(parts) > 4 else '')
        try:
            vis = int(row.get('visibility') or 0)
        except ValueError:
            vis = 0
        return dict(
            name=(row.get('name') or '')[:200],
            city=(row.get('city') or '')[:100],
            state=state[:2],
            email=(row.get('email') or None),
            phone=(row.get('phone') or None),
            url=(row.get('url') or None),
            visibility=vis)

    new_rows = []
    for row in rows:
        lid = row['id'].strip()
        if lid in known:
            db.session.query(DirectoryListing).filter_by(id=lid).update(fields(row))
            updated += 1
        else:
            new_rows.append({'id': lid, **fields(row)})
            added += 1

    # One round trip per thousand rather than one per row.
    for i in range(0, len(new_rows), 1000):
        db.session.bulk_insert_mappings(DirectoryListing, new_rows[i:i + 1000])
        print(f'  {min(i + 1000, len(new_rows))}/{len(new_rows)}', flush=True)

    db.session.commit()
    print(f'{added} added, {updated} updated')
