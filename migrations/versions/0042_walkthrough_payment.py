"""What a sales rep was paid for the walkthroughs they booked in a week.

Business-development people are paid a flat amount for each walkthrough they
book, weekly. The count comes from prospect_activity; this table records the
week actually paid, so it is an expense in the books exactly once. A new table
and nothing else: a company with no sales reps has an empty one.
"""
from alembic import op
import sqlalchemy as sa

revision = '0042_walkthrough_payment'
down_revision = '0041_user_worker_model'
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
    if _has_table('walkthrough_payment'):
        return
    op.create_table(
        'walkthrough_payment',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('user_id', sa.Integer, nullable=False),
        sa.Column('user_name', sa.String(120)),
        sa.Column('week_start', sa.Date, nullable=False),
        sa.Column('walkthroughs', sa.Integer, nullable=False),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('method', sa.String(20)),
        sa.Column('note', sa.String(200)),
        sa.Column('paid_at', sa.DateTime),
        sa.UniqueConstraint('user_id', 'week_start', name='uq_walkthrough_payment_user_week'),
    )
    op.create_index('ix_walkthrough_payment_user_id', 'walkthrough_payment', ['user_id'])
    op.create_index('ix_walkthrough_payment_paid_at', 'walkthrough_payment', ['paid_at'])


def downgrade():
    if _has_table('walkthrough_payment'):
        op.drop_table('walkthrough_payment')
