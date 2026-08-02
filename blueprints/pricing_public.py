import json
from flask import Blueprint, render_template, request, jsonify, make_response
from pricing import (
    PRICE_MATRIX_DEFAULTS, HOURS_MATRIX_DEFAULTS, SERVICE_LABELS,
    SERVICE_MULTIPLIERS_DEFAULTS, EXTRAS, FREQUENCY_DISCOUNTS,
    FREQUENCY_LABELS, VALID_BATHS, STANDARD_SQFT,
    get_std_price, get_std_hours, get_multiplier, get_extra_price,
    get_contractor_split, get_sqft_surcharge_rate, get_deposit,
    calculate_job, build_full_matrix,
)

pricing_public_bp = Blueprint('pricing_public', __name__)


# ── Public JSON API (used by website calculator) ──────────────────────────────

@pricing_public_bp.route('/api/pricing-data')
def pricing_data():
    """CORS-enabled public endpoint — website fetches this to stay in sync."""
    combos = sorted(PRICE_MATRIX_DEFAULTS.keys())

    price_matrix = {}
    hours_matrix = {}
    for (beds, baths) in combos:
        key = f'{beds}_{baths}'
        price_matrix[key] = get_std_price(beds, baths)
        hours_matrix[key] = get_std_hours(beds, baths)

    extras = {name: get_extra_price(name) for name in EXTRAS}

    multipliers = {svc: get_multiplier(svc) for svc in SERVICE_MULTIPLIERS_DEFAULTS}

    data = {
        'price_matrix':        price_matrix,
        'hours_matrix':        hours_matrix,
        'multipliers':         multipliers,
        'extras':              extras,
        'valid_combos':        [[b, ba] for (b, ba) in combos],
        'valid_baths':         {str(k): v for k, v in VALID_BATHS.items()},
        'standard_sqft':       {str(k): v for k, v in STANDARD_SQFT.items()},
        'frequency_discounts': FREQUENCY_DISCOUNTS,
        'contractor_split':    get_contractor_split(),
        'sqft_surcharge_rate': get_sqft_surcharge_rate(),
        'deposit':             get_deposit(),
        'service_labels':      SERVICE_LABELS,
    }

    resp = make_response(jsonify(data))
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Cache-Control'] = 'public, max-age=300'
    return resp


@pricing_public_bp.route('/api/calculate', methods=['POST'])
def api_calculate():
    """Calculate price+hours+earnings for a given job configuration."""
    d = request.get_json() or {}
    result = calculate_job(
        service_type=d.get('service_type', 'standard'),
        beds=d.get('beds', 1),
        baths=d.get('baths', 1),
        sqft=d.get('sqft'),
        extras=d.get('extras', ''),
        frequency=d.get('frequency', 'one_time'),
    )
    resp = make_response(jsonify(result))
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp


# ── Customer Quote Calculator (View 1) ────────────────────────────────────────

@pricing_public_bp.route('/quote')
def quote_calculator():
    extras = {name: get_extra_price(name) for name in EXTRAS}
    return render_template('public/quote.html',
        valid_baths=VALID_BATHS,
        extras=extras,
        frequency_labels=FREQUENCY_LABELS,
        service_labels=SERVICE_LABELS,
        deposit=get_deposit(),
    )


# ── Contractor Pay Chart (View 2) ─────────────────────────────────────────────

@pricing_public_bp.route('/pay-chart')
def pay_chart():
    from pricing import get_labor_rate
    rows = build_full_matrix()
    extras = {name: get_extra_price(name) for name in EXTRAS}
    split = int(get_contractor_split())
    return render_template('public/pay_chart.html',
        rows=rows,
        extras=extras,
        split=split,
        labor_rate=get_labor_rate(),
        service_labels=SERVICE_LABELS,
    )
