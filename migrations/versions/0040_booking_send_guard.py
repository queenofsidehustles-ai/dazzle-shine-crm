"""Remember the last confirmation send on a booking, so a double-click on the
Send button does not send the customer everything twice.

booking.customer_send_at is when it went; booking.customer_send_kind is what
went with it ('none', 'deposit' or 'full'). Two nullable columns and nothing
else.
"""
from alembic import op
import sqlalchemy as sa

revision = '0040_booking_send_guard'
down_revision = '0039_call_recording_consent'
branch_labels = None
depends_on = None


def _schema():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return None
    return bind.execute(sa.text('SELECT current_schema()')).scalar()


def _columns():
    from sqlalchemy import inspect as sa_inspect
    return {c['name'] for c in sa_inspect(op.get_bind()).get_columns('booking', schema=_schema())}


def upgrade():
    have = _columns()
    if 'customer_send_at' not in have:
        op.add_column('booking', sa.Column('customer_send_at', sa.DateTime(), nullable=True))
    if 'customer_send_kind' not in have:
        op.add_column('booking', sa.Column('customer_send_kind', sa.String(10), nullable=True))


def downgrade():
    op.drop_column('booking', 'customer_send_kind')
    op.drop_column('booking', 'customer_send_at')
