"""Which email sequence a prospect is in, and how far through it.

Calls are scheduled by next_action_date and made by a person. These three
columns carry the emails that go out between the calls: the short chase after
"send your information over", and the quarterly check-in for a prospect who is
under contract elsewhere.

One sequence per prospect, on the prospect itself rather than in a join table.
Two sequences mailing the same facilities manager in the same week is how a
sending domain gets blocked.
"""
import sqlalchemy as sa
from alembic import op

revision = '0017_prospect_sequences'
down_revision = '0016_prospect_renewal'
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
    if 'sequence' not in have:
        op.add_column('prospect', sa.Column('sequence', sa.String(20)))
        op.create_index('ix_prospect_sequence', 'prospect', ['sequence'])
    if 'drip_step' not in have:
        op.add_column('prospect',
                      sa.Column('drip_step', sa.Integer(), server_default='0'))
    if 'last_drip_at' not in have:
        op.add_column('prospect', sa.Column('last_drip_at', sa.DateTime()))


def downgrade():
    have = _columns('prospect')
    if 'last_drip_at' in have:
        op.drop_column('prospect', 'last_drip_at')
    if 'drip_step' in have:
        op.drop_column('prospect', 'drip_step')
    if 'sequence' in have:
        op.drop_index('ix_prospect_sequence', table_name='prospect')
        op.drop_column('prospect', 'sequence')
