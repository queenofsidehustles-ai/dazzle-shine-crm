"""Agreements, amendments, the delivery outcome, and an audit trail.

0029 kept what was sent and what the customer answered. Three questions it
left without a table of their own:

  commercial_agreement             what an acceptance made binding -- the
                                   accepted revision, the answer, the account,
                                   from which day -- and, for an amendment,
                                   the agreement it replaces (kept unchanged).
  commercial_quote_delivery_event  what the mail service said afterwards:
                                   delivered, bounced, marked as spam.
  contract_audit_event             who did what to a quote or agreement, when,
                                   from where, with which request.

All three refuse UPDATE in the database, like 0029's tables; agreements,
answers and audit entries also refuse DELETE, except inside a backup restore
(which sets akye.restoring for its one transaction). On
commercial_quote: amends_agreement_id, for a quote written to amend one.
Every existing row reads NULL; quotes accepted before this have no agreement
row (their 0029 response is their record) and amending them still works.
"""
from alembic import op
import sqlalchemy as sa

revision = '0030_contract_trail'
down_revision = '0029_quote_evidence'
branch_labels = None
depends_on = None

FROZEN = ('commercial_agreement', 'commercial_quote_delivery_event', 'contract_audit_event')
# Never deleted either (nothing references them, so no foreign key keeps them),
# except by a backup restore, which says so. 0029's answers join them here.
KEPT = ('commercial_quote_response', 'commercial_agreement', 'contract_audit_event')


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
    if not _has_column('commercial_quote', 'amends_agreement_id'):
        op.add_column('commercial_quote', sa.Column('amends_agreement_id', sa.Integer(), nullable=True))
        op.create_index('ix_commercial_quote_amends_agreement_id', 'commercial_quote', ['amends_agreement_id'])

    if not _has_table('commercial_agreement'):
        op.create_table(
            'commercial_agreement',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('quote_id', sa.Integer, sa.ForeignKey('commercial_quote.id'),
                      nullable=False, unique=True),
            sa.Column('revision_id', sa.Integer, sa.ForeignKey('commercial_quote_revision.id'),
                      nullable=False),
            sa.Column('response_id', sa.Integer, sa.ForeignKey('commercial_quote_response.id'),
                      nullable=False, unique=True),
            sa.Column('account_id', sa.Integer, index=True),
            sa.Column('content_hash', sa.String(64), nullable=False),
            sa.Column('effective_on', sa.Date, nullable=False),
            sa.Column('amends_agreement_id', sa.Integer,
                      sa.ForeignKey('commercial_agreement.id'), unique=True),
            sa.Column('created_at', sa.DateTime, nullable=False),
        )
    if not _has_table('commercial_quote_delivery_event'):
        op.create_table(
            'commercial_quote_delivery_event',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('delivery_id', sa.Integer,
                      sa.ForeignKey('commercial_quote_delivery.id', ondelete='CASCADE'),
                      nullable=False, index=True),
            sa.Column('event', sa.String(30), nullable=False),
            sa.Column('provider_event_id', sa.String(100), unique=True),
            sa.Column('occurred_at', sa.DateTime),
            sa.Column('detail', sa.String(400)),
            sa.Column('created_at', sa.DateTime, nullable=False),
        )
    if not _has_table('contract_audit_event'):
        op.create_table(
            'contract_audit_event',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('created_at', sa.DateTime, nullable=False, index=True),
            sa.Column('event', sa.String(40), nullable=False),
            sa.Column('quote_id', sa.Integer, index=True),
            sa.Column('revision_id', sa.Integer),
            sa.Column('agreement_id', sa.Integer, index=True),
            sa.Column('actor_kind', sa.String(20), nullable=False),
            sa.Column('actor', sa.String(200)),
            sa.Column('ip_address', sa.String(64)),
            sa.Column('request_id', sa.String(36), index=True),
            sa.Column('detail', sa.Text),
        )

    if op.get_bind().dialect.name == 'postgresql':
        import quote_evidence
        prefix = f'"{_schema()}".'
        for statement in (quote_evidence.frozen_sql(prefix, FROZEN)
                          + quote_evidence.kept_sql(prefix, KEPT)):
            op.execute(statement)


def downgrade():
    if op.get_bind().dialect.name == 'postgresql':
        for table in FROZEN:
            if _has_table(table):
                op.execute(f'DROP TRIGGER IF EXISTS {table}_frozen ON {table}')
        for table in KEPT:
            if _has_table(table):
                op.execute(f'DROP TRIGGER IF EXISTS {table}_kept ON {table}')
        op.execute('DROP FUNCTION IF EXISTS quote_evidence_kept()')
    for table in ('contract_audit_event', 'commercial_quote_delivery_event', 'commercial_agreement'):
        if _has_table(table):
            op.drop_table(table)
    if _has_column('commercial_quote', 'amends_agreement_id'):
        op.drop_index('ix_commercial_quote_amends_agreement_id', 'commercial_quote')
        op.drop_column('commercial_quote', 'amends_agreement_id')
