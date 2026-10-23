"""Mark the owner's own team row.

A new company's owner is created as its first cleaner, so a job can be assigned
to them before anyone else is hired (owner_cleaner.py). This flag tells payroll,
tax forms and the contractor reminders that the row is the owner, not a
contractor to be paid or chased for paperwork. Every row already on file reads
NULL, which means false.
"""
from alembic import op
import sqlalchemy as sa

revision = '0036_staff_is_owner'
down_revision = '0035_commercial_jobs'
branch_labels = None
depends_on = None


def _has_column(table, column):
    """In the schema being migrated; see 0034_booking_repeat_of."""
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    schema = None
    if bind.dialect.name == 'postgresql':
        schema = bind.execute(sa.text('SELECT current_schema()')).scalar()
    return column in {c['name']
                      for c in sa_inspect(bind).get_columns(table, schema=schema)}


def upgrade():
    if not _has_column('staff', 'is_owner'):
        op.add_column('staff', sa.Column('is_owner', sa.Boolean, nullable=True,
                                         server_default=sa.false()))


def downgrade():
    if _has_column('staff', 'is_owner'):
        op.drop_column('staff', 'is_owner')
