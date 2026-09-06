"""A job can be put on hold, and a booking remembers what it was promised.

Two unrelated columns, one migration, because they arrived in the same
conversation and splitting them would mean two deploys for one afternoon's work.

**held_at / hold_note.** A customer rings an hour after booking and needs to
move the cleaning, without a new date in mind. There was nowhere to put that.
Cancelling severs the deposit from the work and reads to everyone as a customer
who went away; leaving it confirmed means the morning-of cron charges her card
for a cleaning nobody is going to do, and texts a cleaner to a house where she
is not expected. So holding is a status of its own — every automation already
selects on an explicit list of statuses, and none of them contain it — and these
record when it started and what she was told, so a deposit cannot sit in limbo
unnoticed.

**promised_checklist.** A quote's checklist can have lines taken off it. Without
carrying that onto the booking, the confirmation email rebuilds the list from
the service default and re-promises the very thing the customer was told would
not be done.

All three are additive and nullable. NULL on promised_checklist means "whatever
the service checklist says", which is right for every booking that did not come
through a quote.
"""
from alembic import op
import sqlalchemy as sa

revision = '0007_hold_and_promised_checklist'
down_revision = '0006_amount_collected'
branch_labels = None
depends_on = None

COLUMNS = (
    ('held_at', sa.DateTime()),
    ('hold_note', sa.String(200)),
    ('promised_checklist', sa.Text()),
)


def _has_column(table, column):
    """Whether the column is already there. See 0003 — these databases were
    built by a year of self-swallowing ALTER TABLE statements."""
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    return column in {c['name'] for c in sa_inspect(bind).get_columns(table)}


def upgrade():
    for name, type_ in COLUMNS:
        if not _has_column('booking', name):
            op.add_column('booking', sa.Column(name, type_, nullable=True))


def downgrade():
    for name, _ in COLUMNS:
        if _has_column('booking', name):
            op.drop_column('booking', name)
