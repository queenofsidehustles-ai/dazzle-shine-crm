"""How far away a commercial customer is.

Travel used to be invisible in a commercial quote. Whatever it cost was
absorbed by the minimum-visit fee, which meant every small job was priced the
same whether it was ten minutes away or an hour — and the ones far enough away
to be losing money looked exactly like the ones that were not.

Kept on the account rather than only in Settings because a customer's distance
belongs to that customer. Quoting them again next year should not start from
the generic default and quietly drop the forty minutes somebody measured once.

Nullable, so every existing account falls back to the deployment's default
until somebody sets a real number.

Revision ID: 0007_commercial_drive_time
Revises: 0006_time_entries
"""
import sqlalchemy as sa
from alembic import op

revision = '0007_commercial_drive_time'
down_revision = '0006_time_entries'
branch_labels = None
depends_on = None


def upgrade():
    cols = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('commercial_account')}
    if 'drive_minutes' not in cols:
        op.add_column('commercial_account',
                      sa.Column('drive_minutes', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('commercial_account', 'drive_minutes')
