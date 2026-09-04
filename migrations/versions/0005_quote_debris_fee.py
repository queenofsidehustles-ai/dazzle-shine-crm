"""Construction debris removal as its own quote line, and floor area on a lead.

Post-construction jobs are sold in three sizes, and the largest one includes
hauling the builder's leftover debris, packaging and jobsite trash away. What
that costs is dump fees plus loads — it swings by hundreds between a tidy
remodel and a gut job, and no multiplier off bedroom count can tell those apart.
Folded into the service price it is a loss absorbed silently; on its own line it
is a number she can set per job and the customer can see.

`quoted_price` does not change meaning: it is still what they pay, haul-off
included. These two say how much of it was disposal and what that disposal
covered.

Both are additive and nullable, so this is reversible, and a quote made before
today reads NULL rather than "a haul-off charged at zero" — the first is true of
those quotes and the second would be a claim about them.

`sqft` comes along for the same reason it matters most on these jobs: bedroom
count describes a house somebody lives in, not a building site, and two three-bed
jobs can differ by a thousand square feet of floor that has to be vacuumed twice.
Booking has had this column since the beginning and pricing has always known how
to charge for it — a phone quote simply had nowhere to put the number, so the
surcharge never got applied. NULL means it was not asked, which is what every
quote before today can honestly say.
"""
from alembic import op
import sqlalchemy as sa

revision = '0005_quote_debris_fee'
down_revision = '0004_quote_discount'
branch_labels = None
depends_on = None

COLUMNS = (
    ('debris_fee',  sa.Numeric(10, 2)),
    ('debris_note', sa.String(120)),
    ('sqft',        sa.Integer()),
)


def _existing(table):
    """What the table actually has right now.

    Migrations are being adopted onto databases whose history nobody recorded,
    so what any given instance carries is a question rather than a fact. A
    migration that assumes and is wrong stops a business from booting."""
    from sqlalchemy import inspect as sa_inspect
    return {c['name'] for c in sa_inspect(op.get_bind()).get_columns(table)}


def upgrade():
    have = _existing('lead')
    for name, type_ in COLUMNS:
        if name not in have:
            op.add_column('lead', sa.Column(name, type_, nullable=True))


def downgrade():
    have = _existing('lead')
    for name, _type in COLUMNS:
        if name in have:
            op.drop_column('lead', name)
