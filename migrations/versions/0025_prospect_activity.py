"""Who did what on a lead, and a daily call target for each Sales rep.

A lead remembered only its latest call and a running count of attempts, so
there was no way to say how many calls a rep made today, or this week, or
whether the conversations turned into walkthroughs. `prospect_activity`
keeps one row per call, text, email, walkthrough and hand-off, with who did
it. `user.daily_call_target` is the number the owner expects of a rep; NULL
means the company default. Both additive: a company with no reps has an
empty table and notices nothing.
"""
from alembic import op
import sqlalchemy as sa

revision = '0025_prospect_activity'
down_revision = '0024_prospect_ready_to_quote'
branch_labels = None
depends_on = None


def _schema():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return None
    return bind.execute(sa.text('SELECT current_schema()')).scalar()


def _has_table(name):
    """In the schema being migrated -- see 0019 for why."""
    from sqlalchemy import inspect as sa_inspect
    return name in set(sa_inspect(op.get_bind()).get_table_names(schema=_schema()))


def _has_column(table, column):
    from sqlalchemy import inspect as sa_inspect
    return column in {c['name']
                      for c in sa_inspect(op.get_bind()).get_columns(table, schema=_schema())}


def upgrade():
    if not _has_table('prospect_activity'):
        op.create_table(
            'prospect_activity',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('prospect_id', sa.Integer, index=True),
            sa.Column('business_name', sa.String(200)),
            sa.Column('user_id', sa.Integer),
            sa.Column('user_name', sa.String(120), index=True),
            sa.Column('kind', sa.String(30), nullable=False),
            sa.Column('outcome', sa.String(30)),
            sa.Column('created_at', sa.DateTime, index=True),
        )
    if not _has_column('user', 'daily_call_target'):
        op.add_column('user', sa.Column('daily_call_target', sa.Integer(), nullable=True))


def downgrade():
    if _has_column('user', 'daily_call_target'):
        op.drop_column('user', 'daily_call_target')
    if _has_table('prospect_activity'):
        op.drop_table('prospect_activity')
