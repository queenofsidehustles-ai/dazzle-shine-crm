"""One charge and one credit per off-session obligation.

booking.charge_pending holds an off-session charge Stripe has not answered yet,
so every later attempt repeats that exact request (same idempotency key)
instead of making a new one. payment_credit records each Stripe payment intent
credited to a booking, so a replayed or out-of-order webhook cannot credit the
same money twice. A nullable column and a new table; nothing is backfilled.
"""
from alembic import op
import sqlalchemy as sa

revision = '0043_offsession_charge_guard'
down_revision = '0042_walkthrough_payment'
branch_labels = None
depends_on = None


def _schema():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return None
    return bind.execute(sa.text('SELECT current_schema()')).scalar()


def upgrade():
    from sqlalchemy import inspect as sa_inspect
    # Scoped to this schema; see 0019_rental_turnovers for why unscoped lies.
    insp = sa_inspect(op.get_bind())
    schema = _schema()
    have = {c['name'] for c in insp.get_columns('booking', schema=schema)}
    if 'charge_pending' not in have:
        op.add_column('booking', sa.Column('charge_pending', sa.Text(), nullable=True))
    if 'payment_credit' not in set(insp.get_table_names(schema=schema)):
        op.create_table(
            'payment_credit',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('stripe_payment_intent', sa.String(100), nullable=False),
            sa.Column('booking_id', sa.Integer(), nullable=False),
            sa.Column('amount_cents', sa.Integer(), nullable=False),
            sa.Column('outcome', sa.String(20), nullable=False, server_default='credited'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.UniqueConstraint('stripe_payment_intent', name='uq_payment_credit_intent'),
        )
        op.create_index('ix_payment_credit_booking_id', 'payment_credit', ['booking_id'])


def downgrade():
    op.drop_index('ix_payment_credit_booking_id', table_name='payment_credit')
    op.drop_table('payment_credit')
    op.drop_column('booking', 'charge_pending')
