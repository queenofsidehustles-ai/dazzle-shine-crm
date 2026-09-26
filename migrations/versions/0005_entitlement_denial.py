"""Record of somebody wanting something their plan does not include.

The model arrived with the plan work and was only ever created by
create_all(), which is enough on an instance that boots the application against
its own database and nothing else. A company's schema is built from the
migrations alone, so without this every company would be missing the table --
and the first padlock anybody hit would be an error instead of an upsell.
"""
from alembic import op
import sqlalchemy as sa

revision = '0005_entitlement_denial'
down_revision = '0004_login_tokens'
branch_labels = None
depends_on = None


def _current_schema():
    """The schema being built, or None where that has no meaning (SQLite)."""
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return None
    return bind.execute(sa.text('SELECT current_schema()')).scalar()


def _has_table(name):
    from sqlalchemy import inspect as sa_inspect
    return name in sa_inspect(op.get_bind()).get_table_names(
        schema=_current_schema())


def upgrade():
    if _has_table('entitlement_denial'):
        return
    op.create_table(
        'entitlement_denial',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('feature', sa.String(60), index=True),
        sa.Column('plan', sa.String(20)),
        sa.Column('path', sa.String(200)),
        sa.Column('created_at', sa.DateTime(), index=True),
    )


def downgrade():
    if _has_table('entitlement_denial'):
        op.drop_table('entitlement_denial')
