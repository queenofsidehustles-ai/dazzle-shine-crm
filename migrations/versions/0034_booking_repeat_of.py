"""Remember which finished job an on-demand repeat was made from.

"Book again" on a completed booking creates a fresh one-off booking for a client
who comes back now and then, not on a schedule. This nullable column links it to
the job it copied, so the new booking can say "Repeat of #3" and the original
can list its repeats. Every booking already on file reads NULL.
"""
from alembic import op
import sqlalchemy as sa

revision = '0034_booking_repeat_of'
# After 0033, the head both branches share. (Written on main's old chain, where
# 0021_photo_optional_wording was the head; that id now sits before 0021.)
down_revision = '0033_photo_optional_wording'
branch_labels = None
depends_on = None


def _has_column(table, column):
    """In the schema being migrated. A company's schema is migrated with
    `<company>, public` on the search path, and public is migrated first -- so
    asking without a schema finds public's new column and skips every
    company's. Same shape as 0021_quote_prospect: SQLite has no schemas."""
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    schema = None
    if bind.dialect.name == 'postgresql':
        schema = bind.execute(sa.text('SELECT current_schema()')).scalar()
    return column in {c['name']
                      for c in sa_inspect(bind).get_columns(table, schema=schema)}


def upgrade():
    if not _has_column('booking', 'repeat_of_booking_id'):
        op.add_column('booking', sa.Column('repeat_of_booking_id', sa.Integer, nullable=True))
        op.create_index('ix_booking_repeat_of_booking_id', 'booking', ['repeat_of_booking_id'])


def downgrade():
    if _has_column('booking', 'repeat_of_booking_id'):
        op.drop_index('ix_booking_repeat_of_booking_id', table_name='booking')
        op.drop_column('booking', 'repeat_of_booking_id')
