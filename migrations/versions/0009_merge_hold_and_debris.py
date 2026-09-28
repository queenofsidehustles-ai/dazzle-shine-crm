"""Rejoin the lines again: the CRM's hold-and-debris work, and Akye's.

The same split as 0008, one product later. Since that merge the live Dazzle &
Shine CRM added three revisions off 0004_quote_discount — 0005_quote_debris_fee,
0006_amount_collected and 0007_hold_and_promised_checklist — while Akye stood at
0008_merge_quote_discount. Both lines are real: one is what the cleaning company
needed on a Friday, the other is what the product needed to have tenants at all.

0008 merged 0004_quote_discount as it stood then, which does not include what was
added to that line afterwards, so bringing the CRM work across left two heads
again: 0008_merge_quote_discount and 0007_hold_and_promised_checklist. Alembic
refuses to run with two, correctly — guessing would silently skip whichever it
did not pick, and on this branch that means a company's schema being created
without the columns the code expects.

A merge revision, for the same reason as last time: it changes no schema and
re-parents nothing. Every instance stays recorded at the revision it actually
applied and walks forward from there to one head. Re-pointing an existing
revision instead would rewrite ancestry that production has already been through,
and alembic stores only where a database is, not how it got there.
"""

revision = '0009_merge_hold_and_debris'
down_revision = ('0008_merge_quote_discount', '0007_hold_and_promised_checklist')
branch_labels = None
depends_on = None


def upgrade():
    """Nothing to do — the parents carry all the schema."""


def downgrade():
    """Nothing to undo; splitting the heads again is not something to automate."""
