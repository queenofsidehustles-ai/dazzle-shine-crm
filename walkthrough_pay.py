"""What a sales rep is owed for the walkthroughs they booked, week by week.

A flat amount for each walkthrough booked (va_commission's va_walkthrough_booked,
$80 until the owner changes it), paid weekly, Monday to Sunday in the business's
own days. Counted from prospect_activity, which writes a row each time somebody
books one (places_finder._record), with the login that did it.

Each business is paid for once. Booking it again -- the date moved, or the same
call logged and then booked from the lead page -- writes a second row, and
paying for that would pay twice for one meeting. The first booking of a business
is the one that counts, and it counts for whoever made it: if the owner booked it
first, no rep is paid for it.

Employees and contractors are counted alike. How the money goes out differs
(payroll or a contractor payment), and the list says which each rep is.

## What qualifies, in one place
A walkthrough qualifies when a Sales login books it (the diary entry or a call
outcome that books one) and it is the first booking of that business. The
booking is the event: not that the visit happened, and not that the business
later signs. A booking cancelled or moved afterwards still qualifies, because
the pay is for getting it in the diary; the owner who disagrees reverses that
week's payment and pays it again, with a reason.

## Paying and reversing is kept for good
Marking a week paid, and reversing a payment, each add a row to
WalkthroughPayEvent with what was counted (the businesses, copied in, so a lead
deleted or renamed later changes nothing), who did it, and why. Nothing here
updates or deletes an event. A reversal removes the live WalkthroughPayment so
the week can be paid again at the right figure, and the event is what remains of
the first payment. This is the application's rule, not the database's: unlike
the quote trail there is no trigger holding the table, so a person with direct
database access can still change it.
"""
import json
from datetime import date, timedelta

from extensions import db


def rate():
    import va_commission
    return va_commission._rate('va_walkthrough_booked')


def week_of(day):
    """The Monday of the week holding `day`."""
    return day - timedelta(days=day.weekday())


def last_week_start(today=None):
    """The Monday of the last full week: what is being paid this week."""
    from scheduling import local_today
    return week_of(today or local_today()) - timedelta(days=7)


def is_over(week_start, today=None):
    """Whether the week has ended in the business's own days. A week is paid
    once, at the figure of the day it is marked, so it cannot be marked while
    bookings can still be added to it."""
    from scheduling import local_today
    return (today or local_today()) > week_start + timedelta(days=6)


def parse_week(value, today=None):
    """A Monday from ?week=YYYY-MM-DD (any day of the week is accepted), or last
    week when it is missing or not a date."""
    try:
        return week_of(date.fromisoformat((value or '').strip()))
    except ValueError:
        return last_week_start(today)


def reps():
    """Sales logins, active or not (a rep who left is still owed for the week
    before they went)."""
    from models import User
    return User.query.filter(User.role == 'sales').order_by(User.name).all()


def _payable_ids(ids):
    """Of these login ids, those a walkthrough can be paid to: a Sales login, or
    one that has since been deleted. A deleted login is still owed for what they
    booked, and its paid weeks must stay on the page. The activity row keeps their
    name; their role is gone with them, so the owner is shown 'login removed'
    and decides whether to pay."""
    from models import User
    ids = {i for i in ids if i is not None}
    if not ids:
        return set()
    existing = {u.id: u.role for u in User.query.filter(User.id.in_(ids)).all()}
    return {i for i in ids if i not in existing or existing[i] == 'sales'}


def credited(week_start):
    """{user id: [activity rows]} -- the walkthroughs each rep is credited with
    for the week beginning `week_start`. See the module note for which count."""
    from models import ProspectActivity as A
    import rep_activity
    start, end = rep_activity.utc_bounds(week_start, week_start + timedelta(days=6))
    first_for_business = (db.session.query(db.func.min(A.id))
                          .filter(A.kind == 'walkthrough_booked', A.prospect_id.isnot(None))
                          .group_by(A.prospect_id))
    rows = (A.query
            .filter(A.kind == 'walkthrough_booked', A.user_id.isnot(None),
                    A.created_at >= start, A.created_at < end,
                    db.or_(A.prospect_id.is_(None), A.id.in_(first_for_business)))
            .order_by(A.created_at).all())
    ok = _payable_ids({r.user_id for r in rows})
    out = {}
    for r in rows:
        if r.user_id in ok:
            out.setdefault(r.user_id, []).append(r)
    return out


def statement(week_start):
    """One line per rep for the week: what they booked, what that comes to, and
    whether it has been paid (and what was paid, which can differ from today's
    figure if the rate has moved since)."""
    from models import User, WalkthroughPayment
    per = rate()
    got = credited(week_start)
    paid = {p.user_id: p for p in WalkthroughPayment.query.filter_by(week_start=week_start).all()}
    ids = set(got) | set(paid)
    users = {u.id: u for u in User.query.filter(User.id.in_(ids or {-1})).all()}
    lines = []
    for uid in ids:
        rows, pay, u = got.get(uid, []), paid.get(uid), users.get(uid)
        # A deleted login keeps the name it was booked and paid under.
        name = u.name if u else ((pay.user_name if pay else None) or (rows[0].user_name if rows else None) or 'Former team member')
        lines.append({
            'user': u, 'user_id': uid, 'name': name, 'removed': u is None,
            'rows': rows, 'count': len(rows),
            'amount': round(len(rows) * per, 2), 'payment': pay,
        })
    lines.sort(key=lambda l: l['name'].lower())
    return {'week_start': week_start, 'week_end': week_start + timedelta(days=6),
            'rate': per, 'lines': lines,
            'owed': round(sum(l['amount'] for l in lines if l['payment'] is None), 2)}


def week_for_user(user_id, week_start):
    """The same figure for one rep: (count, amount, payment or None)."""
    from models import WalkthroughPayment
    n = len(credited(week_start).get(user_id, []))
    pay = WalkthroughPayment.query.filter_by(user_id=user_id, week_start=week_start).first()
    return n, round(n * rate(), 2), pay


def _items(rows):
    """What was counted, copied: the business as it was named when it was paid."""
    return json.dumps([{'prospect_id': r.prospect_id, 'business': r.business_name,
                        'booked_at': r.created_at.isoformat() if r.created_at else None}
                       for r in rows])


def _event(action, pay, items, actor_id, actor_name, reason=None):
    from models import WalkthroughPayEvent
    db.session.add(WalkthroughPayEvent(
        user_id=pay.user_id, user_name=pay.user_name, week_start=pay.week_start,
        action=action, walkthroughs=pay.walkthroughs, amount=pay.amount,
        method=pay.method, items=items, actor_id=actor_id,
        actor_name=(actor_name or '')[:120] or None,
        reason=(reason or '').strip()[:300] or None))


def mark_paid(user_id, week_start, method='zelle', actor_id=None, actor_name=None):
    """Record the week as paid, at the figure worked out now. Returns
    (payment, created): a week already recorded is returned untouched, never
    paid a second time. Added to the session, with its event; the caller
    commits."""
    from models import User, WalkthroughPayment
    existing = WalkthroughPayment.query.filter_by(user_id=user_id, week_start=week_start).first()
    if existing:
        return existing, False
    if not is_over(week_start):
        return None, False
    user = db.session.get(User, user_id)
    rows = credited(week_start).get(user_id, [])
    n, amount = len(rows), round(len(rows) * rate(), 2)
    if n == 0:
        return None, False
    name = user.name if user else (rows[0].user_name or 'Former team member')
    pay = WalkthroughPayment(
        user_id=user_id, user_name=name, week_start=week_start, walkthroughs=n,
        amount=amount, method=(method or 'zelle')[:20],
        note=f'{name} walkthroughs, week of {week_start.isoformat()}')
    db.session.add(pay)
    _event('paid', pay, _items(rows), actor_id, actor_name)
    return pay, True


def reverse(payment, actor_id=None, actor_name=None, reason=''):
    """Take a payment back, saying why. False when no reason is given: a payment
    that was made and is being undone is exactly what needs one. The event keeps
    the figure and what was counted; the live record goes so the week can be paid
    again. The caller commits."""
    if not (reason or '').strip():
        return False
    from models import WalkthroughPayEvent
    paid = (WalkthroughPayEvent.query
            .filter_by(user_id=payment.user_id, week_start=payment.week_start, action='paid')
            .order_by(WalkthroughPayEvent.id.desc()).first())
    _event('reversed', payment, paid.items if paid else None, actor_id, actor_name, reason)
    db.session.delete(payment)
    return True


def history(week_start):
    """Every payment and reversal for the week, oldest first."""
    from models import WalkthroughPayEvent
    return (WalkthroughPayEvent.query.filter_by(week_start=week_start)
            .order_by(WalkthroughPayEvent.id).all())
