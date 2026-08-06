"""The money picture: what came in, what went out, what's actually left.

Revenue here is CASH BASIS — a job counts on the day the money landed
(Booking.paid_at), not the day it was booked. The dashboard used to sum every
confirmed booking by its created_at date, which counted jobs that hadn't
happened yet and filed them in the month they were booked rather than the month
they were paid. That's booked value, not income, and subtracting real expenses
from it produces a profit figure that's confidently wrong.

Money going out comes from three places that each own their own records:
  · cleaner pay      → ContractorPayment  (written by the payroll screen)
  · card fees        → ProcessingFee      (synced from Stripe)
  · VA commissions   → CommissionPayment  (written by the commissions screen)
Everything else the owner spends is typed into Expense. Those four are kept
separate on purpose: a payout that could also be hand-entered as an expense is a
payout that eventually gets counted twice.
"""
from calendar import monthrange
from datetime import date, datetime, timedelta

from sqlalchemy import func

from extensions import db
from models import (ADVERTISING_CATEGORIES, CATEGORY_GROUP, CATEGORY_LABELS,
                    CATEGORY_SCHEDULE_C, Booking, CommissionPayment,
                    ContractorPayment, Expense, ProcessingFee)


# ── Periods ─────────────────────────────────────────────────────────────────
def month_bounds(year, month):
    """First and last day of a month, inclusive."""
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def period_bounds(kind, year, month):
    """(start, end, label) for the period the user picked."""
    if kind == 'quarter':
        q = (month - 1) // 3
        start = date(year, q * 3 + 1, 1)
        end_month = q * 3 + 3
        end = date(year, end_month, monthrange(year, end_month)[1])
        return start, end, f'Q{q + 1} {year}'
    if kind == 'year':
        return date(year, 1, 1), date(year, 12, 31), f'{year}'
    start, end = month_bounds(year, month)
    return start, end, start.strftime('%B %Y')


def months_in(start, end):
    """Every (year, month) the range touches."""
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _dt_bounds(start, end):
    """Datetime range covering the whole of both end days."""
    return datetime.combine(start, datetime.min.time()), \
           datetime.combine(end + timedelta(days=1), datetime.min.time())


# ── Money in ────────────────────────────────────────────────────────────────
def revenue_between(start, end):
    """Cash actually received in the period — jobs by the date they were PAID."""
    lo, hi = _dt_bounds(start, end)
    total = db.session.query(func.sum(Booking.price)).filter(
        Booking.paid_at.isnot(None), Booking.paid_at >= lo, Booking.paid_at < hi,
    ).scalar()
    return round(float(total or 0), 2)


def jobs_paid_between(start, end):
    lo, hi = _dt_bounds(start, end)
    return db.session.query(func.count(Booking.id)).filter(
        Booking.paid_at.isnot(None), Booking.paid_at >= lo, Booking.paid_at < hi,
    ).scalar() or 0


def booked_value_between(start, end):
    """The OLD measure — confirmed + completed by booking date. Kept so the P&L
    can show what's in the pipeline next to what's actually banked."""
    lo, hi = _dt_bounds(start, end)
    total = db.session.query(func.sum(Booking.price)).filter(
        Booking.status.in_(['completed', 'confirmed']),
        Booking.created_at >= lo, Booking.created_at < hi,
    ).scalar()
    return round(float(total or 0), 2)


def unpaid_outstanding():
    """Work that's done or confirmed but nobody has paid for yet."""
    total = db.session.query(func.sum(Booking.price)).filter(
        Booking.paid_at.is_(None),
        Booking.status.in_(['confirmed', 'completed']),
    ).scalar()
    return round(float(total or 0), 2)


def lead_fees_collected_between(start, end):
    """Advertising money recovered inside the prices customers paid."""
    lo, hi = _dt_bounds(start, end)
    total = db.session.query(func.sum(Booking.lead_fee)).filter(
        Booking.paid_at.isnot(None), Booking.paid_at >= lo, Booking.paid_at < hi,
    ).scalar()
    return round(float(total or 0), 2)


# ── Money out ───────────────────────────────────────────────────────────────
def contractor_payments_between(start, end):
    """The individual payouts behind the cleaner-pay total, so the figure on the
    P&L can be opened up and checked rather than taken on trust."""
    lo, hi = _dt_bounds(start, end)
    return ContractorPayment.query.filter(
        ContractorPayment.created_at >= lo, ContractorPayment.created_at < hi,
        ContractorPayment.status == 'paid',
    ).order_by(ContractorPayment.created_at).all()


def contractor_pay_between(start, end):
    """Every payout written by the payroll screen — solo jobs and crew shares.

    Labor only. Tips are excluded on purpose: they're the customer's money
    passing through, so counting them here would inflate labor, drag margin
    down on every tipped job, and trip the floor-price warnings for no reason."""
    lo, hi = _dt_bounds(start, end)
    total = db.session.query(func.sum(ContractorPayment.amount)).filter(
        ContractorPayment.created_at >= lo, ContractorPayment.created_at < hi,
        ContractorPayment.status == 'paid',
    ).scalar()
    return round(float(total or 0), 2)


def tips_between(start, end):
    """Where the tip money went: what customers gave, what the card processor
    took, the owner's share when she worked the job herself, and what reached
    the cleaners.

    Only the owner's share is hers — that part is income. The rest passes
    through and must never touch revenue, labor or margin."""
    lo, hi = _dt_bounds(start, end)
    paid_jobs = Booking.query.filter(
        Booking.paid_at.isnot(None), Booking.paid_at >= lo, Booking.paid_at < hi,
        Booking.tip_amount > 0,
    ).all()
    collected = round(sum(b.tip_amount or 0 for b in paid_jobs), 2)
    card_fee = round(sum(b.tip_fee for b in paid_jobs), 2)
    passed_on = db.session.query(func.sum(ContractorPayment.tip_amount)).filter(
        ContractorPayment.created_at >= lo, ContractorPayment.created_at < hi,
        ContractorPayment.status == 'paid',
    ).scalar()
    passed_on = round(float(passed_on or 0), 2)
    # Whatever's left after the card fee and what she handed out is hers —
    # derived from what actually happened rather than from any split rule.
    return {
        'collected': collected,
        'card_fee': card_fee,
        'passed_on': passed_on,
        'owner_share': round(collected - card_fee - passed_on, 2),
    }


def commissions_paid_between(start, end):
    lo, hi = _dt_bounds(start, end)
    total = db.session.query(func.sum(CommissionPayment.amount)).filter(
        CommissionPayment.paid_at >= lo, CommissionPayment.paid_at < hi,
    ).scalar()
    return round(float(total or 0), 2)


def processing_fees_between(start, end):
    """What Stripe kept. Returns (amount, months_missing) so the page can say
    'sync August' instead of quietly reporting $0 as though cards were free."""
    wanted = months_in(start, end)
    rows = ProcessingFee.query.filter(
        db.tuple_(ProcessingFee.year, ProcessingFee.month).in_(wanted)
    ).all() if wanted else []
    have = {(r.year, r.month) for r in rows}
    missing = [ym for ym in wanted if ym not in have]
    return round(sum(r.amount or 0 for r in rows), 2), missing


def expenses_between(start, end):
    """Hand-entered costs, newest first."""
    return Expense.query.filter(
        Expense.date >= start.isoformat(), Expense.date <= end.isoformat(),
    ).order_by(Expense.date.desc(), Expense.id.desc()).all()


# ── The whole picture ───────────────────────────────────────────────────────
def profit_and_loss(start, end):
    """Everything the P&L page needs, in one pass."""
    revenue = revenue_between(start, end)
    contractor = contractor_pay_between(start, end)
    commissions = commissions_paid_between(start, end)
    fees, fee_months_missing = processing_fees_between(start, end)

    tips = tips_between(start, end)

    rows = expenses_between(start, end)
    by_cat = {}
    for e in rows:
        c = by_cat.setdefault(e.category or 'other', {
            'key': e.category or 'other',
            'label': CATEGORY_LABELS.get(e.category, (e.category or 'Other').title()),
            'group': CATEGORY_GROUP.get(e.category, 'Overhead'),
            'schedule_c': CATEGORY_SCHEDULE_C.get(e.category, 'Line 27a — Other'),
            'amount': 0.0, 'count': 0, 'miles': 0.0,
        })
        c['amount'] += e.amount or 0
        c['count'] += 1
        c['miles'] += e.miles or 0
    for c in by_cat.values():
        c['amount'] = round(c['amount'], 2)
    categories = sorted(by_cat.values(), key=lambda c: c['amount'], reverse=True)

    typed_total = round(sum(c['amount'] for c in categories), 2)
    # Cleaner pay and card fees are direct costs of doing the job — taking them
    # off first shows what the work itself actually yields.
    gross_profit = round(revenue - contractor - fees, 2)
    net_profit = round(gross_profit - commissions - typed_total + tips['owner_share'], 2)

    ad_spend = round(sum(c['amount'] for c in categories
                         if c['key'] in ADVERTISING_CATEGORIES), 2)
    lead_fees = lead_fees_collected_between(start, end)

    return {
        'start': start, 'end': end,
        'revenue': revenue,
        'jobs_paid': jobs_paid_between(start, end),
        'contractor_pay': contractor,
        'contractor_payments': contractor_payments_between(start, end),
        'tips': tips,
        'processing_fees': fees,
        'fee_months_missing': fee_months_missing,
        'commissions': commissions,
        'gross_profit': gross_profit,
        'categories': categories,
        'expense_total': typed_total,
        'total_out': round(contractor + fees + commissions + typed_total, 2),
        'net_profit': net_profit,
        'margin': round(net_profit / revenue * 100, 1) if revenue else 0.0,
        'mileage_miles': round(sum(c['miles'] for c in categories), 1),
        # Is the lead fee baked into prices actually covering the ad bills?
        'lead_fees_collected': lead_fees,
        'ad_spend': ad_spend,
        'lead_fee_delta': round(lead_fees - ad_spend, 2),
        # Context, not income
        'booked_value': booked_value_between(start, end),
        'unpaid_outstanding': unpaid_outstanding(),
        'expenses': rows,
    }


def job_economics(start, end):
    """Per-job margin, and the aggregates behind it.

    Answers the questions the P&L can't: which jobs actually make money, what
    discounting really costs, which lead sources are worth buying, and what each
    cleaner is genuinely earning per hour — the last being the early warning
    that someone is about to quit.

    Counted by job date, not payment date: this is about whether the WORK is
    profitable, which is a different question from when cash moved."""
    jobs = Booking.query.filter(
        Booking.preferred_date >= start.isoformat(),
        Booking.preferred_date <= end.isoformat(),
        Booking.status.in_(['completed', 'confirmed', 'in_progress']),
    ).order_by(Booking.preferred_date).all()

    rows, by_source, by_cleaner, below_floor = [], {}, {}, []
    for b in jobs:
        # What the job actually costs to get cleaned — the amounts committed to
        # the people on it, not the theoretical value of its hours.
        labor = b.committed_labor
        if labor is None:                       # legacy percentage job
            labor = round(b.commissionable_price * 0.5, 2)
        price = b.price or 0
        lead_fee = b.lead_fee or 0
        discount = b.discount_amount or 0
        # What's left after paying for the cleaning and the ad that won it.
        margin = round(price - labor - lead_fee, 2)
        row = {
            'booking': b,
            'price': price,
            'baseline': round(price + discount, 2),
            'discount': discount,
            'labor': labor,
            'lead_fee': lead_fee,
            'margin': margin,
            'labor_pct': round(labor / price * 100, 1) if price else 0,
            'margin_pct': round(margin / price * 100, 1) if price else 0,
            'hours': b.estimated_hours,
            'floor': b.floor_price,
            'under_floor': b.below_floor_by,
        }
        rows.append(row)
        if b.below_floor_by:
            below_floor.append(row)

        src = (b.source or 'unknown').strip().lower() or 'unknown'
        s = by_source.setdefault(src, {'source': src, 'jobs': 0, 'revenue': 0.0,
                                       'labor': 0.0, 'lead_fee': 0.0, 'discount': 0.0,
                                       'margin': 0.0})
        s['jobs'] += 1
        for k, v in (('revenue', price), ('labor', labor), ('lead_fee', lead_fee),
                     ('discount', discount), ('margin', margin)):
            s[k] += v

        # Effective hourly per cleaner — what they're really earning.
        if b.crew:
            people = [(c.staff.name, c.pay_amount or 0, b.hours_each() or 0)
                      for c in b.crew if c.staff]
        elif b.assigned_cleaner:
            people = [(b.assigned_cleaner, labor, b.estimated_hours or 0)]
        else:
            people = []
        for name, paid, hrs in people:
            c = by_cleaner.setdefault(name, {'name': name, 'jobs': 0, 'paid': 0.0, 'hours': 0.0})
            c['jobs'] += 1
            c['paid'] += paid
            c['hours'] += hrs

    for s in by_source.values():
        for k in ('revenue', 'labor', 'lead_fee', 'discount', 'margin'):
            s[k] = round(s[k], 2)
        s['margin_pct'] = round(s['margin'] / s['revenue'] * 100, 1) if s['revenue'] else 0
        s['cost_per_job'] = round(s['lead_fee'] / s['jobs'], 2) if s['jobs'] else 0
    for c in by_cleaner.values():
        c['paid'] = round(c['paid'], 2)
        c['hours'] = round(c['hours'], 2)
        c['effective_hourly'] = round(c['paid'] / c['hours'], 2) if c['hours'] else None

    revenue = round(sum(r['price'] for r in rows), 2)
    labor_total = round(sum(r['labor'] for r in rows), 2)
    return {
        'start': start, 'end': end,
        'rows': rows,
        'jobs': len(rows),
        'revenue': revenue,
        'baseline': round(sum(r['baseline'] for r in rows), 2),
        'discount_total': round(sum(r['discount'] for r in rows), 2),
        'labor_total': labor_total,
        'lead_fee_total': round(sum(r['lead_fee'] for r in rows), 2),
        'margin_total': round(sum(r['margin'] for r in rows), 2),
        'labor_pct': round(labor_total / revenue * 100, 1) if revenue else 0,
        'margin_pct': round(sum(r['margin'] for r in rows) / revenue * 100, 1) if revenue else 0,
        'by_source': sorted(by_source.values(), key=lambda s: s['margin'], reverse=True),
        'by_cleaner': sorted(by_cleaner.values(),
                             key=lambda c: c['effective_hourly'] or 0),
        'below_floor': below_floor,
    }


def monthly_trend(months=6, today=None):
    """Revenue vs net profit for the last N months, oldest first — for the chart."""
    today = today or date.today()
    out = []
    y, m = today.year, today.month
    stack = []
    for _ in range(months):
        stack.append((y, m))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    for yy, mm in reversed(stack):
        s, e = month_bounds(yy, mm)
        p = profit_and_loss(s, e)
        out.append({'month': s.strftime('%b %Y'),
                    'revenue': p['revenue'], 'profit': p['net_profit']})
    return out
