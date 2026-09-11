"""Canonical presentation helpers for monetary amounts.

Money is stored to cents. Cleaner-facing surfaces must never silently discard
those cents: the amount offered, accepted, displayed, and paid is one fact.
"""
from decimal import Decimal, ROUND_HALF_UP


def usd(value):
    """Return a USD amount with a symbol, separators, and exactly two decimals."""
    amount = Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return f'${amount:,.2f}'
