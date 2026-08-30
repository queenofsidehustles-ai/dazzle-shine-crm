import json
from flask import Blueprint, render_template, request, jsonify, make_response
from auth import login_required
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


# What a customer is allowed to see. Everything else `calculate_job` returns
# stays on the server.
_CUSTOMER_FIELDS = (
    'client_price', 'list_price', 'discount_amount', 'discount_pct',
    'hours', 'service_label', 'extras_total', 'extras_list', 'beds', 'baths',
)


@pricing_public_bp.route('/api/calculate', methods=['POST'])
def api_calculate():
    """Price a job for somebody who is thinking about booking one.

    This is public and answers to any origin, because it is what a business's
    own website posts to. Two things follow from that.

    First, it must not return what the cleaner is paid. `calculate_job` works
    out `contractor_earnings` and `contractor_split_pct` in the same call, and
    those were going straight back over an `Access-Control-Allow-Origin: *`
    header -- so anybody who opened the network tab on a booking page could
    read what that company pays its cleaners and the exact split it keeps.
    Whitelisted rather than blacklisted, so a new field added to the pricing
    engine is private until somebody decides otherwise.

    Second, the field names have to be forgiving. The office page sends
    `beds`, a form on somebody's website sends `bedrooms`, and neither should
    be quietly priced as a one-bedroom.
    """
    d = request.get_json(silent=True) or request.form.to_dict() or {}

    def num(*names, default=1):
        """The first of these keys that was sent, as a whole number.

        The pricing engine parses with `int(str(value))`, so handing it a
        float turns 3 into the string "3.0" and raises -- which on a public
        endpoint means a 500 where a price should be."""
        for n in names:
            raw = d.get(n)
            if raw in (None, ''):
                continue
            try:
                return int(float(raw))
            except (TypeError, ValueError):
                continue
        return default

    try:
        result = calculate_job(
            service_type=d.get('service_type', 'standard'),
            beds=num('beds', 'bedrooms'),
            baths=num('baths', 'bathrooms'),
            sqft=d.get('sqft'),
            extras=d.get('extras', ''),
            frequency=d.get('frequency', 'one_time'),
        )
    except Exception:
        # A customer typing something odd into a form on somebody's website
        # must not get an error page where a price belongs. Say so plainly and
        # let the booking page keep the last good figure on screen.
        resp = make_response(jsonify({'ok': False,
                                      'error': 'Could not price that combination.'}), 400)
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp
    safe = {k: result[k] for k in _CUSTOMER_FIELDS if k in result}
    # `total` and `price` are aliases for the one figure anybody actually wants.
    # The admin quote page was already reading `d.price ?? d.total`, both of
    # which were absent, so its price hint had quietly stopped appearing.
    safe['total'] = safe['price'] = result.get('client_price')

    resp = make_response(jsonify(safe))
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
@login_required
def pay_chart():
    """The owner's costing reference: what a job of each size ought to pay.

    This used to be sent to contractors, and it can't be any more. Pay is now set
    per job, and the two numbers legitimately differ — a long clean on a
    discounted recurring plan is worth far less than this table's arithmetic
    says, which is the whole reason per-job pay exists. A cleaner holding this
    chart would read the gap as being underpaid rather than as the table not
    applying, so the chart stays on this side of the login and the offer is the
    only figure anyone outside sees.

    It shows nothing about what the customer is charged: printing pay and price
    side by side only ever invited the comparison."""
    from pricing import get_labor_rate, get_extra_hours
    rows = build_full_matrix()
    # Add-ons are shown as what they add to the cleaner's pay, not to the
    # customer's price, for the same reason.
    labor_rate = get_labor_rate()
    extras = {name: round(get_extra_hours(name) * labor_rate, 2) for name in EXTRAS}
    return render_template('public/pay_chart.html',
        rows=rows,
        extras=extras,
        service_labels=SERVICE_LABELS,
    )

@pricing_public_bp.route('/book')
def book():
    """The business's own booking page, on its own address, in its own colours.

    Every company gets this on every plan, including the free one. It is the
    same app and the same database, so it costs us nothing to run -- and the
    setting-up it requires (services, prices, extras) is exactly the work that
    makes the rest of the software useful. Charging for it would mean free
    accounts never enter their prices and never see what the product does.

    What IS paid is putting it on their own domain and taking our name off the
    bottom, which is `booking_widget` in the plan table.
    """
    import branding, brands, entitlements
    palette = brands.get_brand('primary')
    accent = brands.normalise_hex(palette.get('accent'), '#2563eb')
    # `?embed=1` is the same page inside somebody's own website: no masthead,
    # no footer, transparent behind it, and it reports its height to the parent
    # so the frame grows instead of scrolling inside itself.
    embed = request.args.get('embed') in ('1', 'true', 'yes')

    # The first time anybody opens this page, remember it. That single fact is
    # what tells the getting-started list the business has actually put the
    # link somewhere, rather than being a step you dismiss by clicking it.
    # One write in the lifetime of an account, not one per visit.
    try:
        from models import BusinessSetting
        from extensions import db as _db
        if not BusinessSetting.get('booking_page_seen'):
            BusinessSetting.set('booking_page_seen', '1')
            _db.session.commit()
    except Exception:
        pass                     # never let bookkeeping stop somebody booking

    return render_template(
        'public/book.html',
        embed=embed,
        biz=branding.biz_name(),
        phone=branding.phone(),
        city_line=branding.city_line(),
        valid_baths=VALID_BATHS,
        extras={name: get_extra_price(name) for name in EXTRAS},
        frequency_labels=FREQUENCY_LABELS,
        service_labels=SERVICE_LABELS,
        deposit=get_deposit(),
        brand_dark=brands.normalise_hex(palette.get('dark'), '#1f2937'),
        brand_accent=accent,
        brand_accent_text=brands.readable_on(accent),
        # Our name comes off the page once they are paying for that.
        show_badge=not entitlements.can('booking_widget'),
    )


@pricing_public_bp.route('/embed.js')
def embed_js():
    """The one line a business pastes into its own website.

    An iframe rather than a script that injects a form. The form posts to the
    same origin it was served from, so there is no cross-origin request to
    whitelist, no CORS header to get wrong, and nothing on the customer's site
    can read what is typed into it. The only thing crossing the boundary is a
    number: how tall the frame needs to be.
    """
    import branding
    js = """(function () {
  var s = document.currentScript;
  var base = %s;
  var box = document.createElement('div');
  var f = document.createElement('iframe');
  f.src = base + '/book?embed=1';
  f.title = 'Book a clean';
  f.loading = 'lazy';
  f.style.cssText = 'width:100%%;border:0;display:block;min-height:620px';
  f.setAttribute('scrolling', 'no');
  box.appendChild(f);
  (s && s.parentNode ? s.parentNode : document.body).insertBefore(box, s);
  window.addEventListener('message', function (e) {
    // Only resize for our own frame, and only for a plausible height. A page
    // is free to receive messages from anywhere; acting on them is the part
    // that has to be careful.
    if (!e.data || e.data.akye !== 'height') return;
    if (e.source !== f.contentWindow) return;
    var h = parseInt(e.data.height, 10);
    if (h > 200 && h < 20000) f.style.height = h + 'px';
  });
})();""" % (json.dumps(branding.crm_base().rstrip('/')),)
    resp = make_response(js)
    resp.headers['Content-Type'] = 'application/javascript; charset=utf-8'
    resp.headers['Cache-Control'] = 'public, max-age=300'
    return resp

