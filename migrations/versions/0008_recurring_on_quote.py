"""One quote that says both prices: the first clean, and every one after it.

A caller asks what a deep clean costs, and the real answer has two halves --
what it takes to get the place right, and what it takes to keep it that way.
Sent as two emails on two days, the customer compares two numbers out of
context and the second email is the one that does not get opened.

Additive and nullable, so every quote already sent stays exactly as it was.
"""
import sqlalchemy as sa
from alembic import op

revision = '0008_recurring_on_quote'
down_revision = '0007_hold_and_promised_checklist'
branch_labels = None
depends_on = None


def _current_schema():
    """The schema this is running in, or None on SQLite.

    Same shape as 0004 and 0005: SQLite has no schemas and asking it for
    current_schema() raises rather than returning nothing.
    """
    import sqlalchemy as _sa
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return None
    return bind.execute(_sa.text('SELECT current_schema()')).scalar()


def _columns():
    from sqlalchemy import inspect as sa_inspect
    try:
        return {c['name'] for c in sa_inspect(op.get_bind()).get_columns(
            'lead', schema=_current_schema())}
    except Exception:
        return set()


def upgrade():
    have = _columns()
    # A database built straight from the models already has these, and adding
    # one twice is what stops such an install migrating forward.
    if 'recurring_price' not in have:
        op.add_column('lead', sa.Column('recurring_price', sa.Numeric(10, 2)))
    if 'recurring_frequency' not in have:
        op.add_column('lead', sa.Column('recurring_frequency', sa.String(20)))


def downgrade():
    have = _columns()
    if 'recurring_frequency' in have:
        op.drop_column('lead', 'recurring_frequency')
    if 'recurring_price' in have:
        op.drop_column('lead', 'recurring_price')
