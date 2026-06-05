# ============================================================
# DAZZLE & SHINE — PRICING CONFIGURATION
# Edit numbers here to update prices everywhere.
# No other files need to be touched.
# ============================================================

DEPOSIT_AMOUNT = 50  # $50 non-refundable deposit (goes toward final balance)

# Base price for 1 bedroom / 1 bathroom
# Then add per_extra_bed for each bedroom above 1
# And per_extra_bath for each bathroom above 1
SERVICES = {
    "standard": {
        "label": "Standard House Cleaning",
        "base": 140,
        "per_extra_bed": 35,
        "per_extra_bath": 25,
    },
    "deep": {
        "label": "Deep Cleaning",
        "base": 265,
        "per_extra_bed": 60,
        "per_extra_bath": 35,
    },
    "moveout": {
        "label": "Move-Out / Move-In Cleaning",
        "base": 230,
        "per_extra_bed": 50,
        "per_extra_bath": 35,
    },
    "airbnb": {
        "label": "Airbnb / Vacation Rental Cleaning",
        "base": 150,
        "per_extra_bed": 35,
        "per_extra_bath": 25,
    },
    "apartment": {
        "label": "Apartment & Condo Cleaning",
        "base": 140,
        "per_extra_bed": 30,
        "per_extra_bath": 20,
    },
    "luxury": {
        "label": "Luxury Home Cleaning",
        "base": 235,
        "per_extra_bed": 70,
        "per_extra_bath": 45,
    },
}

# Add-on prices
EXTRAS = {
    "Inside oven":      35,
    "Inside fridge":    30,
    "Laundry":          40,
    "Inside windows":   45,
    "Inside cabinets":  30,
}

# Frequency discounts (percentage off per visit)
FREQUENCY_DISCOUNTS = {
    "one_time":  0,    # No discount
    "monthly":   5,    # 5% off
    "biweekly":  10,   # 10% off
    "weekly":    15,   # 15% off
}

FREQUENCY_LABELS = {
    "one_time":  "One-Time",
    "monthly":   "Monthly (5% off)",
    "biweekly":  "Bi-Weekly (10% off)",
    "weekly":    "Weekly (15% off)",
}


def get_service_price(service_type, field):
    """Get price from DB override if available, otherwise use default."""
    try:
        from models import PricingSetting
        db_val = PricingSetting.get(f"{service_type}_{field}")
        if db_val is not None:
            return float(db_val)
    except Exception:
        pass
    return SERVICES.get(service_type, {}).get(field, 0)


def get_extra_price(extra_name):
    """Get add-on price from DB override if available."""
    try:
        from models import PricingSetting
        key = f"extra_{extra_name.lower().replace(' ', '_')}"
        db_val = PricingSetting.get(key)
        if db_val is not None:
            return float(db_val)
    except Exception:
        pass
    return EXTRAS.get(extra_name, 0)


def get_deposit():
    try:
        from models import PricingSetting
        val = PricingSetting.get('deposit_amount')
        if val is not None:
            return float(val)
    except Exception:
        pass
    return DEPOSIT_AMOUNT


def calculate_price(service_type, bedrooms, bathrooms, extras=None, frequency="one_time"):
    """Calculate total job price based on service, home size, extras, and frequency."""
    if service_type not in SERVICES:
        return 0

    try:
        beds = int(str(bedrooms).replace("+", "").replace("Studio", "1"))
        baths = float(str(bathrooms).replace("+", ""))
    except (ValueError, TypeError):
        beds, baths = 1, 1

    extra_beds = max(0, beds - 1)
    extra_baths = max(0, baths - 1)

    total = get_service_price(service_type, 'base')
    total += extra_beds * get_service_price(service_type, 'per_extra_bed')
    total += extra_baths * get_service_price(service_type, 'per_extra_bath')

    if extras:
        for extra in [e.strip() for e in extras.split(",") if e.strip()]:
            total += get_extra_price(extra)

    discount = FREQUENCY_DISCOUNTS.get(frequency, 0)
    if discount:
        total = total * (1 - discount / 100)

    return round(total, 2)
