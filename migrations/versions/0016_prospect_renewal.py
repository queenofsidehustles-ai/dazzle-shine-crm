"""When the incumbent's contract ends, as a date rather than a note.

A commercial prospect who says no is usually saying "we are under contract".
`renewal_note` has always been able to hold "March 2027", but a note is only
ever found again by the person who typed it. A date can be queried, so the
prospect can be put back on the call list a month before the contract ends --
which is the one week of the year that a competitor is actually displaceable.

`renewal_woken_at` records that the wake-up has happened, so it happens once
rather than on each of the thirty nights before the date.
"""
import sqlalchemy as sa
from alembic import op

revision = '0016_prospect_renewal'
down_revision = '0015_faq'
branch_labels = None
depends_on = None


def _current_schema():
    import sqlalchemy as _sa
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return None
    return bind.execute(_sa.text('SELECT current_schema()')).scalar()


def _columns(table):
    from sqlalchemy import inspect as sa_inspect
    insp = sa_inspect(op.get_bind())
    if table not in insp.get_table_names(schema=_current_schema()):
        return set()
    return {c['name'] for c in insp.get_columns(table, schema=_current_schema())}


def upgrade():
    have = _columns('prospect')
    if not have:
        return
    if 'renewal_date' not in have:
        op.add_column('prospect', sa.Column('renewal_date', sa.String(10)))
        op.create_index('ix_prospect_renewal_date', 'prospect', ['renewal_date'])
    if 'renewal_woken_at' not in have:
        op.add_column('prospect', sa.Column('renewal_woken_at', sa.DateTime()))


def downgrade():
    have = _columns('prospect')
    if 'renewal_woken_at' in have:
        op.drop_column('prospect', 'renewal_woken_at')
    if 'renewal_date' in have:
        op.drop_index('ix_prospect_renewal_date', table_name='prospect')
        op.drop_column('prospect', 'renewal_date')
