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

# The quote comes back as a range so you can quote confidently, never below cost.
RANGE_LOW = 0.85
RANGE_HIGH = 1.20

# Friendly facility choices shown as Step-1 buttons (key, label, one-line help).
FACILITY_TYPES = [
    ('office', '🏢 Office', 'Offices, cubicles, meeting rooms'),
    ('daycare', '🧸 Daycare', 'Childcare centers & preschools'),
    ('medical_office', '🩺 Medical', 'Doctor / dental offices, clinics'),
    ('apartment', '🏘️ Apartments', 'Complexes, common areas, turnovers'),
    ('property_manager', '🏢 Property Mgmt', 'Managed buildings'),
    ('other', '📦 Other', 'Retail, gyms, churches, etc.'),
]

# Optional scope add-ons (key, label, % added to the price).
EXTRAS = [
    ('restrooms', '🚻 Restroom deep-clean', 0.10),
    ('breakroom', '🍽️ Break room / kitchen', 0.08),
    ('trash', '🗑️ Trash & liner service', 0.05),
    ('disinfection', '🧴 Disinfect high-touch', 0.08),
]


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


def quote(square_footage, category='office', frequency='weekly', extras=None):
    """Return a confident, profitable price with a low/standard/premium range."""
    extras = extras or []
    sqft = max(0.0, float(square_footage or 0))
    rate = prod_rate(category) or 3000
    hourly = _get('comm_hourly_cost')
    target = _get('comm_target_labor') or 0.40
    min_visit = _get('comm_min_visit')

    hours = sqft / rate if rate else 0.0
    labor = hours * hourly
    price = (labor / target) if target else labor
    extra_pct = sum(pct for key, _lbl, pct in EXTRAS if key in extras)
    price = price * (1 + extra_pct)
    price = max(price, min_visit if sqft else 0.0)

    vpm = VISITS_PER_MONTH.get(frequency, 4.3)
    standard = round(price)
    monthly = round(standard * vpm)
    return {
        'square_footage': int(sqft),
        'hours': round(hours, 2),
        'labor_cost': round(labor, 2),
        'low': round(price * RANGE_LOW),
        'standard': standard,
        'premium': round(price * RANGE_HIGH),
        'per_visit': standard,          # what we save on the account
        'monthly': monthly,
        'annual': monthly * 12,
        'profit_per_visit': round(standard - labor),
    }


def get_config():
    """JSON-serializable config for the in-browser live calculator."""
    return {
        'hourly': _get('comm_hourly_cost'),
        'target': _get('comm_target_labor') or 0.40,
        'min_visit': _get('comm_min_visit'),
        'prod_rates': {c: prod_rate(c) for c in PROD_RATES},
        'visits_per_month': VISITS_PER_MONTH,
        'facility_types': [{'key': k, 'label': l, 'desc': d} for k, l, d in FACILITY_TYPES],
        'extras': [{'key': k, 'label': l, 'pct': p} for k, l, p in EXTRAS],
        'range_low': RANGE_LOW, 'range_high': RANGE_HIGH,
    }
