"""Say whether an office or sales login is an employee or a contractor.

A cleaner's Staff row already carries this (worker_model). Office admins,
dispatchers and business-development people are logins, not Staff, and they
can be either; an employee and a contractor are paid and papered differently.
One nullable column on user. Every login already on file reads NULL, which
means "not recorded", and nothing treats NULL as either.
"""
from alembic import op
import sqlalchemy as sa

revision = '0041_user_worker_model'
down_revision = '0040_booking_send_guard'
branch_labels = None
depends_on = None


def _has_column(table, column):
    """In the schema being migrated; see 0034_booking_repeat_of."""
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    schema = None
    if bind.dialect.name == 'postgresql':
        schema = bind.execute(sa.text('SELECT current_schema()')).scalar()
    return column in {c['name']
                      for c in sa_inspect(bind).get_columns(table, schema=schema)}


def upgrade():
    if not _has_column('user', 'worker_model'):
        op.add_column('user', sa.Column('worker_model', sa.String(20), nullable=True))


def downgrade():
    if _has_column('user', 'worker_model'):
        op.drop_column('user', 'worker_model')
