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
                        Table, select, insert, update, text)

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
    # When they first assigned a job to somebody. The trial's 14 days run from
    # here rather than from signup: a fortnight that starts before anybody has
    # used the product is a trial they never had.
    Column('activated_at', DateTime),
    # Which trial emails have gone to this company, comma-separated. The
    # countdown in the banner only reaches somebody who logs in, and the whole
    # reason the 30-day cap exists is the person who does not — so the nudges
    # are the half of that feature that actually leaves the building.
    #
    # Written down rather than derived, because "have we already emailed
    # them?" cannot be worked out from dates alone: a cron that runs twice, or
    # a deploy that replays a day, would send the same email again, and the
    # second copy of "9 days left" is the one that gets the sender marked as
    # spam.
    Column('nudges_sent', String(200)),
)


# Somebody who wanted the product before the door was open.
#
# Lives here rather than in models.py for the same reason `organizations`
# does: this is the product's own list, not any one cleaning company's, and
# copying it into every tenant schema would be both absurd and a leak.
product_leads = Table(
    'product_leads', control_metadata,
    Column('id', Integer, primary_key=True),
    Column('name', String(120)),
    Column('company', String(200)),
    Column('email', String(200), index=True),
    Column('phone', String(40)),
    # Roughly how many cleaners. Free text on purpose -- "3 or 4, depends" is
    # a more useful answer than a number they had to round.
    Column('cleaners', String(40)),
    Column('note', String(500)),
    # Where they came from, so the first ten can be traced back to whatever
    # actually worked.
    Column('source', String(120)),
    Column('created_at', DateTime, default=datetime.utcnow, index=True),
    Column('contacted_at', DateTime),
)


def ensure_columns(engine):
    """Add any column this code expects and the table does not have.

    `create_all` creates missing tables. It does not touch a table that
    already exists, so a column added to `organizations` after a deployment
    went live would simply never appear there — and every read of it would
    fail on the one database that matters.

    Per-company schemas have alembic for this. The control plane sits outside
    it by design, so it needs its own small version: additive only, one column
    at a time, and silent when there is nothing to do.
    """
    from sqlalchemy import inspect as sa_inspect
    try:
        have = {c['name'] for c in sa_inspect(engine).get_columns(
            'organizations', schema='public')}
    except Exception:
        return                      # table is not there yet; create_all will make it
    ddl = {
        'plan': 'VARCHAR(20)',
        'subscription_status': 'VARCHAR(30)',
        'stripe_customer_id': 'VARCHAR(80)',
        'stripe_subscription_id': 'VARCHAR(80)',
        'trial_ends_at': 'TIMESTAMP',
        'current_period_end': 'TIMESTAMP',
        'grandfathered': 'BOOLEAN',
        'activated_at': 'TIMESTAMP',
        'nudges_sent': 'VARCHAR(200)',
    }
    for name, sqltype in ddl.items():
        if name in have:
            continue
        try:
            with engine.begin() as conn:
                conn.execute(text(
                    f'ALTER TABLE public.organizations ADD COLUMN {name} {sqltype}'))
            print(f'  ✅ control plane: added organizations.{name}')
        except Exception as e:
            print(f'  ⚠️  could not add organizations.{name}: {e}')


def ensure_table(engine):
    """Create the control-plane table if it is not there. Safe to call always."""
    control_metadata.create_all(engine, tables=[organizations, product_leads])
    ensure_columns(engine)


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
    # Everything, for a fortnight — but the fortnight does not start until they
    # assign a job. Until then they have thirty days to begin, which is what
    # `trial_ends_at` holds; `billing.mark_activated` moves it when they do.
    #
    # A free plan nobody has seen the paid features from is a plan nobody
    # upgrades out of: they cannot miss the hiring pipeline if they never had
    # it. So the trial gives the top plan and then steps down, rather than
    # asking somebody to imagine what they are not being shown.
    from datetime import timedelta
    now = datetime.utcnow()
    with engine.begin() as conn:
        conn.execute(insert(organizations).values(
            slug=slug, name=name, schema_name=tenancy.schema_for(slug),
            owner_email=owner_email, status='active',
            created_at=now,
            plan='scale',
            subscription_status='trialing',
            trial_ends_at=now + timedelta(days=30),
            activated_at=None))
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
    """Record what Stripe told us, or when a trial actually began.

    The whitelist is the point: a caller that has not thought about which
    field it is writing cannot write one by accident. `activated_at` is on it
    because the trial clock starts from the product being used, which is
    something only this application knows and Stripe never will.
    """
    allowed = {'plan', 'subscription_status', 'stripe_customer_id',
               'stripe_subscription_id', 'trial_ends_at', 'current_period_end',
               'grandfathered', 'status', 'activated_at', 'nudges_sent'}
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


def add_lead(engine, **fields):
    """Record somebody who asked for early access. Never raises.

    A form that loses the person filling it in is worse than no form. If the
    table is missing or the write fails, the caller still emails the details
    on, so the lead reaches a human either way.
    """
    allowed = {'name', 'company', 'email', 'phone', 'cleaners', 'note', 'source'}
    row = {k: (v or None) for k, v in fields.items() if k in allowed}
    row['created_at'] = datetime.utcnow()
    try:
        ensure_table(engine)
        with engine.begin() as conn:
            conn.execute(insert(product_leads).values(**row))
        return True
    except Exception:
        return False


def all_leads(engine):
    """Everybody who has asked, newest first."""
    try:
        with engine.connect() as conn:
            return [dict(r) for r in conn.execute(
                select(product_leads).order_by(
                    product_leads.c.created_at.desc())).mappings()]
    except Exception:
        return []

