"""What was done about walkthrough pay, kept for good.

A week's walkthrough pay can be marked paid and, if it was wrong, reversed. The
live record (walkthrough_payment) is removed on a reversal so the week can be
paid again correctly; this table keeps the fact that it was paid, what was
counted, who paid and who reversed it and why. A new table and nothing else.
"""
from alembic import op
import sqlalchemy as sa

revision = '0045_walkthrough_pay_event'
down_revision = '0044_booking_send_log'
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
    if _has_table('walkthrough_pay_event'):
        return
    op.create_table(
        'walkthrough_pay_event',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('user_id', sa.Integer, nullable=False),
        sa.Column('user_name', sa.String(120)),
        sa.Column('week_start', sa.Date, nullable=False),
        sa.Column('action', sa.String(12), nullable=False),
        sa.Column('walkthroughs', sa.Integer, nullable=False),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('method', sa.String(20)),
        sa.Column('items', sa.Text),
        sa.Column('actor_id', sa.Integer),
        sa.Column('actor_name', sa.String(120)),
        sa.Column('reason', sa.String(300)),
        sa.Column('created_at', sa.DateTime),
    )
    op.create_index('ix_walkthrough_pay_event_user_id', 'walkthrough_pay_event', ['user_id'])
    op.create_index('ix_walkthrough_pay_event_week_start', 'walkthrough_pay_event', ['week_start'])
    op.create_index('ix_walkthrough_pay_event_created_at', 'walkthrough_pay_event', ['created_at'])


def downgrade():
    if _has_table('walkthrough_pay_event'):
        op.drop_table('walkthrough_pay_event')
