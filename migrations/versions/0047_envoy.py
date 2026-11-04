"""Envoy: one row per morning run, and the drafts written for each prospect.

`envoy_run` holds one row per local day (run_date is unique), which is what
stops two overlapping scheduler calls from searching twice. `envoy_draft`
holds the words Envoy wrote for a prospect -- one row per prospect, never a
send. Both additive: a company that never turns Envoy on has two empty
tables and notices nothing, and older code ignores them, so a rollback across
this migration is safe.
"""
from alembic import op
import sqlalchemy as sa

revision = '0047_envoy'
down_revision = '0046_booking_charge_tried'
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


def upgrade():
    if not _has_table('envoy_run'):
        op.create_table(
            'envoy_run',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('run_date', sa.String(10), nullable=False, unique=True),
            sa.Column('category', sa.String(40)),
            sa.Column('started_at', sa.DateTime),
            sa.Column('finished_at', sa.DateTime),
            sa.Column('found', sa.Integer),
            sa.Column('created', sa.Integer),
            sa.Column('detail', sa.String(300)),
            sa.Column('emailed_at', sa.DateTime),
        )
    if not _has_table('envoy_draft'):
        op.create_table(
            'envoy_draft',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('prospect_id', sa.Integer, nullable=False, unique=True, index=True),
            sa.Column('first_line', sa.Text),
            sa.Column('email_subject', sa.String(200)),
            sa.Column('email_body', sa.Text),
            sa.Column('call_script', sa.Text),
            sa.Column('followup_day3', sa.Text),
            sa.Column('followup_day7', sa.Text),
            sa.Column('source', sa.String(20)),
            sa.Column('model', sa.String(60)),
            sa.Column('facts', sa.Text),
            sa.Column('created_at', sa.DateTime, index=True),
            sa.Column('updated_at', sa.DateTime),
        )


def downgrade():
    if _has_table('envoy_draft'):
        op.drop_table('envoy_draft')
    if _has_table('envoy_run'):
        op.drop_table('envoy_run')
