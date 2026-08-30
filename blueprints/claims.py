"""Open-job board: broadcast a job to the whole team, first to claim wins.
Big houses can be crew jobs (2+ spots) — then the first N to claim get in, each
with their own pay. Blocks time-clashing claims and lets a cleaner release a job
back to the board."""
import re
import secrets
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for
from sqlalchemy.exc import IntegrityError
from extensions import db
from models import Booking, BookingCrew, Staff, BusinessSetting
from notifications import send_sms
from pricing import get_labor_rate
from translate import translate
import branding

claims_bp = Blueprint('claims', __name__)



def _biz():
    return branding.biz_name()


def _owner_phone():
    return BusinessSetting.get('owner_alert_phone') or BusinessSetting.get('phone')


def commissionable(b):
    return (b.price or 0) - (b.lead_fee or 0)


# ── Time-clash detection ────────────────────────────────────────────────────
def parse_time(t):
    """Return minutes-since-midnight for a free-text time, or None if unclear."""
    t = (t or '').strip().lower()
    m = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?', t)
    if not m:
        return None
    h = int(m.group(1))
    mm = int(m.group(2) or 0)
    ap = (m.group(3) or '').replace('.', '')
    if ap == 'pm' and h != 12:
        h += 12
    elif ap == 'am' and h == 12:
        h = 0
    if h > 23 or mm > 59:
        return None
    return h * 60 + mm


def _window(b):
    """(start_min, end_min) for a job, incl. a 1-hour travel buffer. None if time unclear."""
    start = parse_time(b.preferred_time)
    if start is None:
        return None
    hrs = 2.5
    try:
        from pricing import calculate_job
        hrs = calculate_job(b.service_type, b.bedrooms or 1, b.bathrooms or 1).get('hours') or 2.5
    except Exception:
        pass
    return (start, start + int(hrs * 60) + 60)


def jobs_for(staff, on_date, exclude_id=None):
    """Every job this cleaner is on that day — solo (assigned_cleaner) or as one
    of a crew. Both sources matter, or a crew job wouldn't block a double-book."""
    q = Booking.query.outerjoin(BookingCrew, BookingCrew.booking_id == Booking.id).filter(
        db.or_(db.func.lower(Booking.assigned_cleaner) == (staff.name or '').lower(),
               BookingCrew.staff_id == staff.id),
        Booking.status != 'cancelled',
        Booking.preferred_date == on_date,
    )
    if exclude_id:
        q = q.filter(Booking.id != exclude_id)
    return q.distinct().all()


def clash_reason(staff, new_booking):
    """Return a human message if claiming would clash with the cleaner's day, else None."""
    others = jobs_for(staff, new_booking.preferred_date, exclude_id=new_booking.id)
    if not others:
        return None
    nw = _window(new_booking)
    for o in others:
        if nw is None:
            return f"You already have a job on {new_booking.preferred_date}. Text {_biz()} to confirm you can take both."
        ow = _window(o)
        if ow is None:
            return f"You already have a job on {new_booking.preferred_date}. Text {_biz()} to confirm you can take both."
        if nw[0] < ow[1] and ow[0] < nw[1]:
            return f"This overlaps your {o.preferred_time} job that day — can't be in two places at once!"
    return None


# ── Broadcast a job to the whole team ───────────────────────────────────────
def uses_crew(booking):
    """True once a job tracks named people with set pay — either because it needs
    2+ cleaners, or because someone was assigned directly with a fixed amount."""
    return bool(booking.crew) or booking.is_crew_job


def broadcast_job(booking):
    """Open the job and text every available cleaner a personal claim link.

    Plain job: clears the assignment, first to claim wins.
    Job with people already on it: keeps them and only offers the spots still
    open — so re-offering never bumps someone who was assigned directly or
    already claimed and got their work order. Remove people from the Crew card
    instead."""
    if not booking.claim_token:
        booking.claim_token = secrets.token_urlsafe(24)
    booking.open_for_claim = True
    booking.cleaner_response = None
    booking.broadcast_at = datetime.utcnow()
    if not uses_crew(booking):
        booking.assigned_cleaner = None
    db.session.commit()

    if uses_crew(booking) and booking.spots_left <= 0:
        booking.open_for_claim = False      # nothing to offer — keep it off the board
        db.session.commit()
        return 0

    already = {c.staff_id for c in booking.crew}
    area = booking.city or booking.zip_code or 'your area'
    when = f"{booking.preferred_date or 'soon'}{(' ' + booking.preferred_time) if booking.preferred_time else ''}"
    spots = booking.spots_left
    sent = 0
    for s in Staff.query.filter(Staff.is_active.is_(True), Staff.phone.isnot(None)).all():
        if s.id in already:
            continue                      # already holds a spot on this job
        if not s.agreement_token:
            s.agreement_token = secrets.token_urlsafe(32)
            db.session.commit()
        link = f"{branding.crm_base()}/claim/{booking.claim_token}/{s.agreement_token}"
        # The house, not the stopwatch. An hourly figure in a job offer invites
        # clock-watching on work that is paid per job, and the hours are an
        # estimate for planning rather than a promise about the shift.
        size = booking.size_line()
        if booking.is_crew_job:
            pay = booking.default_crew_pay(s)
            msg = (f"🧹 Team job — {booking.crew_size} cleaners needed! {when} · "
                   f"{booking.service_label}"
                   f"{(' · ' + size) if size else ''} · {area} area · "
                   f"${pay:.2f} each, flat for the job. "
                   f"{spots} spot{'s' if spots != 1 else ''} left 👉 {link}")
        else:
            pay = booking.pay_for(s)
            msg = (f"🧹 New job available! {when} · {booking.service_label}"
                   f"{(' · ' + size) if size else ''} · {area} area · "
                   f"${pay:.2f} for the job. First to claim it gets it 👉 {link}")
        if (s.language or 'en') == 'es':
            msg = translate(msg, target='es')
        try:
            ok, _ = send_sms(s.phone, msg)
            sent += 1 if ok else 0
        except Exception:
            pass
    return sent


def _alert_owner(text):
    phone = _owner_phone()
    if phone:
        try:
            send_sms(phone, text)
        except Exception:
            pass


# ── Claim page (public, personalized link) ──────────────────────────────────
def _pay_for(booking, staff):
    """What this cleaner sees as their take on this job. An amount already
    agreed on their crew row wins; an open spot is quoted at its share of the
    labor budget."""
    if uses_crew(booking):
        row = booking.crew_row_for(staff)
        if row and row.pay_amount is not None:
            return row.pay_amount
        return booking.default_crew_pay(staff)
    return booking.pay_for(staff)


def _claim_state(booking, staff):
    """open = spot available, mine = they're on it, taken = full."""
    if uses_crew(booking):
        if booking.crew_row_for(staff):
            return 'mine'
        return 'open' if (booking.open_for_claim and booking.spots_left > 0) else 'taken'
    if booking.open_for_claim:
        return 'open'
    if (booking.assigned_cleaner or '').lower() == (staff.name or '').lower():
        return 'mine'
    return 'taken'


def _friendly_date(iso):
    """"Tomorrow", or "Monday 1 September". Nobody reads a job off an ISO date."""
    from datetime import date as _date
    if not iso:
        return 'Date to be confirmed'
    try:
        d = _date.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso
    delta = (d - _date.today()).days
    if delta == 0:
        return 'Today'
    if delta == 1:
        return 'Tomorrow'
    return d.strftime('%A %-d %B')


@claims_bp.route('/claim/<ctoken>/<stoken>')
def claim_page(ctoken, stoken):
    booking = Booking.query.filter_by(claim_token=ctoken).first_or_404()
    staff = Staff.query.filter_by(agreement_token=stoken).first_or_404()
    state = _claim_state(booking, staff)
    return render_template('public/claim.html', b=booking, s=staff,
                           when_label=_friendly_date(booking.preferred_date),
                           pay=_pay_for(booking, staff), state=state,
                           hours_each=booking.hours_each(), labor_rate=get_labor_rate(),
                           clash=clash_reason(staff, booking) if state == 'open' else None,
                           biz=_biz(), myday=f"{branding.crm_base()}/contractors/my-day/{staff.agreement_token}")


def _take_crew_spot(booking, staff):
    """Grab one spot on a crew job. Returns True if the spot is theirs.

    Race-safe without locking: everyone inserts, then the lowest N row ids keep
    their spot and any loser deletes its own row. The unique constraint stops the
    same person taking two spots."""
    row = BookingCrew(booking_id=booking.id, staff_id=staff.id,
                      pay_amount=booking.default_crew_pay(staff),
                      claimed_at=datetime.utcnow())
    db.session.add(row)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return True                       # they already held a spot — that's a win

    winners = BookingCrew.query.filter_by(booking_id=booking.id) \
                               .order_by(BookingCrew.id).limit(booking.crew_size or 1).all()
    if row.id not in [w.id for w in winners]:
        db.session.delete(row)            # someone beat them to the last spot
        db.session.commit()
        return False
    return True


@claims_bp.route('/claim/<ctoken>/<stoken>/claim', methods=['POST'])
def claim_do(ctoken, stoken):
    booking = Booking.query.filter_by(claim_token=ctoken).first_or_404()
    staff = Staff.query.filter_by(agreement_token=stoken).first_or_404()

    # Not available anymore?
    if _claim_state(booking, staff) != 'open':
        return redirect(url_for('claims.claim_page', ctoken=ctoken, stoken=stoken))

    # Time clash guard
    reason = clash_reason(staff, booking)
    if reason:
        return render_template('public/claim.html', b=booking, s=staff,
                               when_label=_friendly_date(booking.preferred_date),
                               pay=_pay_for(booking, staff),
                               hours_each=booking.hours_each(), labor_rate=get_labor_rate(),
                               state='clash', clash=reason, biz=_biz(),
                               myday=f"{branding.crm_base()}/contractors/my-day/{staff.agreement_token}")

    if uses_crew(booking):
        if not _take_crew_spot(booking, staff):
            return redirect(url_for('claims.claim_page', ctoken=ctoken, stoken=stoken))
        if not booking.assigned_cleaner:
            booking.assigned_cleaner = staff.name      # first in becomes the lead
        booking.cleaner_notified_at = datetime.utcnow()
        if booking.spots_left <= 0:                    # crew is full — close the board
            booking.open_for_claim = False
            booking.cleaner_response = 'accepted'
        db.session.commit()
        left = booking.spots_left
        note = f"{left} spot{'s' if left != 1 else ''} still open" if left else "crew is full ✅"
    else:
        # Atomic first-wins: only the update that flips open_for_claim from True succeeds.
        won = Booking.query.filter_by(id=booking.id, open_for_claim=True).update(
            {'assigned_cleaner': staff.name, 'open_for_claim': False,
             'cleaner_response': 'accepted', 'cleaner_notified_at': datetime.utcnow()},
            synchronize_session=False)
        db.session.commit()
        if not won:
            return redirect(url_for('claims.claim_page', ctoken=ctoken, stoken=stoken))
        db.session.refresh(booking)
        note = None

    # Send the checklist + notify the owner
    try:
        from blueprints.workorders import create_and_send_workorder
        create_and_send_workorder(booking, recipient=staff)
    except Exception:
        pass
    msg = f"✅ {staff.name} claimed the {booking.preferred_date} job ({booking.name})."
    _alert_owner(f"{msg} {note}" if note else msg)
    return redirect(url_for('claims.claim_page', ctoken=ctoken, stoken=stoken))


# ── Release a claimed job back to the board ─────────────────────────────────
@claims_bp.route('/jobs/release/<int:booking_id>/<stoken>', methods=['POST'])
def release(booking_id, stoken):
    booking = Booking.query.get_or_404(booking_id)
    staff = Staff.query.filter_by(agreement_token=stoken).first_or_404()
    row = booking.crew_row_for(staff)
    if not row and (booking.assigned_cleaner or '').lower() != (staff.name or '').lower():
        return redirect(url_for('contractors.my_day', token=stoken))

    if row:
        if row.paid_at:      # already paid out — releasing would orphan the payment
            return redirect(url_for('contractors.my_day', token=stoken))
        db.session.delete(row)           # frees only their spot; the rest of the crew stays
        db.session.commit()
        # If the lead walked, hand the lead label to whoever's left.
        if (booking.assigned_cleaner or '').lower() == (staff.name or '').lower():
            booking.assigned_cleaner = booking.crew_names[0] if booking.crew else None
            db.session.commit()

    _alert_owner(f"↩️ {staff.name} released the {booking.preferred_date} job ({booking.name}) — re-offering to the team.")
    broadcast_job(booking)   # re-opens the empty spot(s) + re-texts everyone else
    return redirect(url_for('contractors.my_day', token=stoken))
