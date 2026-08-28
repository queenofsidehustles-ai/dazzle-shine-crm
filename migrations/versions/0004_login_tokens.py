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


def _has_table(name):
    from sqlalchemy import inspect as sa_inspect
    return name in sa_inspect(op.get_bind()).get_table_names()


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
