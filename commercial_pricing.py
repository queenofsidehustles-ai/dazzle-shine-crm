"""Commercial quote logic — the pricing brain, and now actually the brain.

Cost-based method so every quote is profitable:

  on-site hours = square_footage / production_rate(facility type)
  on-site labor = hours x your cleaner hourly cost
  price         = labor / target_labor_percent   (labor should be ~40% of the
                  price; the other 60% covers supplies, overhead and profit)
  price         = at least the minimum-visit floor
  price        += the drive, priced the same way as the cleaning

## Travel is added after the floor, on purpose

The minimum-visit fee answers "is this stop worth making at all". The drive
answers "how far is this particular customer". They are different questions,
so the drive sits outside the floor and always moves the number: a small job
forty minutes away costs more than the same job ten minutes away, which is
true and used not to be. Folded inside the floor, travel was invisible on
every job small enough to hit it — which is most small jobs, which are exactly
the ones where the drive is the largest share of the work.

Driving is priced like cleaning rather than recovered at cost. It is paid time
either way, and an hour spent in a van is an hour that cannot be sold to
anybody else.

## Where these numbers came from

The originals quoted a flat 1.7 cents per square foot per visit — a 5,000 sq
ft weekly office at $83 — because they assumed one cleaner covers 3,000 sq ft
an hour, which is a 5,000 sq ft office fully cleaned in 1 hour 40 minutes, and
because the $20 hourly figure was a wage rather than what an hour of somebody's
time actually costs once tax, supplies and travel are in it.

They are still only defaults. The right production rate is the one a company
can measure from its own finished jobs: square footage divided by the hours
somebody actually clocked. Every number here is owner-editable in
Settings → Commercial pricing, and an override always wins.
"""

# Starting defaults (owner can change all of these in settings)
DEFAULTS = {
    'comm_hourly_cost': 25.0,    # what ONE cleaner costs YOU per hour, loaded
    'comm_target_labor': 0.40,   # labor as a share of price (0.40 = 40%)
    'comm_min_visit': 125.0,     # never quote a single visit below this
    'comm_drive_minutes': 30.0,  # round trip, per visit, unless told otherwise
}

# Square feet one cleaner can cover per hour, by facility type.
# Lower = slower/more detailed work = higher price.
PROD_RATES = {
    'office': 2000,
    'property_manager': 2000,
    'realtor': 2000,
    'apartment': 1500,
    'daycare': 1700,
    'medical_office': 1300,
    'airbnb': 800,
    'other': 2000,
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

# Optional scope add-ons (key, label, % added to the price). The percentages
# are starting defaults — owners who have priced their own market can change
# each one in Settings → Commercial pricing, same as the rates above.
EXTRAS = [
    ('restrooms', '🚻 Restroom deep-clean', 0.10),
    ('breakroom', '🍽️ Break room / kitchen', 0.08),
    ('trash', '🗑️ Trash & liner service', 0.05),
    ('disinfection', '🧴 Disinfect high-touch', 0.08),
]

# Scope that isn't really optional for some facility types. A medical clean
# carries the disinfection protocol whether or not anyone remembers to tick the
# box, so the price has to carry it too — leaving it unticked was quoting exam
# rooms at office rates. Pre-ticked in the calculator, still removable.
DEFAULT_EXTRAS = {
    'medical_office': ['disinfection'],
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


def extra_pct(key):
    """What one add-on adds to the price, as a decimal. Owner override wins."""
    try:
        from models import PricingSetting
        v = PricingSetting.get(f'comm_extra_{key}')
        if v not in (None, ''):
            return float(v)
    except Exception:
        pass
    return next((p for k, _lbl, p in EXTRAS if k == key), 0.0)


def default_extras(category):
    """Add-ons pre-ticked for a facility type, because the work is not optional."""
    return list(DEFAULT_EXTRAS.get(category, []))


def drive_minutes(value=None):
    """Round-trip travel for one visit, in minutes.

    A quote may state its own — this customer is across town — and falls back
    to the setting when it does not.
    """
    if value not in (None, ''):
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            pass
    return _get('comm_drive_minutes') or 0.0


def quote(square_footage, category='office', frequency='weekly', extras=None,
          drive_mins=None):
    """Return a confident, profitable price with a low/standard/premium range.

    The one call every quote in the product goes through. It used to be dead
    code — the browser had its own copy of the arithmetic, twice, and they had
    already drifted apart from each other and from this. Fixing a price here
    changed nothing anybody was quoted.
    """
    # Union rather than "whatever was passed", so a facility type's mandatory
    # scope is priced on every path — the saved account and the API, not just
    # the browser calculator where the box happens to start ticked.
    extras = set(extras or []) | set(default_extras(category))
    sqft = max(0.0, float(square_footage or 0))
    rate = prod_rate(category) or 2000
    hourly = _get('comm_hourly_cost')
    target = _get('comm_target_labor') or 0.40
    min_visit = _get('comm_min_visit')
    mins = drive_minutes(drive_mins)

    hours = sqft / rate if rate else 0.0
    labor = hours * hourly
    onsite = (labor / target) if target else labor
    onsite = onsite * (1 + sum(extra_pct(k) for k, _lbl, _p in EXTRAS if k in extras))
    # The floor applies to the work, not to the journey. See the note at the
    # top: a minimum that swallowed the drive made every small job cost the
    # same however far away it was.
    onsite = max(onsite, min_visit if sqft else 0.0)

    drive_labor = (mins / 60.0) * hourly
    drive_price = (drive_labor / target) if target else drive_labor
    if not sqft:
        drive_price = drive_labor = 0.0     # no job, no journey

    # Rounded as two parts that are then added, rather than added and then
    # rounded. The calculator shows the breakdown next to the total — "$156 for
    # the clean, $31 for the trip" — and a total that is a dollar off its own
    # parts reads as a mistake in the quote, which is the last thing somebody
    # wants to see while a customer is on the phone.
    onsite_r = round(onsite)
    drive_r = round(drive_price)
    standard = onsite_r + drive_r
    price = float(standard)

    vpm = VISITS_PER_MONTH.get(frequency, 4.3)
    monthly = round(standard * vpm)
    return {
        'square_footage': int(sqft),
        'hours': round(hours, 2),
        'labor_cost': round(labor + drive_labor, 2),
        'onsite_price': onsite_r,
        'drive_minutes': round(mins),
        'drive_cost': round(drive_labor, 2),
        'drive_price': drive_r,
        'low': round(price * RANGE_LOW),
        'standard': standard,
        'premium': round(price * RANGE_HIGH),
        'per_visit': standard,          # what we save on the account
        'monthly': monthly,
        'annual': monthly * 12,
        'profit_per_visit': round(standard - labor - drive_labor),
    }


def get_config():
    """JSON-serializable config for the in-browser live calculator."""
    return {
        'hourly': _get('comm_hourly_cost'),
        'target': _get('comm_target_labor') or 0.40,
        'min_visit': _get('comm_min_visit'),
        'drive_minutes': _get('comm_drive_minutes') or 0.0,
        'prod_rates': {c: prod_rate(c) for c in PROD_RATES},
        'visits_per_month': VISITS_PER_MONTH,
        'facility_types': [{'key': k, 'label': l, 'desc': d} for k, l, d in FACILITY_TYPES],
        'extras': [{'key': k, 'label': l, 'pct': extra_pct(k)} for k, l, _p in EXTRAS],
        'default_extras': {c: default_extras(c) for c in PROD_RATES},
        'range_low': RANGE_LOW, 'range_high': RANGE_HIGH,
    }
