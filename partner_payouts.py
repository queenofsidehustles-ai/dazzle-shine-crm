"""Paying affiliate partners through Stripe Connect, from Akye's own account.

## Which Stripe account, and why it matters

`stripe_connect.py` pays a cleaning company's cleaners, and it does so from
that company's own Stripe account (`integrations.stripe_secret_key()`). Akye
paying a partner is a different flow of money from a different account: the
product's platform account, the one that also bills the subscriptions
(`billing.stripe_key()`, STRIPE_PLATFORM_SECRET_KEY). Using the wrong key here
would try to pay our partners out of some cleaning company's balance, so this
module has its own and never touches the global `stripe.api_key` that the other
one sets.

The key travels with each request (`api_key=`) rather than being assigned
globally, so a payout and a cleaning company's own charge cannot step on each
other's credentials when they run in the same process.

Nothing here moves money except `transfer()`, and that is only called from
`affiliates.pay_via_stripe` / `retry_payout`, which write the payout down first
and give Stripe a stable idempotency key.

Every function returns (ok, value_or_error) and never raises.
"""
import billing


def configured():
    return bool(billing.stripe_key())


def _stripe():
    import stripe
    return stripe


def _message(exc):
    return getattr(exc, 'user_message', None) or str(exc)


def _error_class(stripe, name):
    """A Stripe exception class by name, wherever this SDK keeps it: top level
    in current versions, under `stripe.error` in older ones. Never None-checked
    by the caller, so a missing one is an empty tuple (matches nothing)."""
    found = getattr(stripe, name, None) or getattr(getattr(stripe, 'error', None), name, None)
    return found if isinstance(found, type) else ()


def create_account(email, name='', idempotency_key=None):
    """An Express connected account that can receive transfers.
    (True, account_id) or (False, error)."""
    if not configured():
        return False, 'Stripe is not set up on this deployment.'
    stripe = _stripe()
    try:
        extra = {'idempotency_key': idempotency_key} if idempotency_key else {}
        acct = stripe.Account.create(
            api_key=billing.stripe_key(), **extra,
            type='express', country='US', email=email or None,
            business_type='individual',
            capabilities={'transfers': {'requested': True}},
            business_profile={
                'product_description': 'Affiliate commissions for recommending Akye.',
                'mcc': '7311',  # advertising services
            },
            metadata={'name': name, 'purpose': 'affiliate'} if name else {'purpose': 'affiliate'})
        return True, acct.id
    except Exception as e:  # noqa: BLE001
        return False, _message(e)


def onboarding_link(account_id, refresh_url, return_url):
    """Stripe's hosted page where the partner enters bank, tax and ID details.
    (True, url) or (False, error)."""
    if not configured():
        return False, 'Stripe is not set up on this deployment.'
    stripe = _stripe()
    try:
        link = stripe.AccountLink.create(
            api_key=billing.stripe_key(), account=account_id,
            refresh_url=refresh_url, return_url=return_url,
            type='account_onboarding')
        return True, link.url
    except Exception as e:  # noqa: BLE001
        return False, _message(e)


def account_status(account_id):
    """(True, {payouts_enabled, details_submitted}) or (False, error)."""
    if not configured():
        return False, 'Stripe is not set up on this deployment.'
    stripe = _stripe()
    try:
        acct = stripe.Account.retrieve(account_id, api_key=billing.stripe_key())
        return True, {'payouts_enabled': bool(getattr(acct, 'payouts_enabled', False)),
                      'details_submitted': bool(getattr(acct, 'details_submitted', False))}
    except Exception as e:  # noqa: BLE001
        return False, _message(e)


def transfer(account_id, amount_cents, description, idempotency_key):
    """Move `amount_cents` from Akye's balance to the partner's account.

    Returns (True, transfer_id, False) on success, or (False, error, uncertain).
    `uncertain` is True when we cannot tell whether Stripe made the transfer
    (a dropped connection, a timeout): the caller must not assume it failed.
    Retrying with the same idempotency key is always safe, because Stripe
    returns the original transfer instead of making a second.

    THIS MOVES REAL MONEY in live mode."""
    if not configured():
        return False, 'Stripe is not set up on this deployment.', False
    if int(amount_cents) <= 0:
        return False, 'Amount must be greater than $0.', False
    stripe = _stripe()
    try:
        tr = stripe.Transfer.create(
            api_key=billing.stripe_key(), amount=int(amount_cents), currency='usd',
            destination=account_id, description=description or 'Akye partner commission',
            idempotency_key=idempotency_key)
        return True, tr.id, False
    except Exception as e:  # noqa: BLE001
        # A response from Stripe that says no is a definite no. Anything else
        # (the connection dropped, the request timed out, a bug on our side)
        # leaves the answer unknown.
        #
        # A server error (HTTP 5xx, Stripe's APIError) is not an answer: the
        # transfer may have been made before the error response was sent. Left
        # pending, the retry reuses the idempotency key and cannot pay twice;
        # released, the next Pay would make a new payout with a new key.
        base = _error_class(stripe, 'StripeError')
        unsure = tuple(c for c in (_error_class(stripe, 'APIConnectionError'),
                                   _error_class(stripe, 'APIError')) if c)
        status = getattr(e, 'http_status', None)
        definite = bool(base) and isinstance(e, base) \
            and not (unsure and isinstance(e, unsure)) \
            and not (isinstance(status, int) and status >= 500)
        return False, _message(e), not definite
