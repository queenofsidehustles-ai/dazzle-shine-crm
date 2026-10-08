"""Which lead a commercial quote was written for.

A quote and the call-list entry it came from were two records that never met:
sending a proposal left the lead sitting in "Interested" with a follow-up call
for the wrong reason, and an accepted quote made a new account while the lead
stayed open on the call list -- so somebody rang a business that had already
signed. One nullable column joins them. Every quote already on file reads NULL
and belongs to no lead, which is exactly what it did yesterday.
"""
from alembic import op
import sqlalchemy as sa

revision = '0021_quote_prospect'
down_revision = '0020_booking_cc'
branch_labels = None
depends_on = None


def _has_column(table, column):
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    return column in {c['name'] for c in sa_inspect(bind).get_columns(table)}


def upgrade():
    if not _has_column('commercial_quote', 'prospect_id'):
        op.add_column('commercial_quote', sa.Column('prospect_id', sa.Integer(), nullable=True))
        op.create_index('ix_commercial_quote_prospect_id', 'commercial_quote', ['prospect_id'])


def downgrade():
    if _has_column('commercial_quote', 'prospect_id'):
        op.drop_index('ix_commercial_quote_prospect_id', table_name='commercial_quote')
        op.drop_column('commercial_quote', 'prospect_id')
