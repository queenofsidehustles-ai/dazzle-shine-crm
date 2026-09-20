"""Optional TOTP two-factor authentication for a User login.

Opt-in, per account, no role required -- enabling it is a choice each person
makes for their own login, not something turned on for everyone at once.

totp_secret and totp_backup_codes are only ever populated once a person has
actually gone through setup (auth.py never reads or writes them for an
account with totp_enabled False), so this is additive and every existing
login is unaffected until its owner chooses to turn it on.
"""
from alembic import op
import sqlalchemy as sa

revision = '0013_user_totp'
down_revision = '0012_company_applicants'
branch_labels = None
depends_on = None


def _has_column(table, column):
    from sqlalchemy import inspect as sa_inspect
    import sqlalchemy as _sa
    bind = op.get_bind()
    schema = None
    if bind.dialect.name == 'postgresql':
        schema = bind.execute(_sa.text('SELECT current_schema()')).scalar()
    return column in {c['name']
                      for c in sa_inspect(bind).get_columns(table, schema=schema)}


def upgrade():
    if not _has_column('user', 'totp_secret'):
        op.add_column('user', sa.Column('totp_secret', sa.String(64), nullable=True))
    if not _has_column('user', 'totp_enabled'):
        op.add_column('user', sa.Column(
            'totp_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    if not _has_column('user', 'totp_backup_codes'):
        op.add_column('user', sa.Column('totp_backup_codes', sa.Text(), nullable=True))


def downgrade():
    if _has_column('user', 'totp_backup_codes'):
        op.drop_column('user', 'totp_backup_codes')
    if _has_column('user', 'totp_enabled'):
        op.drop_column('user', 'totp_enabled')
    if _has_column('user', 'totp_secret'):
        op.drop_column('user', 'totp_secret')
