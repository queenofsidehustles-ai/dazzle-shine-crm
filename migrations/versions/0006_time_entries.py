"""One clock-in and clock-out per cleaner per job.

The clock already existed, on the job's checklist. There is one checklist per
job, so a two-person job had a single shared clock and no way to say who
worked which hours. Enough to know somebody turned up; useless for paying
anybody by the hour, which is how a good number of cleaning companies pay.

Several rows per cleaner per job are allowed deliberately: somebody who leaves
and comes back has two spells, and two rows is the honest record of that.
"""
from alembic import op
import sqlalchemy as sa

revision = '0006_time_entries'
down_revision = '0005_entitlement_denial'
branch_labels = None
depends_on = None


def _current_schema():
    """The schema being built, or None where that has no meaning (SQLite)."""
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return None
    return bind.execute(sa.text('SELECT current_schema()')).scalar()


def _has_table(name):
    from sqlalchemy import inspect as sa_inspect
    return name in sa_inspect(op.get_bind()).get_table_names(
        schema=_current_schema())


def upgrade():
    if _has_table('time_entry'):
        return
    op.create_table(
        'time_entry',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('booking_id', sa.Integer(),
                  sa.ForeignKey('booking.id'), nullable=False, index=True),
        sa.Column('staff_id', sa.Integer(),
                  sa.ForeignKey('staff.id'), nullable=False, index=True),
        sa.Column('clock_in_at', sa.DateTime(), nullable=False),
        sa.Column('clock_out_at', sa.DateTime()),
        sa.Column('note', sa.String(200)),
        sa.Column('edited_by', sa.String(80)),
        sa.Column('created_at', sa.DateTime()),
    )


def downgrade():
    if _has_table('time_entry'):
        op.drop_table('time_entry')
