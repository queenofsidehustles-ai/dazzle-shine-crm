"""Remember which finished job an on-demand repeat was made from.

"Book again" on a completed booking creates a fresh one-off booking for a client
who comes back now and then, not on a schedule. This nullable column links it to
the job it copied, so the new booking can say "Repeat of #3" and the original
can list its repeats. Every booking already on file reads NULL.
"""
from alembic import op
import sqlalchemy as sa

revision = '0034_booking_repeat_of'
down_revision = '0021_photo_optional_wording'
branch_labels = None
depends_on = None


def _has_column(table, column):
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    return column in {c['name'] for c in sa_inspect(bind).get_columns(table)}


def upgrade():
    if not _has_column('booking', 'repeat_of_booking_id'):
        op.add_column('booking', sa.Column('repeat_of_booking_id', sa.Integer, nullable=True))
        op.create_index('ix_booking_repeat_of_booking_id', 'booking', ['repeat_of_booking_id'])


def downgrade():
    if _has_column('booking', 'repeat_of_booking_id'):
        op.drop_index('ix_booking_repeat_of_booking_id', table_name='booking')
        op.drop_column('booking', 'repeat_of_booking_id')
