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
from datetime import datetime

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

def checkout_session(org, plan, success_url, cancel_url):
    """A Stripe-hosted page for entering card details. Returns its URL."""
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
        control_plane.set_billing(
            engine, slug,
            plan=plan,
            subscription_status=status,
            stripe_customer_id=customer or org.get('stripe_customer_id'),
            stripe_subscription_id=obj.get('id'),
            trial_ends_at=_ts(obj.get('trial_end')),
            current_period_end=_ts(obj.get('current_period_end')))
        return True, f'{slug}: subscription {status} on {plan}'

    if kind == 'invoice.payment_failed':
        # Not a cancellation. Stripe will retry for days, and dropping somebody
        # to free on the first failed attempt would take a working business off
        # its own schedule over a card that expired on a Tuesday.
        control_plane.set_billing(engine, slug, subscription_status='past_due')
        return True, f'{slug}: payment failed, marked past_due'

    if kind in ('invoice.paid', 'invoice.payment_succeeded'):
        control_plane.set_billing(engine, slug, subscription_status='active')
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
