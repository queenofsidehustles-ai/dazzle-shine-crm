"""Record what deposit a booking actually paid.

The deposit was a constant, so crediting it against a balance could read the
constant. It is a setting now, and the moment it changes those stop being the
same number: every booking that had paid $50 would start being credited the new
figure, and a job behind a $75 setting would collect $25 too little.

What was charged is a fact about that booking, not about today's settings.

Additive and nullable, so it is reversible and so every booking taken before
today reads NULL — which payments.amount_due() takes as the signal to fall back
to the deposit in force. For those bookings that is the right answer, because
the setting has not moved since they were taken. It stops being the right
answer the first time it does, which is why new bookings record it.
"""
from alembic import op
import sqlalchemy as sa

revision = '0003_deposit_amount_paid'
down_revision = '0002_money_to_numeric'
branch_labels = None
depends_on = None


def _has_column(table, column):
    """Whether the column is already there.

    Migrations are being adopted onto databases whose history nobody recorded —
    a year of hand-written ALTER TABLE statements swallowed their own errors, so
    what any given instance actually has is a question rather than a fact. A
    migration that assumes and is wrong stops a business from booting. Checking
    costs one query."""
    from sqlalchemy import inspect as sa_inspect
    import sqlalchemy as _sa
    bind = op.get_bind()
    # Schema-explicit on Postgres: asking by bare name resolves through
    # search_path into public, which would report the column present in every
    # company's schema the moment it existed in one. None on SQLite, which has
    # no schemas and no current_schema() -- asking it there is a syntax error.
    schema = None
    if bind.dialect.name == 'postgresql':
        schema = bind.execute(_sa.text('SELECT current_schema()')).scalar()
    return column in {c['name']
                      for c in sa_inspect(bind).get_columns(table, schema=schema)}


def upgrade():
    if _has_column('booking', 'deposit_amount_paid'):
        return
    op.add_column('booking',
                  sa.Column('deposit_amount_paid', sa.Numeric(10, 2),
                            nullable=True))


def downgrade():
    if _has_column('booking', 'deposit_amount_paid'):
        op.drop_column('booking', 'deposit_amount_paid')
