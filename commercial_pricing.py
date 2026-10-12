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
    # A dining room goes quickly; the kitchen behind it does not -- grease on
    # every surface, floors that need degreasing rather than mopping, and a
    # health inspector who will look. Priced as the slower of the two.
    'restaurant': 1200,
    # Every machine and mat wiped down, plus locker rooms and showers: closer
    # to a clinic than an office for the time it takes.
    'gym': 1500,
    # Big open rooms used a few times a week -- the sanctuary goes quickly;
    # restrooms, nursery and fellowship-hall kitchen are where the time is.
    'church': 2500,
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
    ('restaurant', '🍽️ Restaurant', 'Dining rooms, kitchens, restrooms'),
    ('gym', '🏋️ Gym', 'Fitness studios, locker rooms, equipment'),
    ('church', '⛪ Church', 'Sanctuaries, halls, classrooms'),
    ('apartment', '🏘️ Apartments', 'Complexes, common areas, turnovers'),
    ('property_manager', '🏢 Property Mgmt', 'Managed buildings'),
    ('other', '📦 Other', 'Retail, schools, warehouses, etc.'),
]

# Optional scope add-ons (key, label, % added to the price). The percentages
# are starting defaults — owners who have priced their own market can change
# each one in Settings → Commercial pricing, same as the rates above.
EXTRAS = [
    ('restrooms', '🚻 Restroom deep-clean', 0.10),
    ('breakroom', '🍽️ Break room / kitchen', 0.08),
    ('trash', '🗑️ Trash & liner service', 0.05),
    ('disinfection', '🧴 Disinfect high-touch', 0.08),
    # A restaurant's kitchen is two jobs a dining room is not: a floor that has
    # to be degreased, not just mopped, and the line -- fryers, grills,
    # cooktops, ovens -- scraped and degreased.
    ('floor_degrease', '🧽 Kitchen floor degreasing', 0.10),
    ('kitchen_equipment', '🍳 Kitchen equipment — fryers, grills, cooktops', 0.15),
    # Not more rooms but more time in each: baseboards, vents, behind and
    # under things, built-up grime. Ticked on a recurring contract it prices
    # every visit as deep; a one-off deep clean before the regular schedule
    # is its own line in the scope.
    ('deep', '✨ Deep clean', 0.50),
    ('post_construction', '🏗️ Post-construction cleanup', 1.00),
]

# Of the add-ons above, the ones that are the same rooms done harder rather
# than more rooms. These go on after the minimum-visit floor, not before it:
# on a small job the floor is most of the price, and a deep clean folded
# underneath it came out at exactly the regular price -- a 1,400 sq ft
# restaurant quoted the same for a deep clean as for a weekly mop.
INTENSITY_EXTRAS = frozenset({'deep', 'post_construction'})

# Scope that isn't really optional for some facility types. A medical clean
# carries the disinfection protocol whether or not anyone remembers to tick the
# box, so the price has to carry it too — leaving it unticked was quoting exam
# rooms at office rates. Pre-ticked in the calculator, still removable.
DEFAULT_EXTRAS = {
    'medical_office': ['disinfection'],
}

# Scope that usually comes with a facility type but is the customer's to turn
# down: pre-ticked on the calculator, and priced only while it stays ticked.
# A restaurant's customers use the restrooms all day and its kitchen is most of
# the work -- but plenty have their own kitchen crew and only want the front of
# house done, and a box that can be unticked must change the price when it is.
SUGGESTED_EXTRAS = {
    'restaurant': ['restrooms', 'breakroom', 'floor_degrease', 'kitchen_equipment'],
    # Locker rooms are restrooms with showers, and equipment is high-touch.
    'gym': ['restrooms', 'disinfection'],
    'church': ['restrooms'],
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
          drive_mins=None, hours=None):
    """Return a confident, profitable price with a low/standard/premium range.

    The one call every quote in the product goes through. It used to be dead
    code — the browser had its own copy of the arithmetic, twice, and they had
    already drifted apart from each other and from this. Fixing a price here
    changed nothing anybody was quoted.

    `hours` is the time somebody judged the job takes, on a walkthrough. When
    given it replaces square footage over the production rate, which assumes a
    full clean of every square foot: a restaurant that only wants its floors
    done weekly is a fraction of that, and pricing it as a full clean loses
    the job. Everything after -- labour share, add-ons, the minimum visit, the
    drive -- is priced exactly as before.
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

    try:
        judged = float(hours) if hours not in (None, '') else 0.0
    except (TypeError, ValueError):
        judged = 0.0
    if judged > 0:
        hours, has_job = judged, True
    else:
        hours, has_job = (sqft / rate if rate else 0.0), bool(sqft)
    labor = hours * hourly
    onsite = (labor / target) if target else labor
    onsite = onsite * (1 + sum(extra_pct(k) for k, _lbl, _p in EXTRAS
                               if k in extras and k not in INTENSITY_EXTRAS))
    # The floor applies to the work, not to the journey. See the note at the
    # top: a minimum that swallowed the drive made every small job cost the
    # same however far away it was.
    at_minimum = bool(has_job and min_visit and onsite < min_visit)
    onsite = max(onsite, min_visit if has_job else 0.0)
    # A deep clean is a harder version of whatever that came to, minimum
    # included -- see INTENSITY_EXTRAS.
    onsite = onsite * (1 + sum(extra_pct(k) for k in INTENSITY_EXTRAS if k in extras))

    drive_labor = (mins / 60.0) * hourly
    drive_price = (drive_labor / target) if target else drive_labor
    if not has_job:
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
        # The minimum visit set the price: add-ons below it don't move it.
        'at_minimum': at_minimum,
        'min_visit': min_visit,
    }


# ── Priced by work area ─────────────────────────────────────────────────────
#
# A commercial quote broken into the areas of the building and the work done
# in each, every line priced the way quote() prices a whole building: time on
# site (quantity over how fast that work goes) at the loaded hourly cost,
# grossed up to the target labour share, plus what the chemicals and the
# machine cost per unit. Floors are the reason: stone or concrete tile on an
# auto-scrubber, ceramic tile scrubbed and grouted and hardwood dust-mopped
# and never wetted each take their own equipment, chemical and time.
#
# Defaults only, like everything here: every rate and supplies figure is the
# owner's to change in Settings -> Commercial pricing.

AREA_PRESETS = [
    'Service floor / dining room', 'Entry & lobby', 'Kitchen', 'Restrooms',
    'Back of house & storage', 'Offices', 'Locker rooms', 'Sanctuary & halls',
    'Exterior & entrance', 'Other',
]

# key, what is done (the line the customer reads), unit, units one cleaner
# does in an hour, supplies + equipment per unit ($), group for the picker.
WORK_ITEMS = [
    ('floor_hardwood', 'Hardwood floor — dust mop & damp mop, wood-safe cleaner', 'sq ft', 1800, 0.004, 'Floors'),
    ('floor_ceramic', 'Ceramic tile floor — scrub, mop & grout detail', 'sq ft', 1200, 0.006, 'Floors'),
    ('floor_stone', 'Stone / concrete tile — auto-scrubber, neutral cleaner', 'sq ft', 1500, 0.012, 'Floors'),
    ('floor_vinyl', 'Vinyl / VCT floor — sweep & damp mop', 'sq ft', 2000, 0.004, 'Floors'),
    ('floor_carpet', 'Carpet — vacuum', 'sq ft', 2500, 0.002, 'Floors'),
    ('floor_kitchen', 'Kitchen floor (quarry tile) — degrease & scrub', 'sq ft', 800, 0.015, 'Floors'),
    ('floor_strip_wax', 'Floor strip & wax', 'sq ft', 250, 0.08, 'Floors'),
    ('rr_toilet', 'Toilets & urinals — clean & disinfect', 'each', 10, 0.25, 'Restrooms'),
    ('rr_sink', 'Sinks, counters & mirrors', 'each', 15, 0.15, 'Restrooms'),
    ('rr_floor', 'Restroom floor — scrub & disinfect', 'sq ft', 600, 0.01, 'Restrooms'),
    ('rr_restock', 'Restock paper & soap', 'each', 30, 0.0, 'Restrooms'),
    ('k_fryer', 'Fryers — degrease exterior & surrounds', 'each', 2, 3.0, 'Kitchen'),
    ('k_line', 'Cooking line — flat-tops, grills & cooktops', 'linear ft', 20, 0.5, 'Kitchen'),
    ('k_hood', 'Hood & filters — degrease', 'linear ft', 10, 0.75, 'Kitchen'),
    ('k_prep', 'Prep tables & stainless surfaces', 'each', 12, 0.1, 'Kitchen'),
    ('g_dusting', 'Dusting & high-touch disinfection', 'sq ft', 4000, 0.001, 'General'),
    ('g_trash', 'Trash & liners', 'each', 30, 0.2, 'General'),
    ('g_glass', 'Glass doors & interior windows', 'each', 20, 0.05, 'General'),
    ('g_labor', 'Additional cleaning time', 'hours', 1, 0.0, 'General'),
]
WORK_ITEM_KEYS = [k for k, *_ in WORK_ITEMS]
_ITEM = {k: (lbl, unit, rate, sup, grp) for k, lbl, unit, rate, sup, grp in WORK_ITEMS}
# The quote form's frequency names -> the calculator's (VISITS_PER_MONTH keys);
# None for a one-off, which has no monthly figure.
_QUOTE_FREQ = {'daily': 'nightly', 'weekly': 'weekly', 'biweekly': 'biweekly',
               'monthly': 'monthly', 'as_needed': None}


def _settings():
    """Every commercial pricing override, in one query -- for pricing a whole
    quote's lines at once, which otherwise asked the database four times a
    line, on every keystroke in the editor. None if it cannot be read."""
    try:
        from models import PricingSetting
        rows = PricingSetting.query.filter(PricingSetting.key.like('comm_%')).all()
    except Exception:
        return None
    out = {}
    for r in rows:
        try:
            out[r.key] = float(r.value)
        except (TypeError, ValueError):
            pass
    return out


def _val(key, s):
    """An override from a _settings() snapshot, else _get()'s answer."""
    if s is None:
        return _get(key)
    v = s.get(key)
    return v if v is not None else DEFAULTS.get(key)


def item_rate(key, s=None):
    """Units one cleaner does in an hour for a work item. Owner override wins."""
    v = _val(f'comm_item_{key}_rate', s)
    return v if v else (_ITEM[key][2] if key in _ITEM else 0.0)


def item_supplies(key, s=None):
    """Supplies and equipment per unit, in dollars. Owner override wins."""
    v = _val(f'comm_item_{key}_supplies', s)
    return v if v is not None else (_ITEM[key][3] if key in _ITEM else 0.0)


def line_price(key, qty, s=None):
    """(price, hours) for one line: the time it takes priced like any other
    cleaning time, plus its supplies."""
    try:
        qty = max(0.0, float(qty or 0))
    except (TypeError, ValueError):
        qty = 0.0
    rate = item_rate(key, s)
    if key not in _ITEM or not rate:
        return 0.0, 0.0
    hours = qty / rate
    target = _val('comm_target_labor', s) or 0.40
    labour = hours * (_val('comm_hourly_cost', s) or 0)
    return round(labour / target + qty * item_supplies(key, s)), hours


def _num(value, default=0.0):
    try:
        v = float(str(value).replace(',', '').replace('$', '').strip())
    except (TypeError, ValueError):
        return default
    return v if v >= 0 else default


def area_quote(areas, frequency='weekly', drive_mins=None, keep_empty=False, fixed=None):
    """Price a quote laid out as work areas and their lines.

    `areas` is what the quote form sends: [{"name", "lines": [{"item", "qty",
    "label"?, "price"?, "override"?}]}]. A line's price is worked out from its
    item and quantity unless it was typed over (override) or is a custom line
    with only a price. What comes back is the same areas, cleaned and priced,
    with each area's subtotal, then the minimum-visit top-up and the travel as
    lines of their own -- never folded into the work, where nobody can see
    them -- the price a visit, and a month.

    keep_empty keeps lines with nothing in them yet, so the editor's rows and
    the priced rows stay one-to-one while somebody is still typing.

    A line carrying `locked_price` keeps it: the price it was quoted at, on a
    line nobody has changed since (see quotes._lock_saved). `fixed` does the
    same for the minimum visit and the travel -- {"min_visit", "travel"} as
    the quote was written -- so editing a saved quote does not quietly
    re-price it at whatever the rates are today.
    """
    s = _settings()
    fixed = fixed or {}
    out_areas, work, hours, has_work = [], 0.0, 0.0, False
    for a in (areas or [])[:30]:
        if not isinstance(a, dict):
            continue
        name = str(a.get('name') or '').strip()[:80] or 'Work area'
        lines = []
        for ln in (a.get('lines') or [])[:60]:
            if not isinstance(ln, dict):
                continue
            key = ln.get('item') if ln.get('item') in _ITEM else 'custom'
            qty = _num(ln.get('qty'))
            if key == 'custom':
                label = str(ln.get('label') or '').strip()[:140]
                unit = str(ln.get('unit') or '').strip()[:20]
                price = round(_num(ln.get('price')), 2)
                h = 0.0
                override = True
                # Described but free -- a complimentary item is still scope
                # the customer is promised, and the review flags the $0.
                keep = bool(label)
                label = label or 'Other work'
            else:
                label = str(ln.get('label') or '').strip()[:140] or _ITEM[key][0]
                unit = _ITEM[key][1]
                price, h = line_price(key, qty, s)
                override = bool(ln.get('override')) and ln.get('price') not in (None, '')
                if override:
                    price = round(_num(ln.get('price')), 2)
                elif ln.get('locked_price') not in (None, ''):
                    price = round(_num(ln.get('locked_price')), 2)
                keep = False
            if not (qty or price or keep) and not keep_empty:
                continue
            lines.append({'item': key, 'label': label, 'qty': qty, 'unit': unit,
                          'price': price, 'override': override})
            work += price
            hours += h
            # Work is there whatever it rounds to: a few square feet priced at
            # $0 still means a visit, and the visit still costs its minimum.
            has_work = has_work or bool(qty or price)
        out_areas.append({'name': name, 'lines': lines,
                          'subtotal': round(sum(l['price'] for l in lines), 2)})
    work = round(work, 2)
    min_visit = fixed['min_visit'] if fixed.get('min_visit') is not None else (_val('comm_min_visit', s) or 0.0)
    minimum = round(min_visit - work, 2) if has_work and work < min_visit else 0.0
    mins = drive_mins if drive_mins not in (None, '') else _val('comm_drive_minutes', s)
    try:
        mins = max(0.0, float(mins or 0))
    except (TypeError, ValueError):
        mins = 0.0
    target = _val('comm_target_labor', s) or 0.40
    if fixed.get('travel') is not None:
        travel = fixed['travel'] if has_work else 0.0
    else:
        travel = round((mins / 60.0) * (_val('comm_hourly_cost', s) or 0) / target) if has_work else 0.0
    per_visit = round(work + minimum + travel, 2)
    calc = _QUOTE_FREQ.get(frequency, 'weekly')
    monthly = round(per_visit * VISITS_PER_MONTH[calc]) if calc else None
    return {'areas': out_areas, 'work': work, 'minimum': minimum, 'min_visit': min_visit,
            'travel': travel, 'drive_minutes': round(mins), 'per_visit': per_visit,
            'monthly': monthly, 'hours': round(hours, 2)}


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
        # What the calculator ticks for each type: the required scope, then
        # the suggested. Only the required part is forced by quote().
        'default_extras': {c: default_extras(c) + [k for k in SUGGESTED_EXTRAS.get(c, [])
                                                   if k not in default_extras(c)]
                           for c in PROD_RATES},
        'range_low': RANGE_LOW, 'range_high': RANGE_HIGH,
        'work_items': [{'key': k, 'label': lbl, 'unit': unit, 'group': grp,
                        'rate': item_rate(k), 'supplies': item_supplies(k)}
                       for k, lbl, unit, _r, _s, grp in WORK_ITEMS],
        'area_presets': AREA_PRESETS,
    }
