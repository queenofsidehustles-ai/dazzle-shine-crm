"""Short-term rental properties and the turnovers their calendars produce.

A host hands over the iCal link Airbnb publishes for a listing. We read it,
and every check-out becomes a cleaning job on that date.

Two tables rather than one. `rental_property` is the standing thing — the
listing, its feed, who it belongs to. `rental_turnover` is one row per booking
we have already turned into a job, keyed on the UID the calendar gives us, so
re-reading the same feed every hour never creates the same clean twice. That
key is the whole reliability story: a duplicated turnover is an argument with a
customer, and a missed one is a guest walking into a dirty flat.

Both nullable and additive. A company that never adds a property has two empty
tables and notices nothing.
"""
from alembic import op
import sqlalchemy as sa

revision = '0019_rental_turnovers'
down_revision = '0018_deposit_method'
branch_labels = None
depends_on = None


def _has_table(name):
    from sqlalchemy import inspect as sa_inspect
    return name in set(sa_inspect(op.get_bind()).get_table_names())


def upgrade():
    if not _has_table('rental_property'):
        op.create_table(
            'rental_property',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('client_id', sa.Integer, sa.ForeignKey('client.id'), nullable=True),
            sa.Column('name', sa.String(120), nullable=False),
            sa.Column('address', sa.String(200)),
            sa.Column('city', sa.String(80)),
            sa.Column('zip_code', sa.String(10)),
            sa.Column('ical_url', sa.String(600), nullable=False),
            sa.Column('service_type', sa.String(50)),
            sa.Column('price', sa.Numeric(10, 2)),
            sa.Column('clean_time', sa.String(20)),
            sa.Column('is_active', sa.Boolean, server_default=sa.true()),
            sa.Column('last_synced_at', sa.DateTime),
            sa.Column('last_error', sa.String(300)),
            sa.Column('created_at', sa.DateTime),
        )
    if not _has_table('rental_turnover'):
        op.create_table(
            'rental_turnover',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('property_id', sa.Integer,
                      sa.ForeignKey('rental_property.id'), nullable=False),
            # The calendar's own id for the stay. One job per uid per checkout,
            # forever — this is what stops an hourly sync duplicating work.
            sa.Column('uid', sa.String(300), nullable=False),
            sa.Column('checkout_on', sa.String(10), nullable=False),
            sa.Column('next_checkin_on', sa.String(10)),
            sa.Column('same_day', sa.Boolean, server_default=sa.false()),
            sa.Column('booking_id', sa.Integer, sa.ForeignKey('booking.id')),
            sa.Column('created_at', sa.DateTime),
        )
        op.create_index('ix_rental_turnover_uid', 'rental_turnover',
                        ['property_id', 'uid', 'checkout_on'], unique=True)


def downgrade():
    op.drop_table('rental_turnover')
    op.drop_table('rental_property')
