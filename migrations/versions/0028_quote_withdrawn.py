"""A sent quote is withdrawn or revised, never rewritten.

The link in a customer's email showed whatever the quote said now, so a price
changed after sending changed under the link they were given -- and a quote
could be accepted on terms nobody had sent. From here only a draft is edited;
a sent quote is withdrawn, or revised into a new draft that remembers what it
replaced. Two nullable columns: when it was withdrawn, and which quote a
revision came from. Every quote already on file reads NULL: neither.
"""
from alembic import op
import sqlalchemy as sa

revision = '0028_quote_withdrawn'
down_revision = '0027_quote_first_visit_premium'
branch_labels = None
depends_on = None


def _has_column(table, column):
    """In the schema being migrated -- see 0021 for why."""
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    schema = None
    if bind.dialect.name == 'postgresql':
        schema = bind.execute(sa.text('SELECT current_schema()')).scalar()
    return column in {c['name'] for c in sa_inspect(bind).get_columns(table, schema=schema)}


def upgrade():
    if not _has_column('commercial_quote', 'withdrawn_at'):
        op.add_column('commercial_quote', sa.Column('withdrawn_at', sa.DateTime(), nullable=True))
    if not _has_column('commercial_quote', 'revised_from_id'):
        op.add_column('commercial_quote', sa.Column('revised_from_id', sa.Integer(), nullable=True))
        op.create_index('ix_commercial_quote_revised_from_id', 'commercial_quote', ['revised_from_id'])


def downgrade():
    if _has_column('commercial_quote', 'revised_from_id'):
        op.drop_index('ix_commercial_quote_revised_from_id', 'commercial_quote')
        op.drop_column('commercial_quote', 'revised_from_id')
    if _has_column('commercial_quote', 'withdrawn_at'):
        op.drop_column('commercial_quote', 'withdrawn_at')
