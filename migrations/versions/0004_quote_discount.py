"""A quote can show a discount instead of just a smaller number.

Quoting somebody a friends-and-family price used to mean typing the discounted
figure into the price box. The customer was then told "$232" with nothing to say
it was ever $290 — so the discount did the business no good at all: they could
not see they had been given anything, and afterwards there was no record that
anything had been given. It also never reached the booking, so Job Economics
reported no discounting on jobs that were plainly discounted.

`quoted_price` deliberately does not change meaning: it is still what they pay,
and every existing reader of it — the quote email, the booking it becomes, the
drips — carries on unchanged. These say what the price would have been and why
it isn't.

All four are additive and nullable, so this is reversible, and a quote made
before today reads NULL rather than "a discount of zero" — which is the truth
about it: there is nothing to show, not nothing given.
"""
from alembic import op
import sqlalchemy as sa

revision = '0004_quote_discount'
down_revision = '0003_deposit_amount_paid'
branch_labels = None
depends_on = None

COLUMNS = (
    ('quote_full_price', sa.Numeric(10, 2)),
    ('discount_code',    sa.String(50)),
    ('discount_amount',  sa.Numeric(10, 2)),
    ('discount_label',   sa.String(80)),
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
