"""VA commission engine.

Computes what a Lead Specialist (VA) is owed for a given month, from paid bookings
and commercial accounts attributed to them.

Attribution: a Booking / CommercialAccount belongs to the VA when its `agent`
field matches the VA's username. Commission is only earned once the customer has
PAID (Booking.paid_at / CommercialAccount.first_paid_at). Leads from paid ads
(source in PAID_AD_SOURCES) never earn commission, even if the VA worked them.
"""
from datetime import datetime
from calendar import monthrange

# Paid-advertising sources → NEVER earn commission.
PAID_AD_SOURCES = {'google_lsa', 'google', 'lsa', 'meta', 'facebook', 'instagram',
                   'paid', 'paid_ads', 'ads', 'ppc', 'thumbtack', 'yelp_ads'}

DEFAULT_RATES = {
    'va_direct_lead':          20.0,   # one-time residential close
    'va_recurring_clean':       5.0,   # per completed recurring clean
    'va_comm_small_land':      50.0,   'va_comm_small_res':    10.0,   # commercial < $1,000/mo
    'va_comm_standard_land':  100.0,   'va_comm_standard_res': 20.0,   # $1,000–$2,500/mo
    'va_comm_large_land':     150.0,   'va_comm_large_res':    30.0,   # $2,500/mo+
    'va_momentum_bonus':      100.0,   'va_momentum_threshold': 10.0,  # $100 at 10+ closes/mo
}


def _rate(key):
    try:
        from models import PricingSetting
        v = PricingSetting.get(key)
        if v not in (None, ''):
            return float(v)
    except Exception:
        pass
    return DEFAULT_RATES.get(key, 0.0)


def get_rates():
    return {k: _rate(k) for k in DEFAULT_RATES}


def tier_of(monthly_value):
    mv = monthly_value or 0
    if mv < 1000:
        return 'small'
    if mv < 2500:
        return 'standard'
    return 'large'


def _not_paid_ad(source):
    return (source or '').strip().lower() not in PAID_AD_SOURCES


def _month_bounds(year, month):
    start = datetime(year, month, 1)
    end = datetime(year, month, monthrange(year, month)[1], 23, 59, 59)
    return start, end


def commission_for_month(agent, year, month):
    """Return a breakdown dict of everything `agent` earned in the given month."""
    if not agent:
        return _empty(agent, year, month)
    from models import Booking, CommercialAccount
    from extensions import db
    start, end = _month_bounds(year, month)
    R = get_rates()
    lines = []

    # ── Residential: VA bookings paid this month ──
    va_bookings = Booking.query.filter(
        Booking.agent == agent, Booking.paid_at.isnot(None),
        Booking.paid_at >= start, Booking.paid_at <= end).all()
    onetime = recurring = 0
    for b in va_bookings:
        if not _not_paid_ad(b.source):
            continue
        if (b.frequency or 'one_time') == 'one_time':
            onetime += 1
            lines.append(('residential_onetime', f'One-time clean — {b.name}',
                          R['va_direct_lead'], b.paid_at))
        else:
            recurring += 1
            lines.append(('residential_recurring', f'Recurring clean — {b.name}',
                          R['va_recurring_clean'], b.paid_at))

    # ── Commercial landing bonuses (first invoice paid this month) ──
    landings = CommercialAccount.query.filter(
        CommercialAccount.agent == agent,
        CommercialAccount.first_paid_at.isnot(None),
        CommercialAccount.first_paid_at >= start,
        CommercialAccount.first_paid_at <= end).all()
    for a in landings:
        t = tier_of(a.monthly_value)
        lines.append(('commercial_landing', f'Commercial signed — {a.business_name} ({t})',
                      R[f'va_comm_{t}_land'], a.first_paid_at))

    # ── Commercial monthly residuals (active, landed in a PRIOR month) ──
    residuals = CommercialAccount.query.filter(
        CommercialAccount.agent == agent,
        CommercialAccount.first_paid_at.isnot(None),
        CommercialAccount.first_paid_at < start,
        CommercialAccount.status == 'active').all()
    for a in residuals:
        t = tier_of(a.monthly_value)
        lines.append(('commercial_residual', f'Commercial residual — {a.business_name} ({t})',
                      R[f'va_comm_{t}_res'], start))

    # ── Momentum bonus: 10+ NEW closes this month ──
    new_res = _new_residential_closes(agent, start, end)
    total_closes = new_res + len(landings)
    momentum = 0.0
    if total_closes >= R['va_momentum_threshold']:
        momentum = R['va_momentum_bonus']
        lines.append(('momentum', f'Momentum bonus — {int(total_closes)} closes this month',
                      momentum, end))

    line_dicts = [{'type': t, 'label': l, 'amount': round(a, 2), 'when': w}
                  for (t, l, a, w) in sorted(lines, key=lambda x: x[3] or start)]
    return {
        'agent': agent, 'year': year, 'month': month,
        'onetime_closes': onetime, 'recurring_cleans': recurring,
        'comm_landings': len(landings), 'comm_residuals': len(residuals),
        'new_closes': int(total_closes), 'momentum': momentum,
        'lines': line_dicts, 'total': round(sum(a for _, _, a, _ in lines), 2),
    }


def _new_residential_closes(agent, start, end):
    """Distinct residential clients whose FIRST paid VA booking falls in this month."""
    from models import Booking
    from extensions import db
    paid = Booking.query.filter(
        Booking.agent == agent, Booking.paid_at.isnot(None),
        Booking.paid_at >= start, Booking.paid_at <= end).all()
    seen, count = set(), 0
    for b in paid:
        if not _not_paid_ad(b.source):
            continue
        key = (b.email or '').lower() or f'id{b.id}'
        if key in seen:
            continue
        earlier = Booking.query.filter(
            db.func.lower(Booking.email) == key,
            Booking.paid_at.isnot(None), Booking.paid_at < start).count()
        if earlier == 0:
            seen.add(key)
            count += 1
    return count


def _empty(agent, year, month):
    return {'agent': agent, 'year': year, 'month': month, 'onetime_closes': 0,
            'recurring_cleans': 0, 'comm_landings': 0, 'comm_residuals': 0,
            'new_closes': 0, 'momentum': 0.0, 'lines': [], 'total': 0.0}
