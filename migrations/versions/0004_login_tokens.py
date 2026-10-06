"""Single-use links for signup, password reset and email confirmation.

Additive and nullable throughout, so it is reversible and so an instance that
rolls back simply stops issuing links rather than losing anything.
"""
from alembic import op
import sqlalchemy as sa

revision = '0004_login_tokens'
down_revision = '0003_deposit_amount_paid'
branch_labels = None
depends_on = None


def _current_schema():
    """The schema this migration is running inside, or None where that has no
    meaning.

    NOT the default schema, and not "is the name resolvable". With search_path
    set to "tenant_acme, public", asking whether a table exists by bare name
    finds it in public and answers yes -- so a guard written that way skips
    creating it inside the company's schema, and every company silently ends up
    missing tables that happen to exist in public.

    None on SQLite, which has no schemas and no current_schema() function.
    Asking it produces a syntax error, which is how a first attempt at this
    broke every local install: the guard raised, the migration failed, and the
    column was never added.
    """
    import sqlalchemy as _sa
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return None
    return bind.execute(_sa.text('SELECT current_schema()')).scalar()


def _has_table(name):
    from sqlalchemy import inspect as sa_inspect
    return name in sa_inspect(op.get_bind()).get_table_names(schema=_current_schema())


def upgrade():
    if _has_table('login_token'):
        return
    op.create_table(
        'login_token',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), index=True),
        # The hash, never the token. See models.LoginToken.
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True, index=True),
        sa.Column('purpose', sa.String(20), nullable=False),
        sa.Column('email', sa.String(200)),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime()),
    )


def downgrade():
    if _has_table('login_token'):
        op.drop_table('login_token')
