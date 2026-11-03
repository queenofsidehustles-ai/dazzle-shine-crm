"""Remember that a charge was tried, so a missed day can be caught up safely.

booking.charge_tried_at: when an off-session charge was first attempted on the
job. Existing jobs dated before today are marked tried, so the first catch-up
never reaches back to collect something older code already handled.
"""
from alembic import op
import sqlalchemy as sa

revision = '0046_booking_charge_tried'
down_revision = '0045_walkthrough_pay_event'
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
    have = {c['name'] for c in sa_inspect(op.get_bind()).get_columns(
        'booking', schema=_schema())}
    if 'charge_tried_at' in have:
        return
    op.add_column('booking', sa.Column('charge_tried_at', sa.DateTime(), nullable=True))
    op.execute(sa.text(
        "UPDATE booking SET charge_tried_at = CURRENT_TIMESTAMP "
        "WHERE preferred_date IS NOT NULL AND preferred_date < to_char(CURRENT_DATE, 'YYYY-MM-DD')"
        if op.get_bind().dialect.name == 'postgresql' else
        "UPDATE booking SET charge_tried_at = CURRENT_TIMESTAMP "
        "WHERE preferred_date IS NOT NULL AND preferred_date < date('now')"))


def downgrade():
    op.drop_column('booking', 'charge_tried_at')
