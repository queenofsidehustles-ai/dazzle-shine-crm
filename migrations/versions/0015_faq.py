"""Curated answers to problems real users have already hit.

Nothing here is generated -- an entry exists because whoever solved a
problem wrote down the question and the answer that actually worked, so
the next person with the same one finds it instead of hitting support
again.
"""
import sqlalchemy as sa
from alembic import op

revision = '0015_faq'
down_revision = '0014_staff_user_link'
branch_labels = None
depends_on = None


def _current_schema():
    import sqlalchemy as _sa
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return None
    return bind.execute(_sa.text('SELECT current_schema()')).scalar()


def _has_table(name):
    from sqlalchemy import inspect as sa_inspect
    return name in sa_inspect(op.get_bind()).get_table_names(
        schema=_current_schema())


def upgrade():
    if _has_table('faq'):
        return
    op.create_table(
        'faq',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('question', sa.String(300), nullable=False),
        sa.Column('answer', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
    )


def downgrade():
    if not _has_table('faq'):
        return
    op.drop_table('faq')
