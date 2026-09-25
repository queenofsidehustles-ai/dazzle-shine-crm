"""Record how a deposit was actually paid.

Every deposit used to mean one thing: a Stripe card charge, because that was
the only way to take one. Now the office can record a deposit paid in cash,
Zelle, Venmo or check too (see payments.mark_deposit_paid), and the booking
needs somewhere to say which one it was — the same distinction paid_method
already draws for a balance settled in full.

Additive and nullable, so every deposit already on file reads NULL. That is
read as 'card' wherever it matters: every deposit taken before this column
existed went through Stripe, because there was no other way to take one.
"""
from alembic import op
import sqlalchemy as sa

revision = '0010_deposit_method'
down_revision = '0009_company_applicants'
branch_labels = None
depends_on = None


def _has_column(table, column):
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    return column in {c['name'] for c in sa_inspect(bind).get_columns(table)}


def upgrade():
    if _has_column('booking', 'deposit_method'):
        return
    op.add_column('booking', sa.Column('deposit_method', sa.String(20), nullable=True))


def downgrade():
    if _has_column('booking', 'deposit_method'):
        op.drop_column('booking', 'deposit_method')
