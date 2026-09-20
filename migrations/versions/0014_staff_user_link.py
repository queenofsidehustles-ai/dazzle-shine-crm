"""Link a Staff record to the User login that belongs to it.

Staff (the contractor profile -- pay, job assignment, /my-day) and User (a
CRM login) have been separate, unlinked tables since Team Logins existed:
an owner could create a login for someone with no connection back to their
Staff card, and vice versa (see JOURNEY-01's Journey #12 caveat). The
Migration Toolbox's bulk team import is the first thing that actually needs
this link -- it creates the Staff record, then invites the person to create
their own login, and has to know which login belongs to which Staff card.

Nullable and additive: every Staff record created before this stays
unlinked, exactly as it always was, until someone deliberately connects one.
"""
from alembic import op
import sqlalchemy as sa

revision = '0014_staff_user_link'
down_revision = '0013_user_totp'
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


FK_NAME = 'fk_staff_user_id_user'


def upgrade():
    if not _has_column('staff', 'user_id'):
        op.add_column('staff', sa.Column('user_id', sa.Integer(), nullable=True))
        op.create_foreign_key(FK_NAME, 'staff', 'user', ['user_id'], ['id'])


def downgrade():
    if _has_column('staff', 'user_id'):
        try:
            op.drop_constraint(FK_NAME, 'staff', type_='foreignkey')
        except Exception:
            pass
        op.drop_column('staff', 'user_id')
