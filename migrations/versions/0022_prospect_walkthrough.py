"""What was found on a lead's walkthrough.

A commercial quote is only as good as the walkthrough behind it: the floor
area, how many restrooms, whether the kitchen and the hood are part of it, how
often. That lived in somebody's notes app and was typed into the quote by hand
-- or not, and the quote was priced as a full clean of a building that only
wanted its floors done. One nullable text column holding the checklist as
JSON, and when it was done. Every lead already on file reads NULL: no
walkthrough yet, which is the truth.
"""
from alembic import op
import sqlalchemy as sa

revision = '0022_prospect_walkthrough'
down_revision = '0021_quote_prospect'
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
    if not _has_column('prospect', 'walkthrough'):
        op.add_column('prospect', sa.Column('walkthrough', sa.Text(), nullable=True))
    if not _has_column('prospect', 'walkthrough_at'):
        op.add_column('prospect', sa.Column('walkthrough_at', sa.DateTime(), nullable=True))


def downgrade():
    if _has_column('prospect', 'walkthrough_at'):
        op.drop_column('prospect', 'walkthrough_at')
    if _has_column('prospect', 'walkthrough'):
        op.drop_column('prospect', 'walkthrough')
