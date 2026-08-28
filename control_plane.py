"""The list of companies, which is the one thing that is not any one company's.

Every other table in this application belongs to a business: its bookings, its
cleaners, its money. This one sits above them all, in the `public` schema, and
answers a question that has to be answerable *before* any tenant is chosen —
"which company is acme.rollcall.com, and does it exist?"

It is deliberately a separate module and a separate metadata. models.py holds
thirty-three tables that get copied into every company's schema; putting the
organisation list in there would copy the list of all companies into each
company's own schema, which is both absurd and a leak.

Nothing here is created or read on an instance that has no organisations. The
business running today never touches it.
"""
from datetime import datetime

from sqlalchemy import (Column, DateTime, Integer, String, Boolean, MetaData,
                        Table, select, insert, update)

# Its own MetaData: these tables must never be created inside a tenant schema,
# and must never be swept up by a migration that walks models.py.
control_metadata = MetaData(schema='public')

organizations = Table(
    'organizations', control_metadata,
    Column('id', Integer, primary_key=True),
    # The subdomain, and the schema name. Immutable once issued: it is in every
    # link ever texted to a cleaner and every email sent to a customer.
    Column('slug', String(40), unique=True, nullable=False, index=True),
    Column('name', String(200), nullable=False),
    Column('schema_name', String(64), unique=True, nullable=False),
    # 'active' | 'suspended' | 'closed'. A suspended company can still be
    # resolved -- it needs to reach a page explaining why it cannot get in --
    # so this is checked after resolution, never instead of it.
    Column('status', String(20), default='active', nullable=False),
    Column('owner_email', String(200)),
    Column('created_at', DateTime, default=datetime.utcnow),
    Column('provisioned_at', DateTime),
    Column('suspended_at', DateTime),

    # ── Billing ────────────────────────────────────────────────────────────
    # Deliberately here and not in the company's own schema. A business must
    # not be able to edit the record of what it is paying, and anything inside
    # its schema is reachable by its own CRM. This is also the one thing that
    # has to be readable before a tenant is resolved, to decide whether they
    # get in at all.
    Column('plan', String(20), default='solo', nullable=False),
    # What Stripe last told us, verbatim: trialing, active, past_due, canceled,
    # unpaid, incomplete. Never inferred from a browser redirect -- see
    # billing.py for why that distinction is the whole thing.
    Column('subscription_status', String(30), default='trialing'),
    Column('stripe_customer_id', String(64), index=True),
    Column('stripe_subscription_id', String(64), index=True),
    Column('trial_ends_at', DateTime),
    Column('current_period_end', DateTime),
    # A founding customer's price is theirs for as long as they stay. This
    # survives every future price change, which is the whole promise.
    Column('grandfathered', Boolean, default=False),
)


def ensure_table(engine):
    """Create the control-plane table if it is not there. Safe to call always."""
    control_metadata.create_all(engine, tables=[organizations])


def all_orgs(engine):
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(
            select(organizations).order_by(organizations.c.slug)).mappings()]


def find(engine, slug):
    with engine.connect() as conn:
        row = conn.execute(
            select(organizations).where(organizations.c.slug == slug)
        ).mappings().first()
        return dict(row) if row else None


def create(engine, slug, name, owner_email=None):
    import tenancy
    if not tenancy.valid_slug(slug):
        raise ValueError(
            f'{slug!r} is not a usable address. Lower-case letters, numbers and '
            f'hyphens, 3-40 characters, and not one of the reserved names.')
    if find(engine, slug):
        raise ValueError(f'{slug!r} is already taken.')
    with engine.begin() as conn:
        conn.execute(insert(organizations).values(
            slug=slug, name=name, schema_name=tenancy.schema_for(slug),
            owner_email=owner_email, status='active',
            created_at=datetime.utcnow()))
    return find(engine, slug)


def mark_provisioned(engine, slug):
    with engine.begin() as conn:
        conn.execute(update(organizations)
                     .where(organizations.c.slug == slug)
                     .values(provisioned_at=datetime.utcnow()))


def set_status(engine, slug, status):
    values = {'status': status}
    if status == 'suspended':
        values['suspended_at'] = datetime.utcnow()
    with engine.begin() as conn:
        conn.execute(update(organizations)
                     .where(organizations.c.slug == slug).values(**values))


def set_billing(engine, slug, **fields):
    """Record what Stripe told us. Only ever called from a verified webhook."""
    allowed = {'plan', 'subscription_status', 'stripe_customer_id',
               'stripe_subscription_id', 'trial_ends_at', 'current_period_end',
               'grandfathered', 'status'}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f'not billing fields: {sorted(bad)}')
    with engine.begin() as conn:
        conn.execute(update(organizations)
                     .where(organizations.c.slug == slug).values(**fields))
    return find(engine, slug)


def find_by_customer(engine, stripe_customer_id):
    """Which company a Stripe customer belongs to. The webhook's only handle."""
    with engine.connect() as conn:
        row = conn.execute(
            select(organizations).where(
                organizations.c.stripe_customer_id == stripe_customer_id)
        ).mappings().first()
        return dict(row) if row else None
