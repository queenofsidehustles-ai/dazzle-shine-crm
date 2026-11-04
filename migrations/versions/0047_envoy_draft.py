"""Envoy's drafts, and what it read on each prospect's website.

One row per prospect per kind of draft (first line, intro email, call script,
day-3 and day-7 follow-ups). A new table and nothing else, so a company that
never uses Envoy has an empty one and notices nothing -- additive, as the
rollback window requires (AKYE_COHORT_RELEASE_CONTROL.md).

Everything else Envoy keeps (whether it is switched on, the service area, the
weekday rotation) is a handful of BusinessSetting rows, which need no schema.
"""
from alembic import op
import sqlalchemy as sa

revision = '0047_envoy_draft'
down_revision = '0046_booking_charge_tried'
branch_labels = None
depends_on = None


def _current_schema():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return None
    return bind.execute(sa.text('SELECT current_schema()')).scalar()


def _has_table(name):
    from sqlalchemy import inspect as sa_inspect
    # Scoped to this schema; see 0019_rental_turnovers for why unscoped lies.
    return name in set(sa_inspect(op.get_bind()).get_table_names(
        schema=_current_schema()))


def upgrade():
    if not _has_table('envoy_site'):
        op.create_table(
            'envoy_site',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('prospect_id', sa.Integer, nullable=False),
            sa.Column('url', sa.String(300)),
            sa.Column('ok', sa.Boolean),
            sa.Column('title', sa.String(200)),
            sa.Column('summary', sa.Text),
            sa.Column('email', sa.String(200)),
            sa.Column('error', sa.String(200)),
            sa.Column('fetched_at', sa.DateTime),
        )
        op.create_index('ix_envoy_site_prospect_id', 'envoy_site', ['prospect_id'], unique=True)
    if _has_table('envoy_draft'):
        return
    op.create_table(
        'envoy_draft',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('prospect_id', sa.Integer, nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('subject', sa.String(200)),
        sa.Column('body', sa.Text, nullable=False),
        sa.Column('source', sa.String(10)),
        sa.Column('created_at', sa.DateTime),
        sa.UniqueConstraint('prospect_id', 'kind', name='uq_envoy_draft_prospect_kind'),
    )
    op.create_index('ix_envoy_draft_prospect_id', 'envoy_draft', ['prospect_id'])


def downgrade():
    if _has_table('envoy_draft'):
        op.drop_table('envoy_draft')
    if _has_table('envoy_site'):
        op.drop_table('envoy_site')
