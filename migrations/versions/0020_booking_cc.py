"""Keep somebody in the loop without making them the customer.

On a post-construction job the construction company books the clean and pays
the invoice; the homeowner lives in the house and wants to know when it is
happening. There was nowhere to put the second person. The only route was to
type their address into the booking's email form, which wrote it onto
`booking.email` -- so the payer silently became the passenger, and every later
invoice, payment link and confirmation went to the wrong one of the two.

Two nullable columns, so every booking already on file reads NULL and copies
nobody, which is exactly what those bookings did yesterday.
"""
from alembic import op
import sqlalchemy as sa

revision = '0020_booking_cc'
down_revision = '0019_rental_turnovers'
branch_labels = None
depends_on = None


def _has_column(table, column):
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    return column in {c['name'] for c in sa_inspect(bind).get_columns(table)}


def upgrade():
    if not _has_column('booking', 'cc_email'):
        op.add_column('booking', sa.Column('cc_email', sa.String(120), nullable=True))
    if not _has_column('booking', 'cc_name'):
        op.add_column('booking', sa.Column('cc_name', sa.String(120), nullable=True))


def downgrade():
    if _has_column('booking', 'cc_name'):
        op.drop_column('booking', 'cc_name')
    if _has_column('booking', 'cc_email'):
        op.drop_column('booking', 'cc_email')
