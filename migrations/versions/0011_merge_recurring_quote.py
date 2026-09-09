"""Rejoin the lines a third time: the CRM's recurring quote, and Akye's.

Same split as 0008 and 0009, one product later. The live Dazzle & Shine CRM
added 0008_recurring_on_quote off 0007_hold_and_promised_checklist -- one quote
carrying both the deep clean and what it costs to keep the place clean -- while
Akye had walked on to 0010_assistant_proposals.

Both lines are real. One is what the cleaning company needed with a customer on
the phone; the other is what the product needed to have an assistant that can
be trusted to act. Bringing the CRM's work across leaves two heads, and alembic
refuses to run with two, correctly: guessing would silently skip whichever it
did not pick, and here that means a company's schema being created without the
columns a quote is about to be written into.

A merge revision, for the same reason as last time. It changes no schema and
re-parents nothing, so every instance stays recorded at the revision it
actually applied and walks forward from there to one head.
"""

revision = '0011_merge_recurring_quote'
down_revision = ('0010_assistant_proposals', '0008_recurring_on_quote')
branch_labels = None
depends_on = None


def upgrade():
    """Nothing to do — the parents carry all the schema."""


def downgrade():
    """Nothing to undo."""
