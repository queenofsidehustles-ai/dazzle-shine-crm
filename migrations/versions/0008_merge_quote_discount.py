"""Rejoin the two migration lines: the product's, and the live business's.

Two things were being built at once and both added migrations off
0003_deposit_amount_paid. The Akye/tenancy work went 0004_login_tokens →
0005 → 0006 → 0007_commercial_drive_time. The live Dazzle & Shine CRM took a
hotfix line and added 0004_quote_discount. Neither is wrong; they are the same
schema described from two directions.

Alembic calls that branching, and it refuses to run with two heads rather than
guessing which is "the" latest — correctly, because guessing would silently skip
whichever it did not pick. On this branch it showed up as every tenancy test
dying at "Multiple head revisions are present", including signup, which creates
a company's schema by running migrations.

This is a merge revision: no schema of its own, two parents, one head. It is
deliberately NOT a re-parenting of 0004_quote_discount onto 0007. That would
change the recorded ancestry of a revision the production database has already
applied, and alembic stores only which revision an instance is at, not how it
got there — so production would sit at 0004_quote_discount with 0004_login_tokens
through 0007 behind it in the chain and never applied. Merging leaves every
applied revision exactly where it is and lets each instance walk from wherever
it actually stands to the single new head.
"""

revision = '0008_merge_quote_discount'
down_revision = ('0007_commercial_drive_time', '0004_quote_discount')
branch_labels = None
depends_on = None


def upgrade():
    """Nothing to do — the parents carry all the schema."""


def downgrade():
    """Nothing to undo; splitting the heads again is not something to automate."""
