"""Whether a work-area quote carries a one-time first-visit premium.

A new contract's first clean is almost always slower than every visit after
it -- years of buildup, nobody's set the pace yet, the scope gets found out
rather than known. One nullable boolean: whether the quote's first visit
carries commercial_pricing.area_quote()'s first-visit premium, priced as its
own one-time line and never folded into the recurring per-visit or monthly
figures. Every quote on file reads NULL/false: no premium, which is the
behavior before this existed.
"""
from alembic import op
import sqlalchemy as sa

revision = '0027_quote_first_visit_premium'
down_revision = '0026_feature_seen'
branch_labels = None
depends_on = None


def _has_column(table, column):
    """In the schema being migrated -- see 0021 for why."""
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    schema = None
    if bind.dialect.name == 'postgresql':
        schema = bind.execute(sa.text('SELECT current_schema()')).scalar()
    return column in {c['name']
                      for c in sa_inspect(bind).get_columns(table, schema=schema)}


def upgrade():
    if not _has_column('commercial_quote', 'first_visit_premium'):
        op.add_column('commercial_quote',
                      sa.Column('first_visit_premium', sa.Boolean(), nullable=True))


def downgrade():
    if _has_column('commercial_quote', 'first_visit_premium'):
        op.drop_column('commercial_quote', 'first_visit_premium')
