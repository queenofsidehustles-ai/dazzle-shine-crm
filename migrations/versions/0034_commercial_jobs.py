"""Commercial jobs are bookings.

A commercial account used to be a record and nothing else: no job on the
calendar, no cleaner, no confirmation, no way to be paid. A commercial job is
now a Booking like any other -- the schedule, the crew, the pay links and the
invoice all come with it -- that names the account it is for and carries the
scope of work in place of bedrooms and bathrooms.
"""
from alembic import op
import sqlalchemy as sa

revision = '0034_commercial_jobs'
down_revision = '0033_photo_optional_wording'
branch_labels = None
depends_on = None


def _schema():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return None
    return bind.execute(sa.text('SELECT current_schema()')).scalar()


def _has_column(table, column):
    from sqlalchemy import inspect as sa_inspect
    return column in {c['name']
                      for c in sa_inspect(op.get_bind()).get_columns(table, schema=_schema())}


def upgrade():
    if not _has_column('booking', 'commercial_account_id'):
        op.add_column('booking', sa.Column('commercial_account_id', sa.Integer(), nullable=True))
        op.create_index('ix_booking_commercial_account_id', 'booking', ['commercial_account_id'])
    if not _has_column('booking', 'scope_of_work'):
        op.add_column('booking', sa.Column('scope_of_work', sa.Text(), nullable=True))


def downgrade():
    op.drop_index('ix_booking_commercial_account_id', table_name='booking')
    op.drop_column('booking', 'scope_of_work')
    op.drop_column('booking', 'commercial_account_id')
