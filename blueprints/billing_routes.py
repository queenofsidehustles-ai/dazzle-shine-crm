"""The pages a company sees about money, and the one Stripe talks to.

Four routes, and only one of them can change what anybody is entitled to.

    /upgrade              where a padlock sends you
    /billing              the plan, the trial, the card
    /billing/checkout     hands off to Stripe's own payment page
    /billing/return       a friendly "setting you up" page, and nothing more

    /api/stripe/webhook   the only thing that changes a plan

The last two are the point. Stripe sends the customer back to a success URL
after checkout, and that URL is a link like any other -- it can be opened,
shared, bookmarked or typed by anybody. If arriving there upgraded the account,
the plan could be upgraded by visiting a page. So it says thank you and nothing
else, and the entitlement changes when Stripe tells us, over a signed webhook.
"""
import os

from flask import (Blueprint, render_template, request, redirect, url_for,
                   jsonify, abort, flash)

import billing
import branding
import control_plane
import entitlements
from auth import login_required, owner_required

billing_bp = Blueprint('billing', __name__)


def _org_or_404():
    org = billing.current_org()
    if org is None:
        abort(404)
    return org


@billing_bp.route('/upgrade')
@login_required
def upgrade():
    """Where a locked feature sends somebody.

    Named in entitlements.requires_plan, which redirects here. Shows what they
    were reaching for, so the page answers the question they actually have."""
    feature = request.args.get('feature') or ''
    label = entitlements.FEATURE_LABELS.get(
        feature, feature.replace('_', ' ').capitalize() if feature else '')
    need = entitlements.plan_for_feature(feature) if feature else 'pro'
    return render_template('admin/upgrade.html',
                           feature=feature, feature_label=label,
                           need=need, plans=entitlements.PLANS,
                           state=entitlements.state(),
                           can_pay=billing.configured())


@billing_bp.route('/billing')
@owner_required
def billing_home():
    """What they are on, what it costs, and how to change it.

    Owner-only: what the business pays is not a VA's business."""
    org = billing.current_org()
    state = entitlements.state()
    portal_url = None
    if org and org.get('stripe_customer_id') and billing.configured():
        try:
            portal_url = billing.portal_session(
                org, f'{branding.crm_base()}/billing')
        except Exception:
            portal_url = None
    return render_template('admin/billing.html', org=org, state=state,
                           plans=entitlements.PLANS, portal_url=portal_url,
                           can_pay=billing.configured(),
                           usage={k: entitlements.usage(k)
                                  for k in ('field_workers', 'jobs_per_month',
                                            'clients')})


@billing_bp.route('/billing/checkout/<plan>', methods=['POST'])
@owner_required
def checkout(plan):
    if plan not in ('pro', 'scale'):
        abort(404)
    if not billing.configured():
        flash('Card payments are not switched on for this deployment yet.', 'error')
        return redirect(url_for('billing.billing_home'))
    org = _org_or_404()
    base = branding.crm_base()
    try:
        url = billing.checkout_session(
            org, plan,
            success_url=f'{base}/billing/return',
            cancel_url=f'{base}/billing')
    except Exception as e:
        import errors
        errors.capture(e, path='/billing/checkout', method='POST')
        flash('Could not open the payment page. Nothing has been charged.', 'error')
        return redirect(url_for('billing.billing_home'))
    return redirect(url, code=303)


@billing_bp.route('/billing/return')
@owner_required
def checkout_return():
    """Deliberately does nothing but say thank you.

    Reaching this page is not proof of anything -- it is a URL. The plan changes
    when Stripe's signed webhook says it changed, which is usually within a
    second or two, occasionally longer. So this page tells the truth: the
    payment went through, and the account is being updated."""
    return render_template('admin/billing_return.html',
                           state=entitlements.state())


@billing_bp.route('/api/stripe/webhook', methods=['POST'])
def stripe_webhook():
    """The only route that changes what a company is entitled to.

    Everything here happens after the signature is verified. An unverified
    payload is a stranger claiming somebody paid."""
    secret = billing.webhook_secret()
    if not secret or not billing.configured():
        return jsonify({'ok': False, 'error': 'billing not configured'}), 503

    import stripe
    stripe.api_key = billing.stripe_key()
    try:
        event = stripe.Webhook.construct_event(
            request.data, request.headers.get('Stripe-Signature'), secret)
    except Exception:
        # Do not say why. A caller learning the difference between a bad
        # signature and a malformed body learns something worth knowing.
        return jsonify({'ok': False}), 400

    try:
        changed, detail = billing.apply_event(event)
    except Exception as e:
        import errors
        errors.capture(e, path='/api/stripe/webhook', method='POST')
        # 500 so Stripe retries. The handlers are idempotent, so a retry is
        # safe, and losing a payment event is worse than processing it twice.
        return jsonify({'ok': False}), 500

    if not changed:
        # Acknowledged, not applied -- an event we do not act on, or one for a
        # company we do not know. Recorded so it is visible, and 200 so Stripe
        # stops retrying something that will never succeed.
        try:
            from models import ErrorLog
            ErrorLog.record(kind='stripe', message=detail[:400],
                            path='/api/stripe/webhook', method='POST')
        except Exception:
            pass
    return jsonify({'ok': True, 'detail': detail}), 200
