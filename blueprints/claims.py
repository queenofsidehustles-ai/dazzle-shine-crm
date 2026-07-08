"""Open-job board: broadcast a job to the whole team, first to claim wins.
Blocks time-clashing claims and lets a cleaner release a job back to the board."""
import re
import secrets
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for
from extensions import db
from models import Booking, Staff, BusinessSetting
from notifications import send_sms
from translate import translate

claims_bp = Blueprint('claims', __name__)

CRM_BASE = 'https://dazzle-shine-crm-production.up.railway.app'


def _biz():
    return BusinessSetting.get('business_name', 'Dazzle & Shine Maids')


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


def clash_reason(staff, new_booking):
    """Return a human message if claiming would clash with the cleaner's day, else None."""
    others = Booking.query.filter(
        db.func.lower(Booking.assigned_cleaner) == (staff.name or '').lower(),
        Booking.status != 'cancelled',
        Booking.preferred_date == new_booking.preferred_date,
        Booking.id != new_booking.id,
    ).all()
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
def broadcast_job(booking):
    """Open the job and text every active cleaner a personal claim link."""
    if not booking.claim_token:
        booking.claim_token = secrets.token_urlsafe(24)
    booking.open_for_claim = True
    booking.assigned_cleaner = None
    booking.cleaner_response = None
    booking.broadcast_at = datetime.utcnow()
    db.session.commit()

    area = booking.city or booking.zip_code or 'your area'
    when = f"{booking.preferred_date or 'soon'}{(' ' + booking.preferred_time) if booking.preferred_time else ''}"
    sent = 0
    for s in Staff.query.filter(Staff.is_active.is_(True), Staff.phone.isnot(None)).all():
        if not s.agreement_token:
            s.agreement_token = secrets.token_urlsafe(32)
            db.session.commit()
        pay = s.calc_pay(job_price=commissionable(booking), hours_worked=0)
        link = f"{CRM_BASE}/claim/{booking.claim_token}/{s.agreement_token}"
        msg = (f"🧹 New job available! {when} · {booking.service_label} · {area} area · "
               f"You'd earn ${pay:.0f}. First to claim it gets it 👉 {link}")
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
@claims_bp.route('/claim/<ctoken>/<stoken>')
def claim_page(ctoken, stoken):
    booking = Booking.query.filter_by(claim_token=ctoken).first_or_404()
    staff = Staff.query.filter_by(agreement_token=stoken).first_or_404()
    pay = staff.calc_pay(job_price=commissionable(booking), hours_worked=0)
    mine = (booking.assigned_cleaner or '').lower() == (staff.name or '').lower()
    if booking.open_for_claim:
        state = 'open'
    elif mine:
        state = 'mine'
    else:
        state = 'taken'
    return render_template('public/claim.html', b=booking, s=staff, pay=pay, state=state,
                           clash=clash_reason(staff, booking) if state == 'open' else None,
                           biz=_biz(), myday=f"{CRM_BASE}/contractors/my-day/{staff.agreement_token}")


@claims_bp.route('/claim/<ctoken>/<stoken>/claim', methods=['POST'])
def claim_do(ctoken, stoken):
    booking = Booking.query.filter_by(claim_token=ctoken).first_or_404()
    staff = Staff.query.filter_by(agreement_token=stoken).first_or_404()

    # Not available anymore?
    if not booking.open_for_claim:
        return redirect(url_for('claims.claim_page', ctoken=ctoken, stoken=stoken))

    # Time clash guard
    reason = clash_reason(staff, booking)
    if reason:
        pay = staff.calc_pay(job_price=commissionable(booking), hours_worked=0)
        return render_template('public/claim.html', b=booking, s=staff, pay=pay,
                               state='clash', clash=reason, biz=_biz(),
                               myday=f"{CRM_BASE}/contractors/my-day/{staff.agreement_token}")

    # Atomic first-wins: only the update that flips open_for_claim from True succeeds.
    won = Booking.query.filter_by(id=booking.id, open_for_claim=True).update(
        {'assigned_cleaner': staff.name, 'open_for_claim': False,
         'cleaner_response': 'accepted', 'cleaner_notified_at': datetime.utcnow()},
        synchronize_session=False)
    db.session.commit()
    if not won:
        return redirect(url_for('claims.claim_page', ctoken=ctoken, stoken=stoken))

    db.session.refresh(booking)
    # Send the checklist + notify the owner
    try:
        from blueprints.workorders import create_and_send_workorder
        create_and_send_workorder(booking)
    except Exception:
        pass
    _alert_owner(f"✅ {staff.name} claimed the {booking.preferred_date} job ({booking.name}).")
    return redirect(url_for('claims.claim_page', ctoken=ctoken, stoken=stoken))


# ── Release a claimed job back to the board ─────────────────────────────────
@claims_bp.route('/jobs/release/<int:booking_id>/<stoken>', methods=['POST'])
def release(booking_id, stoken):
    booking = Booking.query.get_or_404(booking_id)
    staff = Staff.query.filter_by(agreement_token=stoken).first_or_404()
    if (booking.assigned_cleaner or '').lower() != (staff.name or '').lower():
        return redirect(url_for('contractors.my_day', token=stoken))
    _alert_owner(f"↩️ {staff.name} released the {booking.preferred_date} job ({booking.name}) — re-offering to the team.")
    broadcast_job(booking)   # re-opens + re-texts everyone
    return redirect(url_for('contractors.my_day', token=stoken))
