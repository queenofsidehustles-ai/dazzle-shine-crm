"""A commercial quote priced by work area, line by line.

A restaurant's service floor is three jobs: stone or concrete tile on an
auto-scrubber, ceramic tile scrubbed and grouted, hardwood dust-mopped and
never wetted. Each takes its own machine, chemical and time, and a quote that
says one figure for "2,400 sq ft" overcharges the quick floors and undercharges
the slow ones -- and gives the customer nothing to read or to negotiate with.

The lines live with the quote they belong to, as JSON, rather than in a table
of their own: they are only ever read and written as the whole quote, and a
quote's copy, export and delete then carry them without a second place to
forget. Existing quotes read NULL and keep the one-figure layout.
"""
from alembic import op
import sqlalchemy as sa

revision = '0023_quote_line_items'
down_revision = '0022_prospect_walkthrough'
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
    if not _has_column('commercial_quote', 'line_items'):
        op.add_column('commercial_quote', sa.Column('line_items', sa.Text(), nullable=True))
    if not _has_column('commercial_quote', 'show_line_prices'):
        op.add_column('commercial_quote', sa.Column('show_line_prices', sa.Boolean(),
                                                    nullable=True, server_default=sa.true()))


def downgrade():
    if _has_column('commercial_quote', 'show_line_prices'):
        op.drop_column('commercial_quote', 'show_line_prices')
    if _has_column('commercial_quote', 'line_items'):
        op.drop_column('commercial_quote', 'line_items')
