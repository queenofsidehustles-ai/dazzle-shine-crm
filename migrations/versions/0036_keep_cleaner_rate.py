"""Existing companies keep the $43 cleaner rate they have been paying.

The starting cleaner rate (pricing.LABOR_RATE_DEFAULT) moved from $43 to $25
an hour: $25 is what a cleaner costs, and $43 read like a price. A company that
never saved its own rate on Settings -> Pricing has been paying the default,
so lowering it would cut every one of its cleaners' pay without anybody
deciding to. This writes $43 down for them first, so only a company created
from now on starts at $25.

"Existing" means the schema already has somebody in it. A company being
provisioned runs every migration on empty tables -- its owner is added after
-- so it is left alone and starts at the new default. A rate somebody saved
is never touched.
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = '0036_keep_cleaner_rate'
down_revision = '0035_commercial_jobs'
branch_labels = None
depends_on = None

OLD_DEFAULT = '43'


def upgrade():
    bind = op.get_bind()
    in_use = bind.execute(sa.text(
        'SELECT EXISTS (SELECT 1 FROM "user") OR EXISTS (SELECT 1 FROM booking)')).scalar()
    if not in_use:
        return
    saved = bind.execute(sa.text(
        "SELECT 1 FROM pricing_setting WHERE key = 'labor_rate'")).first()
    if saved:
        return
    bind.execute(sa.text(
        "INSERT INTO pricing_setting (key, value, updated_at) VALUES ('labor_rate', :v, :t)"),
        {'v': OLD_DEFAULT, 't': datetime.utcnow()})


def downgrade():
    # Which $43 rows this wrote and which an owner saved cannot be told apart,
    # and either way $43 is what that company was paying before.
    pass
