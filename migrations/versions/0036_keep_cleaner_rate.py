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
from alembic import op

revision = '0036_keep_cleaner_rate'
down_revision = '0035_commercial_jobs'
branch_labels = None
depends_on = None


def upgrade():
    # The rule lives with the rate (pricing.keep_old_rate) because restoring a
    # backup taken before this migration has to apply it too: a restore builds
    # today's tables and is stamped at head, so this never runs on that data.
    import pricing
    pricing.keep_old_rate(op.get_bind())


def downgrade():
    # Which $43 rows this wrote and which an owner saved cannot be told apart,
    # and either way $43 is what that company was paying before.
    pass
