"""What Stripe actually kept, straight from their books.

Estimating "2.9% + 30¢" gets close and is still wrong — it misses refund fees,
dispute fees, Connect payout fees, and any rate that differs from the sticker
price. Stripe's balance transactions already carry the real figure on every
movement, so this reads it rather than guessing.

Safe to call repeatedly: syncing a month replaces that month's stored number.
"""
import os
from calendar import monthrange
from datetime import datetime, timezone

import stripe

from extensions import db
from models import ProcessingFee


def is_configured():
    return bool(os.environ.get('STRIPE_SECRET_KEY', ''))


def _epoch(y, m, day, end=False):
    dt = datetime(y, m, day, 23, 59, 59 if end else 0, tzinfo=timezone.utc) if end \
        else datetime(y, m, day, 0, 0, 0, tzinfo=timezone.utc)
    return int(dt.timestamp())


def fetch_month_fees(year, month):
    """Total fees Stripe charged in a calendar month.
    Returns (ok, amount_or_error)."""
    if not is_configured():
        return False, 'Stripe is not configured (missing STRIPE_SECRET_KEY).'
    stripe.api_key = os.environ['STRIPE_SECRET_KEY']
    start = _epoch(year, month, 1)
    end = _epoch(year, month, monthrange(year, month)[1], end=True)
    total = 0
    try:
        # auto_paging_iter walks past the 100-per-page limit on its own.
        for txn in stripe.BalanceTransaction.list(
                created={'gte': start, 'lte': end}, limit=100).auto_paging_iter():
            total += (txn.get('fee') or 0)
    except stripe.error.StripeError as e:
        return False, str(e)
    except Exception as e:                     # network, auth, anything else
        return False, str(e)
    return True, round(total / 100.0, 2)       # Stripe reports cents


def sync_month(year, month):
    """Pull one month's fees and store them. Returns (ok, amount_or_error)."""
    ok, result = fetch_month_fees(year, month)
    if not ok:
        return False, result
    row = ProcessingFee.query.filter_by(year=year, month=month).first()
    if not row:
        row = ProcessingFee(year=year, month=month)
        db.session.add(row)
    row.amount = result
    row.synced_at = datetime.utcnow()
    db.session.commit()
    return True, result


def sync_months(months):
    """Sync a list of (year, month). Returns (synced_count, [error strings])."""
    done, errors = 0, []
    for y, m in months:
        ok, result = sync_month(y, m)
        if ok:
            done += 1
        else:
            errors.append(f'{y}-{m:02d}: {result}')
    return done, errors
