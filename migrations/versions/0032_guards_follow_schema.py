"""Evidence guards that keep working when a company's schema is renamed.

The ownership guard (0029) and the audit chain (0031) wrote their own schema's
name into their bodies. The demo company is built under a staging name
(tenant_<slug>__next, demo_company.py) and renamed into place, so its guards
went on naming a schema that no longer existed: every audit entry, and so
every quote, failed there. Both now find their tables through the trigger that
fired them (TG_TABLE_SCHEMA) and name no schema at all; this re-creates them
in every schema. The hash each computes is unchanged, so every chain written
so far still recomputes. Postgres only.
"""
from alembic import op
import sqlalchemy as sa

revision = '0032_guards_follow_schema'
down_revision = '0031_audit_chain'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    import quote_evidence
    prefix = f'"{bind.execute(sa.text("SELECT current_schema()")).scalar()}".'
    for statement in quote_evidence.ownership_sql(prefix) + quote_evidence.audit_chain_sql(prefix):
        op.execute(statement)


def downgrade():
    pass   # the 0031 bodies broke on rename; nothing worth putting back
