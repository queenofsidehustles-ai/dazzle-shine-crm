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
"""
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


def parse_week(value, today=None):
    """A Monday from ?week=YYYY-MM-DD (any day of the week is accepted), or last
    week when it is missing or not a date."""
    try:
        return week_of(date.fromisoformat((value or '').strip()))
    except ValueError:
        return last_week_start(today)


def reps():
    """Everyone who can be paid this way: Sales logins, active or not (a rep
    who left is still owed for the week before they went)."""
    from models import User
    return User.query.filter(User.role == 'sales').order_by(User.name).all()


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
            .filter(A.kind == 'walkthrough_booked',
                    A.user_id.in_([u.id for u in reps()] or [-1]),
                    A.created_at >= start, A.created_at < end,
                    db.or_(A.prospect_id.is_(None), A.id.in_(first_for_business)))
            .order_by(A.created_at).all())
    out = {}
    for r in rows:
        out.setdefault(r.user_id, []).append(r)
    return out


def statement(week_start):
    """One line per rep for the week: what they booked, what that comes to, and
    whether it has been paid (and what was paid, which can differ from today's
    figure if the rate has moved since)."""
    from models import WalkthroughPayment
    per = rate()
    got = credited(week_start)
    paid = {p.user_id: p for p in WalkthroughPayment.query.filter_by(week_start=week_start).all()}
    lines = []
    for u in reps():
        rows = got.get(u.id, [])
        pay = paid.get(u.id)
        if not rows and pay is None:
            continue
        lines.append({
            'user': u, 'rows': rows, 'count': len(rows),
            'amount': round(len(rows) * per, 2), 'payment': pay,
        })
    return {'week_start': week_start, 'week_end': week_start + timedelta(days=6),
            'rate': per, 'lines': lines,
            'owed': round(sum(l['amount'] for l in lines if l['payment'] is None), 2)}


def week_for_user(user_id, week_start):
    """The same figure for one rep: (count, amount, payment or None)."""
    from models import WalkthroughPayment
    n = len(credited(week_start).get(user_id, []))
    pay = WalkthroughPayment.query.filter_by(user_id=user_id, week_start=week_start).first()
    return n, round(n * rate(), 2), pay


def mark_paid(user_id, week_start, method='zelle'):
    """Record the week as paid, at the figure worked out now. Returns
    (payment, created): a week already recorded is returned untouched, never
    paid a second time. Added to the session; the caller commits."""
    from models import User, WalkthroughPayment
    existing = WalkthroughPayment.query.filter_by(user_id=user_id, week_start=week_start).first()
    if existing:
        return existing, False
    user = db.session.get(User, user_id)
    n, amount, _ = week_for_user(user_id, week_start)
    if user is None or user.role != 'sales' or n == 0:
        return None, False
    pay = WalkthroughPayment(
        user_id=user_id, user_name=user.name, week_start=week_start, walkthroughs=n,
        amount=amount, method=(method or 'zelle')[:20],
        note=f'{user.name} walkthroughs, week of {week_start.isoformat()}')
    db.session.add(pay)
    return pay, True
