"""Talking to the team, and hearing back from them.

Two things that share the same plumbing — reaching everyone at once:

  · Broadcast   — one message to the whole crew (a thank-you, a heads-up,
                  happy birthday), by text, email, or both.
  · Availability — a weekly ask that comes back as data. Each cleaner gets a
                  personal link, taps the days they can work, and the answers
                  land in the CRM so the week can be planned from what people
                  actually said rather than from remembering replies.
"""
import secrets
from datetime import date, datetime, timedelta

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from auth import login_required, owner_required
from extensions import db
from models import Availability, BusinessSetting, Staff
from notifications import send_email, send_sms
from translate import translate
import branding

team_bp = Blueprint('team', __name__, url_prefix='/team')
# The cleaner's own page sits at the root so the texted link stays short.
availability_bp = Blueprint('availability', __name__)



def _biz():
    return branding.biz_name()


def _ensure_token(s):
    """Every personal link hangs off this token — the same one My Day and the
    claim board use."""
    if not s.agreement_token:
        s.agreement_token = secrets.token_urlsafe(32)
        db.session.commit()
    return s.agreement_token


def week_start(d=None, offset=1):
    """Monday of a week. offset=0 this week, 1 next week."""
    d = d or date.today()
    monday = d - timedelta(days=d.weekday())
    return monday + timedelta(weeks=offset)


def week_days(start):
    return [start + timedelta(days=i) for i in range(7)]


def _recipients():
    return Staff.query.filter_by(is_active=True).order_by(Staff.name).all()


# ── Broadcast: one message to everyone ──────────────────────────────────────
@team_bp.route('/broadcast', methods=['GET', 'POST'])
@owner_required
def broadcast():
    """Send the same message to the whole team at once."""
    people = _recipients()

    if request.method == 'POST':
        message = (request.form.get('message') or '').strip()
        subject = (request.form.get('subject') or '').strip() or f'A note from {_biz()}'
        channel = request.form.get('channel', 'sms')
        picked = set(request.form.getlist('staff_ids'))

        if not message:
            flash('Write a message first.', 'error')
            return redirect(url_for('team.broadcast'))

        targets = [s for s in people if not picked or str(s.id) in picked]
        if not targets:
            flash('Nobody selected.', 'error')
            return redirect(url_for('team.broadcast'))

        texted, emailed, missed = [], [], []
        for s in targets:
            body = message
            if (s.language or 'en') == 'es':
                body = translate(message, target='es')
            first = (s.name or '').split()[0] if s.name else ''
            personal = body.replace('{name}', first)

            reached = False
            if channel in ('sms', 'both') and s.phone:
                ok, _ = send_sms(s.phone, personal)
                if ok:
                    texted.append(s.name)
                    reached = True
            if channel in ('email', 'both') and s.email:
                ok, _ = send_email(
                    to_email=s.email, to_name=s.name, subject=subject,
                    html=f"""
<div style="font-family:Inter,sans-serif;max-width:520px;margin:0 auto;color:#1f1333">
  <p style="white-space:pre-wrap;line-height:1.7;font-size:1rem">{personal}</p>
  <p style="color:#9a95ad;font-size:0.85rem;margin-top:22px">— {_biz()}</p>
</div>""")
                if ok:
                    emailed.append(s.name)
                    reached = True
            if not reached:
                missed.append(s.name)

        bits = []
        if texted:
            bits.append(f'texted {len(texted)}')
        if emailed:
            bits.append(f'emailed {len(emailed)}')
        flash(f'Sent — {" and ".join(bits)}.' if bits else 'Nothing sent.',
              'success' if bits else 'warning')
        if missed:
            flash(f'⚠️ Could not reach {", ".join(missed)} — check their phone and email '
                  f'on the Team page.', 'warning')
        return redirect(url_for('team.broadcast'))

    return render_template('admin/team_broadcast.html', people=people)


# ── Availability: the weekly ask, and what came back ────────────────────────
@team_bp.route('/availability')
@owner_required
def availability():
    """Who can work next week — the grid, and who hasn't answered."""
    try:
        offset = int(request.args.get('week', 1))
    except ValueError:
        offset = 1
    start = week_start(offset=offset)
    days = week_days(start)
    people = _recipients()

    day_keys = [d.isoformat() for d in days]
    rows = Availability.query.filter(Availability.day.in_(day_keys)).all()
    answers = {(a.staff_id, a.day): a for a in rows}
    replied = {a.staff_id for a in rows}

    # Free bodies per day — the number she's actually planning against.
    per_day = {k: sum(1 for s in people
                      if (s.id, k) in answers and answers[(s.id, k)].available)
               for k in day_keys}

    return render_template('admin/team_availability.html',
        people=people, days=days, day_keys=day_keys, answers=answers,
        replied=replied, per_day=per_day, start=start, offset=offset,
        waiting=[s for s in people if s.id not in replied])


@team_bp.route('/availability/ask', methods=['POST'])
@owner_required
def ask_availability():
    """Text everyone their personal link for a given week."""
    try:
        offset = int(request.form.get('week', 1))
    except ValueError:
        offset = 1
    start = week_start(offset=offset)
    only_waiting = bool(request.form.get('only_waiting'))

    people = _recipients()
    if only_waiting:
        keys = [d.isoformat() for d in week_days(start)]
        answered = {a.staff_id for a in
                    Availability.query.filter(Availability.day.in_(keys)).all()}
        people = [s for s in people if s.id not in answered]

    label = f"{start.strftime('%b %-d')}–{(start + timedelta(days=6)).strftime('%b %-d')}"
    sent, missed = [], []
    for s in people:
        if not s.phone:
            missed.append(s.name)
            continue
        link = f"{branding.crm_base()}/availability/{_ensure_token(s)}/{start.isoformat()}"
        first = (s.name or '').split()[0]
        msg = (f"Hi {first}! Which days can you work {label}? "
               f"Tap to tell us — takes 10 seconds 👉 {link} — {_biz()}")
        if (s.language or 'en') == 'es':
            msg = translate(msg, target='es')
        ok, _ = send_sms(s.phone, msg)
        (sent if ok else missed).append(s.name)

    if sent:
        flash(f'Asked {len(sent)} cleaner{"s" if len(sent) != 1 else ""} about {label}.', 'success')
    if missed:
        flash(f'⚠️ Could not reach {", ".join(missed)} — no phone number, or the text failed.',
              'warning')
    return redirect(url_for('team.availability', week=offset))


# ── The cleaner's page (public, personal link) ──────────────────────────────
@availability_bp.route('/availability/<token>/<start>', methods=['GET'])
def availability_page(token, start):
    s = Staff.query.filter_by(agreement_token=token).first_or_404()
    try:
        monday = date.fromisoformat(start)
    except ValueError:
        monday = week_start()
    days = week_days(monday)
    mine = {a.day: a for a in Availability.query.filter(
        Availability.staff_id == s.id,
        Availability.day.in_([d.isoformat() for d in days])).all()}
    return render_template('public/availability.html', s=s, days=days,
                           mine=mine, start=monday, biz=_biz(),
                           saved=request.args.get('saved'))


@availability_bp.route('/availability/<token>/<start>', methods=['POST'])
def availability_save(token, start):
    s = Staff.query.filter_by(agreement_token=token).first_or_404()
    try:
        monday = date.fromisoformat(start)
    except ValueError:
        monday = week_start()
    picked = set(request.form.getlist('days'))

    for d in week_days(monday):
        key = d.isoformat()
        row = Availability.query.filter_by(staff_id=s.id, day=key).first()
        if not row:
            row = Availability(staff_id=s.id, day=key)
            db.session.add(row)
        row.available = key in picked
        row.note = (request.form.get(f'note_{key}') or '').strip() or None
        row.updated_at = datetime.utcnow()
    db.session.commit()

    # Let the owner know an answer landed, so she isn't refreshing the page.
    phone = BusinessSetting.get('owner_alert_phone') or BusinessSetting.get('phone')
    if phone:
        try:
            n = len(picked)
            send_sms(phone, f"📅 {s.name} can work {n} day{'s' if n != 1 else ''} "
                            f"the week of {monday.strftime('%b %-d')}.")
        except Exception:
            pass
    return redirect(url_for('availability.availability_page', token=token,
                            start=monday.isoformat(), saved=1))
