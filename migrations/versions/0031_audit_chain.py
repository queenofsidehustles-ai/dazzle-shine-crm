"""The audit trail as a hash chain.

contract_audit_event (0030) refuses UPDATE and DELETE -- but the database's
owner can switch those triggers off. This makes such an edit show: each row
gets its place in the chain (chain_seq), the hash of the row before it
(prev_hash) and its own hash over its contents and that predecessor
(row_hash), computed by the database on insert under a per-schema lock. A row
changed afterwards no longer matches its hash, and the next row names the
wrong predecessor. The nightly backup writes each company's chain head into its
manifest, outside the database (backup.py); certify.py checks both.

Rows written before this are chained here, oldest first: the frozen trigger is
switched off for exactly that UPDATE, inside this migration's transaction, and
on again before it commits. Nothing but the three new columns is touched.
Postgres only; on SQLite the columns exist and stay empty.
"""
from alembic import op
import sqlalchemy as sa

revision = '0031_audit_chain'
down_revision = '0030_contract_trail'
branch_labels = None
depends_on = None


def _schema():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return None
    return bind.execute(sa.text('SELECT current_schema()')).scalar()


def _has_column(table, column):
    from sqlalchemy import inspect as sa_inspect
    return column in {c['name']
                      for c in sa_inspect(op.get_bind()).get_columns(table, schema=_schema())}


def upgrade():
    if not _has_column('contract_audit_event', 'chain_seq'):
        op.add_column('contract_audit_event', sa.Column('chain_seq', sa.BigInteger(), nullable=True))
        op.add_column('contract_audit_event', sa.Column('prev_hash', sa.String(64), nullable=True))
        op.add_column('contract_audit_event', sa.Column('row_hash', sa.String(64), nullable=True))
    if op.get_bind().dialect.name == 'postgresql':
        import quote_evidence
        prefix = f'"{_schema()}".'
        for statement in (quote_evidence.audit_chain_sql(prefix)
                          + quote_evidence.audit_backfill_sql(prefix)):
            op.execute(statement)


def downgrade():
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('DROP TRIGGER IF EXISTS contract_audit_event_chain ON contract_audit_event')
        op.execute('DROP FUNCTION IF EXISTS contract_audit_chain()')
        op.execute('DROP INDEX IF EXISTS uq_contract_audit_event_chain_seq')
    for column in ('row_hash', 'prev_hash', 'chain_seq'):
        if _has_column('contract_audit_event', column):
            op.drop_column('contract_audit_event', column)
