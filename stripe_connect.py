"""Stripe Connect helpers — pay contractors via Express connected accounts.

Every function is defensive: returns (ok: bool, data_or_error). Nothing here
moves money except create_transfer(), which is only called from the guarded
admin "Pay" route. Works in whichever mode STRIPE_SECRET_KEY is (test or live).
"""
import os
import stripe
import integrations


def _init():
    key = integrations.stripe_secret_key()
    stripe.api_key = key
    return bool(key)


def is_configured():
    return bool(integrations.stripe_secret_key())


def create_express_account(email, name=''):
    """Create an Express connected account that can receive transfers.
    Returns (True, account_id) or (False, error_message)."""
    if not _init():
        return False, 'Stripe is not configured (missing STRIPE_SECRET_KEY).'
    try:
        acct = stripe.Account.create(
            type='express',
            country='US',
            email=email or None,
            business_type='individual',
            capabilities={'transfers': {'requested': True}},
            business_profile={
                'product_description': 'Independent cleaning contractor paid for completed jobs.',
                'mcc': '7349',  # cleaning & maintenance services
            },
            metadata={'name': name} if name else {},
        )
        return True, acct.id
    except stripe.error.StripeError as e:
        return False, getattr(e, 'user_message', None) or str(e)
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def create_onboarding_link(account_id, refresh_url, return_url):
    """Hosted onboarding link where the contractor enters bank + tax + ID.
    Returns (True, url) or (False, error)."""
    if not _init():
        return False, 'Stripe is not configured.'
    try:
        link = stripe.AccountLink.create(
            account=account_id,
            refresh_url=refresh_url,
            return_url=return_url,
            type='account_onboarding',
        )
        return True, link.url
    except stripe.error.StripeError as e:
        return False, getattr(e, 'user_message', None) or str(e)
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def get_account_status(account_id):
    """Fetch live status. Returns (True, {payouts_enabled, details_submitted,
    disabled_reason}) or (False, error)."""
    if not _init():
        return False, 'Stripe is not configured.'
    try:
        acct = stripe.Account.retrieve(account_id)
        reqs = getattr(acct, 'requirements', None) or {}
        disabled_reason = reqs.get('disabled_reason') if isinstance(reqs, dict) else getattr(reqs, 'disabled_reason', None)
        return True, {
            'payouts_enabled': bool(getattr(acct, 'payouts_enabled', False)),
            'details_submitted': bool(getattr(acct, 'details_submitted', False)),
            'disabled_reason': disabled_reason,
        }
    except stripe.error.StripeError as e:
        return False, getattr(e, 'user_message', None) or str(e)
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def create_transfer(account_id, amount_dollars, description='', idempotency_key=None):
    """Move money from the platform balance to the contractor's connected account.
    amount_dollars is a float; Stripe wants integer cents. Returns (True, transfer_id)
    or (False, error). THIS MOVES REAL MONEY in live mode.

    Pass a stable idempotency_key (e.g. 'payout-job-<booking_id>') so a retried or
    double-submitted request can never create a second transfer — Stripe returns the
    original transfer instead of charging again."""
    if not _init():
        return False, 'Stripe is not configured.'
    try:
        cents = int(round(float(amount_dollars) * 100))
        if cents <= 0:
            return False, 'Amount must be greater than $0.'
        kwargs = {}
        if idempotency_key:
            kwargs['idempotency_key'] = idempotency_key
        tr = stripe.Transfer.create(
            amount=cents,
            currency='usd',
            destination=account_id,
            description=description or 'Contractor payout',
            **kwargs,
        )
        return True, tr.id
    except stripe.error.StripeError as e:
        return False, getattr(e, 'user_message', None) or str(e)
    except Exception as e:  # noqa: BLE001
        return False, str(e)
