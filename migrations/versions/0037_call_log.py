"""A record of every call placed from the Find Leads call sheet.

One row per call, written when the caller presses Call and filled in from
Twilio's reports afterwards. It is what the monthly call limit counts, and it
is where a recording is found again. A new table and nothing else, so a
company that never calls has an empty one and notices nothing.
"""
from alembic import op
import sqlalchemy as sa

revision = '0037_call_log'
down_revision = '0036_keep_cleaner_rate'
branch_labels = None
depends_on = None


def _current_schema():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return None
    return bind.execute(sa.text('SELECT current_schema()')).scalar()


def _has_table(name):
    from sqlalchemy import inspect as sa_inspect
    # Scoped to this schema; see 0019_rental_turnovers for why unscoped lies.
    return name in set(sa_inspect(op.get_bind()).get_table_names(
        schema=_current_schema()))


def upgrade():
    if _has_table('call_log'):
        return
    op.create_table(
        'call_log',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('prospect_id', sa.Integer, sa.ForeignKey('prospect.id')),
        sa.Column('user_id', sa.Integer),
        sa.Column('agent', sa.String(100)),
        sa.Column('to_number', sa.String(40)),
        sa.Column('call_sid', sa.String(64)),
        sa.Column('status', sa.String(20)),
        sa.Column('duration', sa.Integer),
        sa.Column('recording_sid', sa.String(64)),
        sa.Column('recording_seconds', sa.Integer),
        sa.Column('created_at', sa.DateTime),
        sa.Column('ended_at', sa.DateTime),
    )
    op.create_index('ix_call_log_prospect_id', 'call_log', ['prospect_id'])
    op.create_index('ix_call_log_call_sid', 'call_log', ['call_sid'])
    op.create_index('ix_call_log_created_at', 'call_log', ['created_at'])


def downgrade():
    if _has_table('call_log'):
        op.drop_table('call_log')
