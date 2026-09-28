"""Taking money for the product, and deciding what a company has paid for.

## The one rule everything else follows from

**A browser redirect is not proof of payment.** Stripe sends the customer back
to a success URL when checkout completes, and that URL is just a link — it can
be opened by anybody, bookmarked, shared, or typed. Treating it as "they paid"
means the plan can be upgraded by visiting a page.

So the redirect does one thing: shows a friendly "thanks, setting you up" page.
Every change to what a company is entitled to comes from a webhook whose
signature Stripe signed, and from nowhere else.

## Webhooks arrive more than once

Stripe retries until it gets a 200, and will happily deliver the same event
twice. Every handler here therefore states a fact rather than applying a change:
"this subscription is now active on the Growth plan" is safe to process five
times; "add a month" is not. Nothing here increments anything.

## Losing a card does not lose the business

A failed renewal drops a company to the free plan. It does not lock them out and
it does not delete anything. They keep every customer, every job and every
record; they simply cannot run a business on it until the card is fixed. An
owner locked out of her own schedule over an expired card would rightly never
come back, and we would have taken her data hostage over $99.
"""
import os
from datetime import datetime, timedelta, timezone

import control_plane
import tenancy

# What each plan is called at Stripe. Price IDs live in the environment because
# they differ between test and live mode, and a test price ID in production is a
# subscription that charges nobody.
PRICE_ENV = {
    'pro': 'STRIPE_PRICE_PRO',
    'scale': 'STRIPE_PRICE_SCALE',
}

TRIAL_DAYS = 14


def stripe_key():
    """The product's own Stripe account — not a customer's.

    Deliberately from the environment only. integrations.py reads keys a
    business saved in its own settings, which is how a cleaning company charges
    its cleaning customers. That is a different Stripe account and a different
    flow of money, and confusing the two would mean subscriptions billed to the
    customer's own processor."""
    return (os.environ.get('STRIPE_PLATFORM_SECRET_KEY') or '').strip()


def webhook_secret():
    return (os.environ.get('STRIPE_PLATFORM_WEBHOOK_SECRET') or '').strip()


def configured():
    return bool(stripe_key())


def price_id(plan):
    return (os.environ.get(PRICE_ENV.get(plan, ''), '') or '').strip()


def _engine():
    import provisioning
    return provisioning._engine()


# ---------------------------------------------------------------------------
# What a company is entitled to
# ---------------------------------------------------------------------------

# Statuses where the company keeps what it pays for. Anything else falls back
# to the free plan -- never to a locked door.
PAYING = ('trialing', 'active')


def plan_for(org):
    """The plan a company may actually use right now.

    Reads the control plane, not the company's own database: a business must
    not be able to change what it is paying for by editing its own records."""
    if not org:
        return 'solo'
    if org.get('status') == 'suspended':
        return 'solo'
    status = (org.get('subscription_status') or 'trialing').lower()
    if status not in PAYING:
        return 'solo'
    if status == 'trialing':
        # A trial has to have an end date to be a trial. Without one this
        # returned the paid plan forever -- so a row with a blank status and no
        # dates, which is what a half-written record or a hand-edited row looks
        # like, quietly granted the top plan to somebody who had paid nothing.
        # Missing information must never be read as permission.
        ends = org.get('trial_ends_at')
        if not ends or ends < datetime.utcnow():
            return 'solo'
    return org.get('plan') or 'solo'


# How long somebody gets, and how long they have to start.
TRIAL_DAYS = 14
START_WITHIN_DAYS = 30


def trial_state(org, now=None):
    """Where a company is in its trial, in the words the banner needs.

    Two clocks, because one is not honest:

      * 14 days from the moment they first assign a job to somebody. A
        fortnight measured from signup is a trial a busy company can lose
        without ever having used the product — and then they are owed an
        apology and a manual extension, which is a conversation worth
        designing out.

      * 30 days from signup to make that start. Without it the first clock
        never runs for somebody who signs up and does nothing, and a trial
        that waits indefinitely creates no reason to begin.

    Returns None when there is no trial in play at all — a paying customer, or
    a single-business install with no control plane.
    """
    if not org:
        return None
    status = (org.get('subscription_status') or '').lower()
    if status and status != 'trialing':
        return None                       # paying, cancelled, or past due

    now = now or datetime.utcnow()
    started = org.get('activated_at')
    ends = org.get('trial_ends_at')
    created = org.get('created_at') or now

    if not ends:
        # A trial with no end date is not a trial — see plan_for. Treat it as
        # the start-by window so it is at least bounded.
        ends = created + timedelta(days=START_WITHIN_DAYS)

    days = (ends - now).days
    over = ends <= now

    return {
        'started': bool(started),
        'expired': over,
        'ends_at': ends,
        'days_left': max(0, days),
        # Distinguishing these two matters: one says "you have not begun", the
        # other says "you are running out". They need different sentences.
        'phase': 'over' if over else ('running' if started else 'not_started'),
    }


def mark_activated(engine, slug, when=None):
    """Start the 14 days, now that they have actually used it.

    Called the first time a company has a job with somebody assigned to it.
    Moves the end date to fourteen days from that moment — which may be later
    than the original start-by deadline, and should be: they engaged, so they
    get their fortnight.

    Does nothing if it has already been called.
    """
    org = control_plane.find(engine, slug)
    if not org or org.get('activated_at'):
        return False
    when = when or datetime.utcnow()
    control_plane.set_billing(engine, slug,
                activated_at=when,
                trial_ends_at=when + timedelta(days=TRIAL_DAYS))
    return True


def current_org():
    """The company this request belongs to, or None on the product's own site."""
    from flask import g
    slug = getattr(g, 'tenant_slug', None)
    if not slug:
        return None
    cached = getattr(g, '_org', None)
    if cached is not None:
        return cached
    try:
        org = control_plane.find(_engine(), slug)
    except Exception:
        org = None
    g._org = org
    return org


def install(app):
    """Let entitlements.py read the plan from the control plane.

    entitlements decides what a plan includes; this decides which plan. Keeping
    them apart means the limits can be changed without touching billing, and the
    billing can be changed without touching the limits."""
    import entitlements

    original = entitlements._load_state

    def _load_state():
        org = None
        try:
            org = current_org()
        except Exception:
            pass
        if org is None:
            # No company: the single-business instance, or the product's own
            # site. Behaves exactly as it did before any of this existed.
            return original()
        plan = plan_for(org)
        status = (org.get('subscription_status') or 'trialing').lower()
        trial_ends = org.get('trial_ends_at')
        on_trial = status == 'trialing' and bool(trial_ends) and \
            trial_ends > datetime.utcnow()
        days_left = max(0, (trial_ends - datetime.utcnow()).days + 1) if on_trial else 0
        return {
            'plan': org.get('plan') or 'solo',
            'effective_plan': plan,
            'on_trial': on_trial,
            'trial_days_left': days_left,
            'trial_ends_at': trial_ends,
            'grandfathered': bool(org.get('grandfathered')),
            'status': status,
            'label': entitlements.PLANS[plan]['label'],
        }

    entitlements._load_state = _load_state


# ---------------------------------------------------------------------------
# Starting and managing a subscription
# ---------------------------------------------------------------------------

def _refuse_demo(org):
    """A demo company never subscribes to Akye (demo_guard.py)."""
    import demo_guard
    if (org or {}).get('is_demo') or demo_guard.active():
        raise demo_guard.DemoBlocked('This is a demo company. Plans cannot be '
                                     'changed and no card is ever taken.')


def checkout_session(org, plan, success_url, cancel_url):
    """A Stripe-hosted page for entering card details. Returns its URL."""
    _refuse_demo(org)
    import stripe
    stripe.api_key = stripe_key()
    price = price_id(plan)
    if not price:
        raise RuntimeError(f'No price configured for the {plan} plan '
                           f'({PRICE_ENV.get(plan)} is unset).')

    kwargs = {
        'mode': 'subscription',
        'line_items': [{'price': price, 'quantity': 1}],
        'success_url': success_url,
        'cancel_url': cancel_url,
        # The slug is how the webhook finds its way back to the company. Stripe
        # returns metadata on the events, so this is the thread that ties a
        # payment to a schema.
        'metadata': {'slug': org['slug'], 'plan': plan},
        'subscription_data': {'metadata': {'slug': org['slug'], 'plan': plan}},
        'client_reference_id': org['slug'],
        'allow_promotion_codes': True,
    }
    if org.get('stripe_customer_id'):
        kwargs['customer'] = org['stripe_customer_id']
    else:
        kwargs['customer_email'] = org.get('owner_email')
    return stripe.checkout.Session.create(**kwargs).url


def portal_session(org, return_url):
    """Stripe's own page for changing a card, switching plan, or cancelling.

    Deliberately not rebuilt here. Card details, tax, invoices, proration and
    dunning are Stripe's job, they do it better, and every one of those screens
    is one this product then does not have to keep correct."""
    _refuse_demo(org)
    import stripe
    stripe.api_key = stripe_key()
    if not org.get('stripe_customer_id'):
        return None
    return stripe.billing_portal.Session.create(
        customer=org['stripe_customer_id'], return_url=return_url).url


# ---------------------------------------------------------------------------
# What Stripe tells us
# ---------------------------------------------------------------------------

def apply_event(event):
    """Record what an event says. Idempotent by construction.

    Every branch states a fact -- this subscription is now in this state, on
    this plan, until this date. None of them add, subtract or toggle, so the
    same event delivered five times leaves the same result as delivering it
    once. Stripe retries until it gets a 200, so that is not optional."""
    kind = event.get('type', '')
    obj = (event.get('data') or {}).get('object') or {}
    engine = _engine()

    slug = ((obj.get('metadata') or {}).get('slug')
            or obj.get('client_reference_id'))
    customer = obj.get('customer')

    org = None
    if slug:
        org = control_plane.find(engine, slug)
    if org is None and customer:
        org = control_plane.find_by_customer(engine, customer)
    if org is None:
        # An event for something we do not know about. Acknowledged so Stripe
        # stops retrying; recorded so somebody can look.
        return False, f'no company for {kind} (customer={customer}, slug={slug})'

    slug = org['slug']

    if kind == 'checkout.session.completed':
        control_plane.set_billing(
            engine, slug,
            stripe_customer_id=customer or org.get('stripe_customer_id'),
            stripe_subscription_id=obj.get('subscription')
            or org.get('stripe_subscription_id'))
        return True, f'{slug}: checkout completed'

    if kind in ('customer.subscription.created',
                'customer.subscription.updated',
                'customer.subscription.deleted'):
        status = obj.get('status') or 'canceled'
        if kind.endswith('deleted'):
            status = 'canceled'
        plan = ((obj.get('metadata') or {}).get('plan')
                or _plan_from_items(obj) or org.get('plan') or 'solo')
        fields = dict(
            plan=plan,
            subscription_status=status,
            stripe_customer_id=customer or org.get('stripe_customer_id'),
            stripe_subscription_id=obj.get('id'),
            trial_ends_at=_ts(obj.get('trial_end')),
            current_period_end=_ts(obj.get('current_period_end')))
        # Bookkeeping for the console's sales page. Best-effort: a payload shape
        # it does not expect must never stop the plan and status above from
        # being recorded -- that is what decides whether a company can work.
        try:
            mrr = monthly_cents(obj)
            if mrr is not None:
                fields['mrr_cents'] = mrr
            code = _discount_code(engine, obj)
            if code:
                fields['discount_code'] = code
        except Exception:
            pass
        fields.update(_revenue_dates(org, status))
        control_plane.set_billing(engine, slug, **fields)
        return True, f'{slug}: subscription {status} on {plan}'

    if kind == 'invoice.payment_failed':
        # Not a cancellation. Stripe will retry for days, and dropping somebody
        # to free on the first failed attempt would take a working business off
        # its own schedule over a card that expired on a Tuesday.
        control_plane.set_billing(engine, slug, subscription_status='past_due')
        return True, f'{slug}: payment failed, marked past_due'

    if kind in ('invoice.paid', 'invoice.payment_succeeded'):
        control_plane.set_billing(engine, slug, subscription_status='active',
                                  **_revenue_dates(org, 'active'))
        return True, f'{slug}: payment received'

    return False, f'{slug}: ignored {kind}'


def _plan_from_items(subscription):
    """Work out the plan from the price on the subscription, when metadata is
    missing -- which it is on anything created in the Stripe dashboard."""
    try:
        items = ((subscription.get('items') or {}).get('data') or [])
        prices = {price_id(p): p for p in PRICE_ENV if price_id(p)}
        for item in items:
            pid = (item.get('price') or {}).get('id')
            if pid in prices:
                return prices[pid]
    except Exception:
        pass
    return None


def _ts(value):
    return datetime.utcfromtimestamp(value) if value else None


# ---------------------------------------------------------------------------
# Revenue, as the console counts it
# ---------------------------------------------------------------------------

# Months per billing interval, for turning any price into a monthly figure.
_MONTHS = {'month': 1, 'year': 12, 'week': 12 / 52, 'day': 12 / 365}


def monthly_cents(subscription, now=None):
    """What this subscription brings in per month, in cents, after discounts.

    From the subscription Stripe sent, not from the plan's list price: a
    yearly plan, a second seat or a discount code all make those differ, and
    the sales page is only worth reading if it adds up to what the bank sees.

    A one-off ("once") discount is left out -- it comes off one invoice and
    is not recurring revenue lost. Returns None when the subscription carries
    no prices at all, so the caller keeps what it knew rather than writing 0.
    """
    items = ((subscription.get('items') or {}).get('data') or [])
    total, priced = 0.0, False
    for item in items:
        price = item.get('price') or item.get('plan') or {}
        amount = price.get('unit_amount', price.get('amount'))
        if amount is None:
            continue
        priced = True
        recurring = price.get('recurring') or {}
        interval = recurring.get('interval') or price.get('interval') or 'month'
        count = recurring.get('interval_count') or price.get('interval_count') or 1
        total += amount * (item.get('quantity') or 1) / (_MONTHS.get(interval, 1) * count)
    if not priced:
        return None
    coupon = _recurring_coupon(subscription, now)
    if coupon:
        if coupon.get('percent_off'):
            total *= 1 - float(coupon['percent_off']) / 100
        elif coupon.get('amount_off'):
            total = max(0.0, total - coupon['amount_off'])
    return int(round(total))


def _recurring_coupon(subscription, now=None):
    """The coupon still taking money off every month, if there is one."""
    discount = subscription.get('discount')
    if not isinstance(discount, dict):
        return None
    coupon = discount.get('coupon') or {}
    duration = coupon.get('duration')
    if duration == 'forever':
        return coupon
    if duration == 'repeating':
        end = discount.get('end')
        now = now or datetime.utcnow()
        if end is None or datetime.utcfromtimestamp(end) > now:
            return coupon
    return None


def _discount_code(engine, subscription):
    """The code a customer typed, as a person would recognise it."""
    discount = subscription.get('discount')
    if not isinstance(discount, dict):
        return None
    promo = discount.get('promotion_code')
    promo_id = promo.get('id') if isinstance(promo, dict) else promo
    if promo_id:
        row = control_plane.find_promo_code(engine, stripe_promotion_id=promo_id)
        if row:
            return row['code']
    coupon = discount.get('coupon') or {}
    # Made in the Stripe dashboard rather than the console: its name is the
    # best label there is, and its id the fallback.
    return (coupon.get('name') or coupon.get('id') or promo_id or '')[:64] or None


def _revenue_dates(org, status):
    """When they first paid, and when they left. First-write, so replays are safe."""
    now = datetime.utcnow()
    out = {}
    if status == 'active':
        if not org.get('paid_since'):
            out['paid_since'] = now
        if org.get('canceled_at'):
            out['canceled_at'] = None          # came back
    elif status == 'canceled' and not org.get('canceled_at'):
        out['canceled_at'] = now
    return out


# ---------------------------------------------------------------------------
# Discount codes for Akye's own plans
# ---------------------------------------------------------------------------

DURATIONS = ('once', 'repeating', 'forever')


def create_promo_code(code, *, percent_off=None, amount_off_cents=None,
                      duration='once', duration_months=None,
                      max_redemptions=None, expires_at=None, note=None):
    """Make the coupon and the code a customer types, in Stripe. Returns ids.

    Stripe holds the discount; checkout already accepts codes
    (allow_promotion_codes), so a code made here works the moment this
    returns. Raises on anything Stripe refuses, with Stripe's own message.
    """
    import stripe
    key = stripe_key()
    if not key:
        raise RuntimeError('Stripe is not set up on this deployment, so there is '
                           'nowhere to create the code.')
    stripe.api_key = key
    coupon_args = {'duration': duration, 'name': code,
                   'metadata': {'source': 'akye-console'}}
    if percent_off:
        coupon_args['percent_off'] = percent_off
    else:
        coupon_args['amount_off'] = amount_off_cents
        coupon_args['currency'] = 'usd'
    if duration == 'repeating':
        coupon_args['duration_in_months'] = duration_months
    coupon = stripe.Coupon.create(**coupon_args)
    promo_args = {'coupon': coupon['id'], 'code': code,
                  'metadata': {'source': 'akye-console', 'note': (note or '')[:300]}}
    if max_redemptions:
        promo_args['max_redemptions'] = max_redemptions
    if expires_at:
        promo_args['expires_at'] = int(expires_at.replace(tzinfo=timezone.utc).timestamp())
    try:
        promo = stripe.PromotionCode.create(**promo_args)
    except Exception:
        # Do not leave a coupon behind that no code points at.
        try:
            stripe.Coupon.delete(coupon['id'])
        except Exception:
            pass
        raise
    return coupon['id'], promo['id']


def set_promo_code_active(stripe_promotion_id, active):
    import stripe
    key = stripe_key()
    if not key:
        raise RuntimeError('Stripe is not set up on this deployment.')
    stripe.api_key = key
    stripe.PromotionCode.modify(stripe_promotion_id, active=bool(active))


def promo_redemptions():
    """{promotion id: times redeemed}, straight from Stripe. {} if unavailable."""
    key = stripe_key()
    if not key:
        return {}
    try:
        import stripe
        stripe.api_key = key
        codes = stripe.PromotionCode.list(limit=100)
        return {p['id']: p.get('times_redeemed') or 0 for p in codes.auto_paging_iter()}
    except Exception:
        return {}
