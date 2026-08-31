"""What this business's plan lets it do.

One module decides every plan question in the application. Not because that is
tidy, but because the alternative — a plan check written inline wherever someone
remembered one — is how a paying customer gets locked out of a feature they paid
for, and how a free one quietly runs a fifty-person operation for nothing. There
is one table of limits below and everything reads it.

Two rules the rest of the app depends on:

**Gating blocks new actions, never old data.** A business that drops from Pro to
Solo with forty clients keeps all forty. It cannot add a forty-first. Nothing
disappears, nothing is deleted, and no record they entered stops being readable.
A limit that eats yesterday's work is not a nudge, it is a betrayal, and it is
the thing people write reviews about.

**Locked features are shown, not hidden.** A greyed-out Hiring tab with a padlock
sells the upgrade. A Hiring tab that isn't there sells nothing, because as far as
the owner knows the product cannot do it at all.

## Where the plan actually lives

Today: a row in BusinessSetting, because this deployment is one business.
Later: a column on the organization, once the app is multi-tenant.

Everything routes through `state()` so that change is one function, not a
hundred call sites. Do not read the plan setting anywhere else.
"""
from datetime import datetime, timedelta
from functools import wraps

# Plan order. A feature needing 'pro' is available to 'pro' and 'scale'.
RANK = {'solo': 0, 'pro': 1, 'scale': 2}

DEFAULT_PLAN = 'solo'

# The trial is a full Pro trial, not a crippled one. A company with six cleaners
# cannot evaluate this product inside the Solo limits — they would be testing a
# tool built for somebody else and concluding, correctly, that it does not fit.
TRIAL_DAYS = 14


# ---------------------------------------------------------------------------
# The table. Everything else in this file is machinery around it.
# ---------------------------------------------------------------------------

PLANS = {
    'solo': {
        'label': 'Solo',
        'price': 0,
        'blurb': 'For the owner who is still doing the work.',
        # None means unlimited. A number is a hard ceiling.
        'limits': {
            'field_workers': 2,        # them, plus one helper
            'jobs_per_month': 20,
            'clients': None,           # never capped — this is their business, not ours
            'checklist_templates': 1,
            'office_logins': 1,
            'sms_per_month': 0,        # see note below
        },
        'features': set(),
    },
    'pro': {
        'label': 'Pro',
        'price': 79,
        'blurb': 'For the owner who has stopped cleaning and started managing.',
        'limits': {
            'field_workers': 10,
            'jobs_per_month': None,
            'clients': None,
            'checklist_templates': None,
            'office_logins': None,
            'sms_per_month': 1000,     # fair use; metered past this, not cut off
        },
        'features': {
            'sms', 'crew_pay', 'payroll', 'tax_forms', 'hiring', 'interviews',
            'sops', 'automations', 'recurring', 'reports', 'job_economics',
            'discounts', 'card_payments', 'booking_widget', 'templates',
            'invoices', 'team_logins',
        },
    },
    'scale': {
        'label': 'Scale',
        'price': 249,
        'blurb': 'For multi-crew operations and commercial contracts.',
        'limits': {
            'field_workers': None,
            'jobs_per_month': None,
            'clients': None,
            'checklist_templates': None,
            'office_logins': None,
            'sms_per_month': 5000,
        },
        'features': None,   # None means "everything" — see can()
    },
}

# Why SMS is zero on Solo and not merely small: every text costs real money to
# send, every month, forever, to somebody who has never paid anything. It is the
# only limit here that is about cash rather than product design, and it is the
# one that decides whether a free tier is a funnel or a slow leak. Solo still
# sends email, which costs approximately nothing, so a free business is never
# unable to reach its customers — only unable to do it by text.

# Human-readable names, used in upgrade prompts. A padlock that says
# 'crew_pay' teaches the owner nothing about what they would be buying.
FEATURE_LABELS = {
    'sms': 'Text messaging',
    'crew_pay': 'Per-job crew pay',
    'payroll': 'Payroll',
    'tax_forms': '1099s and W-9s',
    'hiring': 'The hiring funnel',
    'interviews': 'Video interviews',
    'sops': 'SOP library',
    'automations': 'Automated reminders',
    'recurring': 'Recurring jobs',
    'reports': 'Profit & Loss and reporting',
    'job_economics': 'Job economics',
    'discounts': 'Discount codes',
    'card_payments': 'Card payments',
    'booking_widget': 'Booking form on your own website, without our name on it',
    'templates': 'Email and text templates',
    'invoices': 'Invoicing',
    'team_logins': 'Extra office logins',
    'commercial': 'Commercial accounts and quotes',
    'lead_finder': 'Find Leads',
    'multi_brand': 'A second brand',
    'content_studio': 'Content Studio',
    'va_commissions': 'VA commissions',
    'remove_branding': 'Remove our branding',
    'data_export': 'Data export',
}

LIMIT_LABELS = {
    'field_workers': 'active cleaners',
    'jobs_per_month': 'jobs this month',
    'clients': 'clients',
    'checklist_templates': 'checklist templates',
    'office_logins': 'office logins',
    'sms_per_month': 'texts this month',
}


# ---------------------------------------------------------------------------
# Plan state — the one seam that changes when this goes multi-tenant
# ---------------------------------------------------------------------------

def state():
    """This business's plan, as a dict, resolved once per request.

    Returns: plan, effective_plan, on_trial, trial_days_left, grandfathered,
    status. `plan` is what they bought; `effective_plan` is what they may use
    right now, which differs during a trial.

    When this application becomes multi-tenant, this function reads from the
    organization row instead of BusinessSetting and nothing else changes.
    """
    try:
        from flask import g, has_request_context
        if has_request_context() and hasattr(g, '_entitlement_state'):
            return g._entitlement_state
    except Exception:
        g = None

    st = _load_state()

    try:
        from flask import g as _g, has_request_context as _hrc
        if _hrc():
            _g._entitlement_state = st
    except Exception:
        pass
    return st


def _load_state():
    plan = DEFAULT_PLAN
    status = 'active'
    grandfathered = False
    trial_ends = None

    try:
        from models import BusinessSetting
        plan = (BusinessSetting.get('plan') or DEFAULT_PLAN).strip().lower()
        if plan not in PLANS:
            plan = DEFAULT_PLAN
        status = (BusinessSetting.get('plan_status') or 'active').strip().lower()
        grandfathered = (BusinessSetting.get('grandfathered') or '') == '1'
        raw = (BusinessSetting.get('trial_ends_at') or '').strip()
        if raw:
            try:
                trial_ends = datetime.fromisoformat(raw)
            except ValueError:
                trial_ends = None
    except Exception:
        # No database yet, or a broken one. A plan lookup must never be the
        # reason a page fails to render, so fall back to the free plan and let
        # the page decide what it can show.
        pass

    on_trial = bool(trial_ends and datetime.utcnow() < trial_ends and plan == 'solo')
    days_left = 0
    if on_trial:
        days_left = max(0, (trial_ends - datetime.utcnow()).days + 1)

    effective = 'pro' if on_trial else plan

    # An unpaid subscription drops to Solo rather than locking the app. They
    # keep reading everything they have; they simply cannot run a business on
    # it until the card is fixed. Deleting access to their own schedule over a
    # declined card would be a worse outcome for them than for us.
    if status in ('past_due', 'canceled', 'cancelled') and not on_trial:
        effective = 'solo'

    return {
        'plan': plan,
        'effective_plan': effective,
        'on_trial': on_trial,
        'trial_days_left': days_left,
        'trial_ends_at': trial_ends,
        'grandfathered': grandfathered,
        'status': status,
        'label': PLANS[effective]['label'],
    }


def effective_plan():
    return state()['effective_plan']


def set_plan(plan, status='active'):
    """Change the plan. Called by the Stripe webhook, and by you in support."""
    if plan not in PLANS:
        raise ValueError(f'unknown plan: {plan}')
    from models import BusinessSetting
    from extensions import db
    BusinessSetting.set('plan', plan)
    BusinessSetting.set('plan_status', status)
    db.session.commit()
    _clear_cache()


def start_trial(days=TRIAL_DAYS):
    """Begin a Pro trial. Idempotent — calling it twice does not extend one."""
    from models import BusinessSetting
    from extensions import db
    if (BusinessSetting.get('trial_ends_at') or '').strip():
        return False
    BusinessSetting.set('trial_ends_at', (datetime.utcnow() + timedelta(days=days)).isoformat())
    db.session.commit()
    _clear_cache()
    return True


def _clear_cache():
    try:
        from flask import g, has_request_context
        if has_request_context() and hasattr(g, '_entitlement_state'):
            del g._entitlement_state
    except Exception:
        pass


# ---------------------------------------------------------------------------
# The questions the rest of the app asks
# ---------------------------------------------------------------------------

def can(feature):
    """May this business use this feature right now?"""
    plan = effective_plan()
    if PLANS[plan]['features'] is None:      # top plan: everything
        return True
    # A feature is available on a plan if that plan or any lower one grants it.
    for name, cfg in PLANS.items():
        if RANK[name] > RANK[plan]:
            continue
        if cfg['features'] is None or feature in cfg['features']:
            return True
    return False


def plan_for_feature(feature):
    """The cheapest plan that includes this feature — what to offer them."""
    for name in sorted(PLANS, key=lambda n: RANK[n]):
        cfg = PLANS[name]
        if cfg['features'] is None or feature in cfg['features']:
            return name
    return 'scale'


def limit(name):
    """The ceiling for this plan, or None for unlimited."""
    return PLANS[effective_plan()]['limits'].get(name)


def usage(name):
    """How much of it is already in use. Cheap aggregate queries only —
    this runs on the sidebar of every admin page."""
    try:
        return _USAGE[name]()
    except Exception:
        # A failed count must not block a legitimate action. Reporting zero
        # errs towards letting the owner work, which is the right way to be
        # wrong about somebody else's business.
        return 0


def remaining(name):
    """How many more they may add. None when unlimited."""
    cap = limit(name)
    if cap is None:
        return None
    return max(0, cap - usage(name))


def at_limit(name):
    cap = limit(name)
    return cap is not None and usage(name) >= cap


def _month_start():
    now = datetime.utcnow()
    return datetime(now.year, now.month, 1)


def _count_field_workers():
    from models import Staff
    return Staff.query.filter_by(is_active=True).count()


def _count_jobs_this_month():
    from models import Booking
    return Booking.query.filter(Booking.created_at >= _month_start()).count()


def _count_clients():
    from models import Client
    return Client.query.count()


def _count_checklist_templates():
    from models import ChecklistTemplate
    return ChecklistTemplate.query.count()


def _count_office_logins():
    from models import User
    return User.query.filter_by(active=True).count()


def _count_sms_this_month():
    from models import OutboundLog
    return OutboundLog.query.filter(
        OutboundLog.channel == 'sms',
        OutboundLog.status == 'sent',
        OutboundLog.created_at >= _month_start(),
    ).count()


_USAGE = {
    'field_workers': _count_field_workers,
    'jobs_per_month': _count_jobs_this_month,
    'clients': _count_clients,
    'checklist_templates': _count_checklist_templates,
    'office_logins': _count_office_logins,
    'sms_per_month': _count_sms_this_month,
}


# ---------------------------------------------------------------------------
# Enforcing it
# ---------------------------------------------------------------------------

def requires_plan(feature):
    """Guard a whole page behind a feature.

    Server-side, because a hidden menu item is decoration and not a lock: the
    URL is still there, and the person most likely to type it is the one who
    just cancelled.

        @money_bp.route('/payroll')
        @owner_required
        @requires_plan('payroll')
        def payroll(): ...
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if can(feature):
                return f(*args, **kwargs)
            from flask import redirect, url_for, request
            record_denial(feature, path=request.path)
            try:
                return redirect(url_for('billing.upgrade', feature=feature))
            except Exception:
                # Billing isn't mounted yet. Fail towards the dashboard with a
                # message rather than a 500 on a page they cannot use anyway.
                from flask import flash
                flash(_upgrade_message(feature), 'error')
                return redirect(url_for('admin.dashboard'))
        return decorated
    return decorator


def check_limit(name):
    """For POST handlers that create something. Returns (ok, message).

        ok, msg = entitlements.check_limit('field_workers')
        if not ok:
            flash(msg, 'error')
            return redirect(...)
    """
    if not at_limit(name):
        return True, None
    record_denial(f'limit:{name}')
    cap = limit(name)
    what = LIMIT_LABELS.get(name, name.replace('_', ' '))
    upgrade = _next_plan()
    if not upgrade:
        return False, f"You've reached the maximum of {cap} {what}."
    return False, (
        f"You're at {cap} {what} — the limit on the {PLANS[effective_plan()]['label']} plan. "
        f"{PLANS[upgrade]['label']} removes it for ${PLANS[upgrade]['price']}/month."
    )


def _next_plan():
    order = sorted(PLANS, key=lambda n: RANK[n])
    cur = effective_plan()
    i = order.index(cur)
    return order[i + 1] if i + 1 < len(order) else None


def _upgrade_message(feature):
    label = FEATURE_LABELS.get(feature, feature.replace('_', ' ').capitalize())
    need = plan_for_feature(feature)
    return (f"{label} is part of the {PLANS[need]['label']} plan "
            f"(${PLANS[need]['price']}/month).")


def record_denial(feature, path=None):
    """Write down that somebody wanted something their plan does not include.

    This is the most valuable table in the application and it costs one insert.
    Which wall a business hits in the week before they upgrade tells you what
    they are actually buying. Which wall they hit in the week before they leave
    tells you what you priced wrong. Neither is knowable afterwards, and almost
    nobody collects it, so it is worth writing the row even on the days nobody
    reads it.
    """
    try:
        from models import EntitlementDenial
        from extensions import db
        db.session.add(EntitlementDenial(
            feature=feature,
            plan=effective_plan(),
            path=(path or '')[:200],
        ))
        db.session.commit()
    except Exception:
        # Never let analytics break a request. The owner is mid-task and does
        # not care that we failed to record our own paywall.
        try:
            from extensions import db
            db.session.rollback()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# For templates
# ---------------------------------------------------------------------------

def template_context():
    """Injected into every admin page by the context processor in app.py."""
    st = state()
    return {
        'PLAN': st,
        'plan_can': can,
        'plan_limit': limit,
        'plan_usage': usage,
        'plan_remaining': remaining,
        'plan_at_limit': at_limit,
        'PLANS': PLANS,
        'FEATURE_LABELS': FEATURE_LABELS,
    }
