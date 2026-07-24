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
CONTRACTOR_SPLIT_PCT = 50   # percent
LEAD_FEE_DEFAULT     = 25   # dollars — ad cost added to customer price, not shared with contractor
SQFT_SURCHARGE_RATE  = 15   # dollars per 200 sqft over standard


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


def get_contractor_split():
    return _db_get('contractor_split', CONTRACTOR_SPLIT_PCT)


def get_lead_fee():
    """Advertising/lead cost added to the customer price but never shared with
    the contractor. Editable via the 'lead_fee' business setting."""
    return _db_get('lead_fee', LEAD_FEE_DEFAULT)


def get_sqft_surcharge_rate():
    return _db_get('sqft_surcharge', SQFT_SURCHARGE_RATE)


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

    # Square footage surcharge
    sqft_surcharge = 0
    if sqft:
        standard_sqft = STANDARD_SQFT.get(beds, 800)
        over = max(0, int(sqft) - standard_sqft)
        sqft_surcharge = (over // 200) * get_sqft_surcharge_rate()

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

    # Hours
    std_hours = get_std_hours(beds, baths)
    hours = round(std_hours * multiplier, 2)

    # Contractor earnings — 50/50 straight, no minimum
    split = get_contractor_split() / 100
    contractor_earnings = round(client_price * split, 2)
    hourly_rate = round(contractor_earnings / hours, 2) if hours > 0 else 0

    return {
        'client_price':         client_price,
        'contractor_earnings':  contractor_earnings,
        'hours':                hours,
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
