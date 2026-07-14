"""Commercial quote logic — the 'pricing brain'.

Cost-based method so every quote is profitable:
  hours   = square_footage / production_rate(facility type)
  labor   = hours x your cleaner hourly cost
  price   = labor / target_labor_percent   (labor should be ~40% of the price;
            the other 60% covers supplies, overhead, and your profit)
  price   = at least the minimum-visit floor

All numbers are owner-editable in Settings → Commercial pricing; these are just
the starting defaults. Overrides are stored in the existing PricingSetting table.
"""

# Starting defaults (owner can change all of these in settings)
DEFAULTS = {
    'comm_hourly_cost': 20.0,    # what ONE cleaner costs YOU per hour
    'comm_target_labor': 0.40,   # labor as a share of price (0.40 = 40%)
    'comm_min_visit': 80.0,      # never quote a single visit below this
}

# Square feet one cleaner can cover per hour, by facility type.
# Lower = slower/more detailed work = higher price.
PROD_RATES = {
    'office': 3000,
    'property_manager': 3000,
    'realtor': 3000,
    'apartment': 2200,
    'daycare': 2500,
    'medical_office': 2000,
    'airbnb': 1500,
    'other': 3000,
}

# Roughly how many cleaning visits land in a month, by frequency.
VISITS_PER_MONTH = {
    'nightly': 22, 'weekly': 4.3, 'biweekly': 2.15, 'monthly': 1, 'custom': 4.3,
}


def _get(key):
    """Read an owner override from PricingSetting, else the default."""
    try:
        from models import PricingSetting
        v = PricingSetting.get(key)
        if v not in (None, ''):
            return float(v)
    except Exception:
        pass
    return DEFAULTS.get(key)


def prod_rate(category):
    try:
        from models import PricingSetting
        v = PricingSetting.get(f'comm_prod_{category}')
        if v not in (None, ''):
            return float(v)
    except Exception:
        pass
    return PROD_RATES.get(category, 3000)


def quote(square_footage, category='office', frequency='weekly'):
    """Return a confident, profitable price for one commercial account."""
    sqft = max(0.0, float(square_footage or 0))
    rate = prod_rate(category) or 3000
    hourly = _get('comm_hourly_cost')
    target = _get('comm_target_labor') or 0.40
    min_visit = _get('comm_min_visit')

    hours = sqft / rate if rate else 0.0
    labor = hours * hourly
    price = (labor / target) if target else labor
    price = max(price, min_visit if sqft else 0.0)
    vpm = VISITS_PER_MONTH.get(frequency, 4.3)

    return {
        'square_footage': int(sqft),
        'hours': round(hours, 2),
        'labor_cost': round(labor, 2),
        'price_per_visit': round(price, 2),
        'monthly': round(price * vpm, 2),
        'your_profit_per_visit': round(price - labor, 2),
    }


def get_config():
    """JSON-serializable config for the in-browser live calculator."""
    return {
        'hourly': _get('comm_hourly_cost'),
        'target': _get('comm_target_labor') or 0.40,
        'min_visit': _get('comm_min_visit'),
        'prod_rates': {c: prod_rate(c) for c in PROD_RATES},
        'visits_per_month': VISITS_PER_MONTH,
    }
