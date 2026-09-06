"""Record what a booking has actually been paid, not merely that it was.

Payment was held as flags — deposit_paid, balance_collected, and a paid_at that
meant "settled in full". A flag is only true against the price on the day it was
set, and prices move: a customer books a three-bed and turns out to have a
four-bed, the scope is corrected, the total goes up. Every flag still said paid,
amount_due() short-circuited to zero, and the extra could not be collected by
any route in the system — the charge button offered nothing and the customer's
own payment page refused their money. The books said paid in full on a job that
was short.

An amount cannot go stale that way. "Paid in full" becomes price minus this,
which re-answers itself the moment either number changes.

Additive and nullable, so it is reversible, and so every existing booking reads
NULL — which payments.collected() takes as the signal to fall back to what those
rows do record. It is deliberately NOT backfilled here: on a settled booking the
only figure available to a backfill is today's price, which on the one kind of
booking this exists to fix is precisely the wrong number. Rather than write a
confident wrong figure into a money column, the fallback stays a fallback, and
the Payment card carries a field for correcting what was actually received.
"""
from alembic import op
import sqlalchemy as sa

revision = '0006_amount_collected'
down_revision = '0005_quote_debris_fee'
branch_labels = None
depends_on = None


def _has_column(table, column):
    """Whether the column is already there. See 0003 — these databases were
    built by a year of self-swallowing ALTER TABLE statements, so what any one
    of them actually has is a question rather than a fact."""
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    return column in {c['name'] for c in sa_inspect(bind).get_columns(table)}


def upgrade():
    if _has_column('booking', 'amount_collected'):
        return
    op.add_column('booking',
                  sa.Column('amount_collected', sa.Numeric(10, 2), nullable=True))


def downgrade():
    if _has_column('booking', 'amount_collected'):
        op.drop_column('booking', 'amount_collected')
