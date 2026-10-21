"""What each person has found of the product.

Help tips (help_tips.py) say what a feature is for. To point somebody at the
features they have not found -- a dot on a menu item they have never opened,
one "Did you know?" when they sign in -- the app has to know which those are,
per person: a new dispatcher has opened none of it, whatever the owner has.
One row per person per feature, written the first time anything happens to it.
Additive: an empty table means everything is unopened, which is the truth for
a company that has just upgraded to this.
"""
from alembic import op
import sqlalchemy as sa

revision = '0026_feature_seen'
down_revision = '0025_prospect_activity'
branch_labels = None
depends_on = None


def _has_table(name):
    """In the schema being migrated -- see 0019 for why."""
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    schema = None
    if bind.dialect.name == 'postgresql':
        schema = bind.execute(sa.text('SELECT current_schema()')).scalar()
    return name in set(sa_inspect(bind).get_table_names(schema=schema))


def upgrade():
    if not _has_table('feature_seen'):
        op.create_table(
            'feature_seen',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('user_key', sa.String(40), nullable=False),
            sa.Column('endpoint', sa.String(80), nullable=False),
            sa.Column('first_seen_at', sa.DateTime),
            sa.Column('tip_opened_at', sa.DateTime),
            sa.Column('suggested_at', sa.DateTime),
            sa.Column('dismissed_at', sa.DateTime),
            sa.UniqueConstraint('user_key', 'endpoint', name='uq_feature_seen_user_endpoint'),
        )


def downgrade():
    if _has_table('feature_seen'):
        op.drop_table('feature_seen')
