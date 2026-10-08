"""Which call-list lead a quote was written for -- commercial or residential.

A quote and the call-list entry it came from were two records that never met:
sending a proposal left the lead sitting in "Interested" with a follow-up call
for the wrong reason, and an accepted quote made a new account while the lead
stayed open on the call list -- so somebody rang a business that had already
signed. A call-list lead is quoted on whichever form fits the work -- a
commercial contract, or a residential per-home price for the property manager
buying turnovers -- so both carry the link. Nullable: every quote already on
file reads NULL and belongs to no lead, which is exactly what it did yesterday.
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


_TABLES = ('commercial_quote', 'lead')


def upgrade():
    for table in _TABLES:
        if not _has_column(table, 'prospect_id'):
            op.add_column(table, sa.Column('prospect_id', sa.Integer(), nullable=True))
            op.create_index(f'ix_{table}_prospect_id', table, ['prospect_id'])


def downgrade():
    for table in _TABLES:
        if _has_column(table, 'prospect_id'):
            op.drop_index(f'ix_{table}_prospect_id', table_name=table)
            op.drop_column(table, 'prospect_id')
