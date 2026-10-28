"""Remember what the last confirmation send delivered, so a retry after a
partial send sends only what did not go.

booking.customer_send_log is JSON: the notification kind, when, and for each
of the confirmation and the payment request which channels reached which
address and which did not. One nullable column.
"""
from alembic import op
import sqlalchemy as sa

revision = '0044_booking_send_log'
down_revision = '0043_offsession_charge_guard'
branch_labels = None
depends_on = None


def _schema():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return None
    return bind.execute(sa.text('SELECT current_schema()')).scalar()


def upgrade():
    from sqlalchemy import inspect as sa_inspect
    have = {c['name'] for c in sa_inspect(op.get_bind()).get_columns('booking', schema=_schema())}
    if 'customer_send_log' not in have:
        op.add_column('booking', sa.Column('customer_send_log', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('booking', 'customer_send_log')
