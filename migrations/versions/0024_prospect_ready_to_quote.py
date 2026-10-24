"""A lead handed to the owner to quote.

A cold caller's job ends where the pricing starts: they qualify the lead and
book (or do) the walkthrough, and the owner writes the quote. That hand-off
lived in somebody's head -- or in a text the owner read at 11pm. Two nullable
columns: when the lead was handed over, and by whom. Every lead already on
file reads NULL: not handed over, which is the truth.
"""
from alembic import op
import sqlalchemy as sa

revision = '0024_prospect_ready_to_quote'
down_revision = '0023_quote_line_items'
branch_labels = None
depends_on = None


def _has_column(table, column):
    """In the schema being migrated -- see 0021 for why."""
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    schema = None
    if bind.dialect.name == 'postgresql':
        schema = bind.execute(sa.text('SELECT current_schema()')).scalar()
    return column in {c['name']
                      for c in sa_inspect(bind).get_columns(table, schema=schema)}


def upgrade():
    if not _has_column('prospect', 'ready_to_quote_at'):
        op.add_column('prospect', sa.Column('ready_to_quote_at', sa.DateTime(), nullable=True))
    if not _has_column('prospect', 'ready_by'):
        op.add_column('prospect', sa.Column('ready_by', sa.String(100), nullable=True))


def downgrade():
    if _has_column('prospect', 'ready_by'):
        op.drop_column('prospect', 'ready_by')
    if _has_column('prospect', 'ready_to_quote_at'):
        op.drop_column('prospect', 'ready_to_quote_at')
