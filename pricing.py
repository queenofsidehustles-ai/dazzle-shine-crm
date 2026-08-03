# ============================================================
# DAZZLE & SHINE — PRICING ENGINE
# Fixed price matrix by (beds, baths). Deep = 1.6x, Move-Out = 1.9x.
# Update prices in the admin dashboard — no code changes needed.
# ============================================================

# Valid bed/bath combinations and their standard prices
PRICE_MATRIX_DEFAULTS = {
    (1, 1): 170,
    (1, 2): 190,
    (2, 1): 200,
    (2, 2): 225,
    (3, 2): 260,
    (3, 3): 295,
    (4, 2): 320,
    (4, 3): 360,
    (5, 3): 410,
    (5, 4): 455,
}

# Estimated hours for standard cleaning
HOURS_MATRIX_DEFAULTS = {
    (1, 1): 1.5,
    (1, 2): 2.0,
    (2, 1): 2.0,
    (2, 2): 2.5,
    (3, 2): 3.0,
    (3, 3): 3.5,
    (4, 2): 4.0,
    (4, 3): 4.5,
    (5, 3): 5.5,
    (5, 4): 6.5,
}

# Valid bathroom options per bedroom count
VALID_BATHS = {1: [1, 2], 2: [1, 2], 3: [2, 3], 4: [2, 3], 5: [3, 4]}

# Standard square footage by bedroom count (for sqft surcharge)
STANDARD_SQFT = {1: 800, 2: 1200, 3: 1800, 4: 2400, 5: 3200}

# Service multipliers vs standard (also stored in DB)
SERVICE_MULTIPLIERS_DEFAULTS = {
    'standard': 1.0,
    'deep':     1.6,
    'moveout':  1.9,
}

SERVICE_LABELS = {
    'standard': 'Standard Cleaning',
    'deep':     'Deep Cleaning',
    'moveout':  'Move-In / Move-Out',
}

# Add-on prices
EXTRAS = {
    'Inside oven':     35,
    'Inside fridge':   30,
    'Laundry':         40,
    'Inside windows':  45,
    'Inside cabinets': 30,
}

# How long each add-on actually takes, in person-hours. These add to the job's
# estimated hours, which is what the cleaner is paid on — without them an add-on
# would raise the customer's price and pay the cleaner nothing extra for the work.
# Starting points from typical trade task times; editable in Settings → Pricing
# once real jobs have been timed.
EXTRA_HOURS = {
    'Inside oven':     0.5,   # degreaser dwell + scrub racks and door glass
    'Inside fridge':   0.5,   # empty, wash and dry shelves and drawers, replace
    'Laundry':         0.75,  # one load: sort, load, transfer, fold, put away
    'Inside windows':  0.75,  # interior panes and sills, typical 3-bed home
    'Inside cabinets': 1.0,   # empty, wipe interiors, replace contents — slow work
}

FREQUENCY_DISCOUNTS = {
    'one_time': 0,
    'monthly':  5,
    'biweekly': 10,
    'weekly':   15,
}

FREQUENCY_LABELS = {
    'one_time': 'One-Time',
    'monthly':  'Monthly (5% off)',
    'biweekly': 'Bi-Weekly (10% off)',
    'weekly':   'Weekly (15% off)',
}

DEPOSIT_AMOUNT       = 50   # dollars
CONTRACTOR_SPLIT_PCT = 50   # percent — LEGACY, only used by jobs with no estimated hours
LABOR_RATE_DEFAULT   = 43   # dollars per person-hour paid to cleaners (the new model)
LEAD_FEE_DEFAULT     = 25   # dollars — ad cost added to customer price, not shared with contractor
SQFT_SURCHARGE_RATE  = 30   # dollars per 200 sqft over standard
# Time those extra square feet actually take. Derived from this pricing matrix
# itself, which implies ~528 sqft per cleaning hour across every home size — so
# 200 sqft is a shade under 0.4 of an hour. Both numbers are editable in
# Settings → Pricing, and any single job's hours can be typed over on the job.
SQFT_HOURS_PER_200   = 0.4  # person-hours per 200 sqft over standard


# ── DB getters (fall back to defaults above) ──────────────────────────────────

def _db_get(key, default):
    try:
        from models import PricingSetting
        val = PricingSetting.get(key)
        if val is not None:
            return float(val)
    except Exception:
        pass
    return default


def get_std_price(beds, baths):
    return _db_get(f'std_price_{beds}_{baths}',
                   PRICE_MATRIX_DEFAULTS.get((int(beds), int(baths)), 0))


def get_std_hours(beds, baths):
    return _db_get(f'std_hours_{beds}_{baths}',
                   HOURS_MATRIX_DEFAULTS.get((int(beds), int(baths)), 2.0))


def get_multiplier(service_type):
    return _db_get(f'{service_type}_multiplier',
                   SERVICE_MULTIPLIERS_DEFAULTS.get(service_type, 1.0))


def get_extra_price(extra_name):
    key = f"extra_{extra_name.lower().replace(' ', '_')}"
    return _db_get(key, EXTRAS.get(extra_name, 0))


def get_extra_hours(extra_name):
    """Person-hours an add-on adds to the job — and therefore to cleaner pay."""
    key = f"extrahrs_{extra_name.lower().replace(' ', '_')}"
    return _db_get(key, EXTRA_HOURS.get(extra_name, 0))


def get_contractor_split():
    return _db_get('contractor_split', CONTRACTOR_SPLIT_PCT)


def get_labor_rate():
    """Dollars paid per person-hour of work — the same for every cleaner and
    every job type.

    This is what replaces the old 'half the job price' rule. Pay is a function
    of how much work a job contains, not of what the customer happened to be
    charged, so discounting a job no longer quietly cuts the cleaner's pay.
    Editable in Settings → Pricing."""
    return _db_get('labor_rate', LABOR_RATE_DEFAULT)


def get_lead_fee():
    """Advertising/lead cost added to the customer price but never shared with
    the contractor. Editable via the 'lead_fee' business setting."""
    return _db_get('lead_fee', LEAD_FEE_DEFAULT)


def get_sqft_surcharge_rate():
    return _db_get('sqft_surcharge', SQFT_SURCHARGE_RATE)


def get_sqft_hours_rate():
    """Person-hours added per 200 sqft over standard — what the cleaner is paid
    for the extra ground to cover."""
    return _db_get('sqft_hours', SQFT_HOURS_PER_200)


def get_deposit():
    return _db_get('deposit_amount', DEPOSIT_AMOUNT)


# ── Core calculation ───────────────────────────────────────────────────────────

def calculate_job(service_type, beds, baths, sqft=None, extras=None, frequency='one_time'):
    """
    Returns a dict with all four key numbers:
      client_price, contractor_earnings, hours, hourly_rate
    Plus breakdown fields for display.
    """
    beds = min(int(str(beds).replace('+', '') or 1), 5)
    baths = int(str(baths).replace('+', '') or 1)

    std_price  = get_std_price(beds, baths)
    multiplier = get_multiplier(service_type)
    base_price = round(std_price * multiplier, 2)

    # Square footage surcharge — extra ground costs the customer more AND takes
    # the cleaner longer, so it has to move both numbers together.
    sqft_surcharge = 0
    sqft_increments = 0
    if sqft:
        standard_sqft = STANDARD_SQFT.get(beds, 800)
        over = max(0, int(sqft) - standard_sqft)
        sqft_increments = over // 200
        sqft_surcharge = sqft_increments * get_sqft_surcharge_rate()

    # Add-ons
    extras_total = 0
    extra_list = []
    if extras:
        if isinstance(extras, str):
            extra_list = [e.strip() for e in extras.split(',') if e.strip()]
        else:
            extra_list = list(extras)
        for e in extra_list:
            extras_total += get_extra_price(e)

    subtotal = base_price + sqft_surcharge + extras_total

    # Frequency discount
    disc = FREQUENCY_DISCOUNTS.get(frequency, 0)
    if disc:
        subtotal = round(subtotal * (1 - disc / 100), 2)

    client_price = round(subtotal, 2)

    # Hours — the base clean scaled by service type, plus the time each add-on
    # genuinely takes. Add-ons used to raise the price without raising the hours,
    # which under hours-based pay would mean the cleaner did the extra work free.
    std_hours = get_std_hours(beds, baths)
    hours = round(std_hours * multiplier, 2)
    extras_hours = round(sum(get_extra_hours(e) for e in extra_list), 2)
    sqft_hours = round(sqft_increments * get_sqft_hours_rate(), 2)
    hours = round(hours + extras_hours + sqft_hours, 2)

    # Contractor earnings — the work in the job at the flat hourly rate.
    # Deliberately not a share of client_price: that's what made a discount cut
    # the cleaner's pay, and made big homes pay worse per hour than small ones.
    labor_rate = get_labor_rate()
    contractor_earnings = round(hours * labor_rate, 2)
    hourly_rate = labor_rate

    return {
        'client_price':         client_price,
        'contractor_earnings':  contractor_earnings,
        'hours':                hours,
        'extras_hours':         extras_hours,
        'sqft_hours':           sqft_hours,
        'hourly_rate':          hourly_rate,
        'base_price':           base_price,
        'sqft_surcharge':       sqft_surcharge,
        'extras_total':         extras_total,
        'extras_list':          extra_list,
        'service_label':        SERVICE_LABELS.get(service_type, service_type),
        'beds':                 beds,
        'baths':                baths,
        'contractor_split_pct': int(get_contractor_split()),
    }


def build_full_matrix():
    """Return all 30 combinations (3 services × 10 combos) sorted by client price."""
    rows = []
    for svc in ('standard', 'deep', 'moveout'):
        for (beds, baths) in sorted(PRICE_MATRIX_DEFAULTS.keys()):
            job = calculate_job(svc, beds, baths)
            job['service_type'] = svc
            rows.append(job)
    rows.sort(key=lambda r: r['client_price'])
    return rows


# ── Backward-compatibility wrappers ───────────────────────────────────────────

SERVICES = {
    'standard': {'label': 'Standard House Cleaning', 'base': 110, 'per_extra_bed': 0, 'per_extra_bath': 0},
    'deep':     {'label': 'Deep Cleaning',            'base': 176, 'per_extra_bed': 0, 'per_extra_bath': 0},
    'moveout':  {'label': 'Move-In / Move-Out',       'base': 209, 'per_extra_bed': 0, 'per_extra_bath': 0},
}


def calculate_price(service_type, bedrooms, bathrooms, extras=None, frequency='one_time', sqft=None):
    extras_str = extras if isinstance(extras, str) else (','.join(extras) if extras else '')
    try:
        sqft_val = int(sqft) if sqft not in (None, '') else None
    except (ValueError, TypeError):
        sqft_val = None
    return calculate_job(service_type, bedrooms, bathrooms, sqft=sqft_val,
                         extras=extras_str, frequency=frequency)['client_price']


def get_service_price(service_type, field):
    if field == 'base':
        return round(get_std_price(1, 1) * get_multiplier(service_type), 2)
    return 0
