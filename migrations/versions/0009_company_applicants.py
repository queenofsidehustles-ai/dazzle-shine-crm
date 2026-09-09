"""A cleaning company applying is a vendor, not a hire.

The application asked how many years somebody had been cleaning, whether they
had their own transport and their own supplies, and auto-rejected anybody who
answered wrong. Every one of those is the right question for a person and the
wrong one for a company with its own LLC, its own crew and its own van --
which is who has actually been applying.

What a company needs instead is paperwork with dates on it: a tax number, a
certificate of general liability, workers' compensation or a state exemption,
a business licence, a W-9. The dates are the point. A certificate collected in
March and never looked at again is worse than none, because by then you
believe you are covered.

All additive and nullable, so every application already in the table stays an
individual and reads exactly as it did.

Numbered for this line rather than the product's. The same change is
0012 on Akye, which has walked further; a revision id only has to be
unique and correctly parented within the line it runs on, and the next
merge revision joins the two as the three before it did.
"""
import sqlalchemy as sa
from alembic import op

revision = '0009_company_applicants'
down_revision = '0008_recurring_on_quote'
branch_labels = None
depends_on = None

COLUMNS = [
    ('applicant_kind', sa.String(20)),
    ('company_name', sa.String(200)),
    ('ein', sa.String(20)),
    ('crew_size', sa.String(20)),
    ('service_areas', sa.String(300)),
    ('has_liability_insurance', sa.Boolean()),
    ('insurance_carrier', sa.String(120)),
    ('insurance_expires', sa.String(10)),
    ('workers_comp', sa.String(20)),
    ('workers_comp_expires', sa.String(10)),
    ('business_license', sa.String(120)),
    ('w9_received', sa.Boolean()),
    ('crew_checks_agreed', sa.Boolean()),
]


def _current_schema():
    """The schema this is running in, or None on SQLite.

    Same shape as 0004 and 0005: SQLite has no schemas, and asking it for
    current_schema() raises rather than returning nothing.
    """
    import sqlalchemy as _sa
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return None
    return bind.execute(_sa.text('SELECT current_schema()')).scalar()


def _have():
    from sqlalchemy import inspect as sa_inspect
    try:
        return {c['name'] for c in sa_inspect(op.get_bind()).get_columns(
            'contractor_application', schema=_current_schema())}
    except Exception:
        return set()


def upgrade():
    # A database built straight from the models already has these, and adding
    # a column twice is what stops such an install migrating forward.
    have = _have()
    for name, kind in COLUMNS:
        if name not in have:
            op.add_column('contractor_application', sa.Column(name, kind))


def downgrade():
    have = _have()
    for name, _kind in reversed(COLUMNS):
        if name in have:
            op.drop_column('contractor_application', name)
