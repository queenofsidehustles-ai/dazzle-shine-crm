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
                        LargeBinary, Text, UniqueConstraint,
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

    # ── Lifecycle ──────────────────────────────────────────────────────────
    # Owned by tenant_data_lifecycle.py, declared here for the same reason the
    # billing columns above are: this is the one Table object every reader of
    # `organizations` — including create_all() on a fresh database and
    # backup.py's restore, which inserts through this object's declared
    # columns rather than the live database's actual ones — has to agree with.
    # tenant_data_lifecycle.ensure_columns() remains the ALTER TABLE backfill
    # for a database that already has this table without them.
    Column('closed_at', DateTime),
    Column('purged_at', DateTime),
    # ── Revenue ────────────────────────────────────────────────────────────
    # What Stripe says this company actually pays, written by the webhook
    # (billing.apply_event) so the console can add up money without calling
    # Stripe on every page view. mrr_cents is monthly and net of any
    # recurring discount; it is kept after a cancellation, because "what did
    # we lose" is asked about the companies that left.
    Column('mrr_cents', Integer),
    Column('paid_since', DateTime),
    Column('canceled_at', DateTime),
    Column('discount_code', String(64)),
    # Set from the console for companies made to try the product out. Left
    # out of every funnel and sales count and never sent trial reminders; a
    # suspension says nothing about whether an account was real.
    Column('is_test', Boolean),
    # ── Where they came from ───────────────────────────────────────────────
    # Written once at signup from the link that first brought the owner to
    # the site (see attribution.py): the tracking tags on it, the site they
    # arrived from when there were none, and the company that referred them.
    # referred_by is a company address, kept only if that company exists.
    Column('signup_source', String(120)),
    Column('signup_medium', String(120)),
    Column('signup_campaign', String(120)),
    Column('signup_referrer', String(120)),
    Column('signup_landing', String(120)),
    Column('referred_by', String(40), index=True),
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


# Discount codes for Akye's own subscriptions -- not a cleaning company's
# codes for its customers, which live in each tenant (models.DiscountCode).
#
# Stripe is the authority: each row is a Stripe coupon plus the promotion code
# a customer types at checkout (billing.checkout_session allows them). This
# table is the console's record of what was made, by whom, and why, and the
# map from Stripe's ids back to the code a person would recognise.
promo_codes = Table(
    'promo_codes', control_metadata,
    Column('id', Integer, primary_key=True),
    Column('code', String(40), unique=True, nullable=False),
    Column('percent_off', Integer),
    Column('amount_off_cents', Integer),
    Column('duration', String(20), nullable=False),     # once | repeating | forever
    Column('duration_months', Integer),
    Column('max_redemptions', Integer),
    Column('expires_at', DateTime),
    Column('note', String(300)),
    Column('stripe_coupon_id', String(64)),
    Column('stripe_promotion_id', String(64), index=True),
    Column('active', Boolean, default=True),
    Column('created_by', String(200)),
    Column('created_at', DateTime, default=datetime.utcnow),
)


# Beta feedback, from any page of any company's CRM.
#
# In the control plane rather than in a tenant schema, for one reason: the
# whole point is to read it in one place. Feedback filed inside each company's
# own database would mean logging into every company to find out what the beta
# said, which is how feedback stops being read.
feedback = Table(
    'feedback', control_metadata,
    Column('id', Integer, primary_key=True),
    Column('org_slug', String(80), index=True),
    Column('user_name', String(120)),
    Column('user_role', String(30)),
    # What they wrote or said. `kind` is their own label for it, so a bug and
    # a wish can be told apart without reading all of them.
    Column('kind', String(20), default='issue'),
    Column('body', Text),
    # Where they were and what they were running, captured rather than asked
    # for. "It broke" from somebody who cannot remember which page is the most
    # common and least useful thing a beta tester sends.
    Column('page', String(300)),
    Column('endpoint', String(120)),
    Column('release', String(60)),
    Column('user_agent', String(300)),
    Column('viewport', String(20)),
    # The screenshot, in the row. Railway's filesystem does not survive a
    # deploy and there is no object store configured, so a handful of
    # downscaled JPEGs in Postgres is the honest option at beta size. The
    # client shrinks them before they are sent; see the widget.
    Column('shot', LargeBinary),
    Column('shot_type', String(40)),
    Column('created_at', DateTime, default=datetime.utcnow, index=True),
    Column('read_at', DateTime),
)


# Who can see across every company: you, and whoever you bring in.
#
# Its own accounts, separate from any company's owner login, because this is a
# different job with a different blast radius. A cleaning company's owner can
# see their own business; somebody here can see all of them, so the two must
# never be the same credential.
console_users = Table(
    'console_users', control_metadata,
    Column('id', Integer, primary_key=True),
    Column('email', String(200), unique=True, index=True),
    Column('name', String(120)),
    Column('password_hash', String(255)),
    # owner > manager > helper, and the rule is the same everywhere: you can
    # only act on somebody below you. Never beside you, never above you.
    #
    # That is what makes a second full-time pair of hands safe. A manager does
    # nearly everything -- reads and triages every report, sees every company,
    # brings in and removes helpers -- and cannot touch the owner or another
    # manager. Only the owner appoints a manager, and nobody can switch the
    # owner off through the console at all.
    Column('role', String(20), default='helper'),
    Column('active', Boolean, default=True),
    Column('created_at', DateTime, default=datetime.utcnow),
    Column('last_login_at', DateTime),
    # Wrong passwords in a row, and when to stop refusing. A console that can
    # see every company's data is worth guessing at, and nothing here rate
    # limited anything before.
    Column('failed', Integer, default=0),
    Column('locked_until', DateTime),
)


# What was done in the console, and by whom.
#
# One person needs no record. Two people need one immediately: "who marked
# that done" and "who switched that off" are the first questions asked the
# moment access is shared, and a system that only keeps the outcome cannot
# answer either.
console_log = Table(
    'console_log', control_metadata,
    Column('id', Integer, primary_key=True),
    Column('actor', String(200), index=True),
    Column('action', String(40)),
    Column('target', String(200)),
    Column('detail', String(400)),
    Column('created_at', DateTime, default=datetime.utcnow, index=True),
)


# Which tenant(s) a given login belongs to. A tenant's own User table can only
# ever answer "does this email exist here" for the one company whose schema is
# already selected -- which is no help to a returning visitor who landed on
# the product's root domain rather than their own subdomain, since nothing has
# picked a schema yet. This is a plain index, not a credential store: it
# exists to route someone to the right login page, not to authenticate them --
# the actual password check still happens on that tenant's own login route,
# same as always. One email can appear more than once here (the same person
# signed up for more than one company), which is why this is a lookup table
# and not a column on organizations.
tenant_logins = Table(
    'tenant_logins', control_metadata,
    Column('id', Integer, primary_key=True),
    Column('email', String(200), nullable=False, index=True),
    Column('tenant_slug', String(40), nullable=False, index=True),
    Column('created_at', DateTime, default=datetime.utcnow),
    UniqueConstraint('email', 'tenant_slug', name='uq_tenant_login_email_slug'),
)


# One row per "find my company" email lookup, purely to throttle it -- the
# same address cannot be asked for repeatedly, the same reason the reset-
# password form is throttled (see blueprints/account.py). Without this, the
# root-domain lookup form is a way to fill a stranger's inbox from a page
# that requires no login.
login_lookup_requests = Table(
    'login_lookup_requests', control_metadata,
    Column('id', Integer, primary_key=True),
    Column('email', String(200), nullable=False, index=True),
    Column('created_at', DateTime, default=datetime.utcnow),
)


# Questions from the public site -- people who are not customers yet and have
# no account to file feedback from.
support_requests = Table(
    'support_requests', control_metadata,
    Column('id', Integer, primary_key=True),
    Column('name', String(120)),
    Column('email', String(200), index=True),
    Column('body', Text),
    Column('page', String(300)),
    Column('user_agent', String(300)),
    Column('created_at', DateTime, default=datetime.utcnow, index=True),
    Column('answered_at', DateTime),
)


# Reference material that is the product's own, not any one company's -- a
# growth plan, a launch runbook, anything that used to live as a link pasted
# into somebody's inbox and should survive the person who pasted it there.
# Plain text, rendered pre-wrapped, the same choice `SOP.content` already
# made: one more markdown renderer to keep secure is not worth it for a page
# only the people already inside the console ever see.
console_docs = Table(
    'console_docs', control_metadata,
    Column('id', Integer, primary_key=True),
    Column('title', String(200), nullable=False),
    Column('content', Text, nullable=False),
    Column('created_by', String(200)),
    Column('sort_order', Integer, default=0),
    Column('created_at', DateTime, default=datetime.utcnow),
    Column('updated_at', DateTime, default=datetime.utcnow, onupdate=datetime.utcnow),
)


def ensure_columns(engine):
    """Add any column this Table object declares that the live table does not have.

    `create_all` creates missing tables. It does not touch a table that
    already exists, so a column added to `organizations` after a deployment
    went live would simply never appear there — and every read of it would
    fail on the one database that matters.

    Per-company schemas have alembic for this. The control plane sits outside
    it by design, so it needs its own small version: additive only, one column
    at a time, and silent when there is nothing to do.

    Derived from `organizations`'s own declared columns rather than a
    separately hand-maintained list — a hand-maintained list is exactly how
    `suspended_at`, `closed_at` and `purged_at` were each independently
    missed here before, one at a time, as the Table object grew and this
    function did not.
    """
    from sqlalchemy import inspect as sa_inspect
    try:
        have = {c['name'] for c in sa_inspect(engine).get_columns(
            'organizations', schema='public')}
    except Exception:
        return                      # table is not there yet; create_all will make it
    for column in organizations.columns:
        if column.name == 'id' or column.name in have:
            continue
        # Deliberately just the type: no NOT NULL, UNIQUE or DEFAULT here even
        # when the column declares them. This runs against a table that may
        # already hold rows, and retrofitting a constraint onto existing data
        # is a different, non-additive operation this function must not do
        # silently at boot.
        sqltype = column.type.compile(dialect=engine.dialect)
        try:
            with engine.begin() as conn:
                conn.execute(text(
                    f'ALTER TABLE public.organizations ADD COLUMN {column.name} {sqltype}'))
            print(f'  ✅ control plane: added organizations.{column.name}')
        except Exception as e:
            print(f'  ⚠️  could not add organizations.{column.name}: {e}')


def ensure_table(engine):
    """Create the control-plane table if it is not there. Safe to call always."""
    control_metadata.create_all(
        engine, tables=[organizations, product_leads, feedback,
                        console_users, support_requests, console_log,
                        tenant_logins, login_lookup_requests, console_docs,
                        promo_codes])
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


def create(engine, slug, name, owner_email=None, attribution=None):
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
    came_from = _signup_attribution(engine, slug, attribution)
    with engine.begin() as conn:
        conn.execute(insert(organizations).values(
            slug=slug, name=name, schema_name=tenancy.schema_for(slug),
            owner_email=owner_email, status='active',
            created_at=now,
            plan='scale',
            subscription_status='trialing',
            trial_ends_at=now + timedelta(days=30),
            activated_at=None,
            **came_from))
    return find(engine, slug)


def _signup_attribution(engine, slug, attribution):
    """The signup_* and referred_by values for a new company.

    A referral is kept only when it names a company that exists and is not
    the one being created: anybody can type ?ref=, and a reward should not
    follow a name that was made up or a company referring itself.
    """
    a = attribution or {}
    out = {f'signup_{k}': (a.get(k) or None) and str(a[k])[:120]
           for k in ('source', 'medium', 'campaign', 'referrer', 'landing')}
    out = {k: v for k, v in out.items() if v}
    ref = (a.get('ref') or '').strip().lower()
    if ref and ref != slug and find(engine, ref):
        out['referred_by'] = ref
    return out


def referred_by(engine, slug):
    """The companies that signed up through this company's referral link."""
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(
            select(organizations).where(organizations.c.referred_by == slug)
            .order_by(organizations.c.created_at)).mappings()]


def mark_provisioned(engine, slug):
    with engine.begin() as conn:
        conn.execute(update(organizations)
                     .where(organizations.c.slug == slug)
                     .values(provisioned_at=datetime.utcnow()))


def set_test_account(engine, slug, is_test):
    with engine.begin() as conn:
        conn.execute(update(organizations).where(organizations.c.slug == slug)
                     .values(is_test=bool(is_test)))


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
               'grandfathered', 'status', 'activated_at', 'nudges_sent',
               'mrr_cents', 'paid_since', 'canceled_at', 'discount_code'}
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


def record_tenant_login(engine, email, tenant_slug):
    """Index one more (email, tenant) pair. Idempotent, and never raises --
    called from the middle of signup and team-login creation, and a lookup
    row that failed to write must never be the reason either of those fails.

    Written once, at account creation, not on every sign-in: which tenant an
    email belongs to does not change afterward, so there is nothing to keep
    fresh on a later login.
    """
    email = (email or '').strip().lower()
    tenant_slug = (tenant_slug or '').strip().lower()
    if not email or not tenant_slug:
        return
    try:
        with engine.begin() as conn:
            exists = conn.execute(select(tenant_logins.c.id).where(
                tenant_logins.c.email == email,
                tenant_logins.c.tenant_slug == tenant_slug)).first()
            if not exists:
                conn.execute(insert(tenant_logins).values(
                    email=email, tenant_slug=tenant_slug))
    except Exception:
        pass


LOOKUP_COOLDOWN_MINUTES = 3


def lookup_recently_requested(engine, email):
    """True if this address was asked for within the cooldown window.

    Checked before sending, not after -- the caller must not send a second
    email just because the first attempt to record this row failed.
    """
    from datetime import timedelta
    email = (email or '').strip().lower()
    if not email:
        return False
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=LOOKUP_COOLDOWN_MINUTES)
        with engine.connect() as conn:
            row = conn.execute(select(login_lookup_requests.c.id).where(
                login_lookup_requests.c.email == email,
                login_lookup_requests.c.created_at >= cutoff)).first()
        return row is not None
    except Exception:
        return False


def record_lookup_request(engine, email):
    email = (email or '').strip().lower()
    if not email:
        return
    try:
        with engine.begin() as conn:
            conn.execute(insert(login_lookup_requests).values(email=email))
    except Exception:
        pass


def tenants_for_email(engine, email):
    """Every tenant slug this email has an account in, newest first.

    A UX hint for routing someone to the right subdomain, never an
    authentication decision -- the tenant's own login still requires the
    real password regardless of what this returns.
    """
    email = (email or '').strip().lower()
    if not email:
        return []
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                select(tenant_logins.c.tenant_slug)
                .where(tenant_logins.c.email == email)
                .order_by(tenant_logins.c.created_at.desc())
            ).all()
        return [r.tenant_slug for r in rows]
    except Exception:
        return []


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


def mark_lead_contacted(engine, lead_id):
    """Somebody has replied to this lead. Keeps the first time, if pressed twice."""
    with engine.begin() as conn:
        result = conn.execute(
            update(product_leads)
            .where(product_leads.c.id == lead_id,
                   product_leads.c.contacted_at.is_(None))
            .values(contacted_at=datetime.utcnow()))
        return result.rowcount > 0


def add_promo_code(engine, **fields):
    allowed = {c.name for c in promo_codes.columns} - {'id'}
    row = {k: v for k, v in fields.items() if k in allowed}
    row.setdefault('created_at', datetime.utcnow())
    row.setdefault('active', True)
    with engine.begin() as conn:
        conn.execute(insert(promo_codes).values(**row))


def all_promo_codes(engine):
    """Every code, newest first."""
    try:
        with engine.connect() as conn:
            return [dict(r) for r in conn.execute(
                select(promo_codes).order_by(promo_codes.c.created_at.desc())).mappings()]
    except Exception:
        return []


def find_promo_code(engine, code=None, stripe_promotion_id=None):
    col, value = ((promo_codes.c.stripe_promotion_id, stripe_promotion_id)
                  if stripe_promotion_id else (promo_codes.c.code, (code or '').upper()))
    try:
        with engine.connect() as conn:
            row = conn.execute(select(promo_codes).where(col == value)).mappings().first()
            return dict(row) if row else None
    except Exception:
        return None


def set_promo_active(engine, code, active):
    with engine.begin() as conn:
        conn.execute(update(promo_codes).where(promo_codes.c.code == code)
                     .values(active=bool(active)))



# --------------------------------------------------------------------------
# Feedback


def add_feedback(engine, **fields):
    """Record one piece of beta feedback. Returns its id."""
    allowed = {c.name for c in feedback.columns} - {'id', 'created_at', 'read_at'}
    row = {k: v for k, v in fields.items() if k in allowed}
    with engine.begin() as conn:
        res = conn.execute(insert(feedback).values(**row))
    try:
        return res.inserted_primary_key[0]
    except Exception:
        return None


def all_feedback(engine, limit=200):
    """Newest first, without the screenshots -- those are fetched one at a time."""
    cols = [c for c in feedback.columns if c.name != 'shot']
    with engine.connect() as conn:
        rows = conn.execute(
            select(*cols).order_by(feedback.c.created_at.desc()).limit(limit)
        ).mappings().all()
    return [dict(r) for r in rows]


def feedback_shot(engine, feedback_id):
    """(bytes, content-type) for one screenshot, or (None, None)."""
    with engine.connect() as conn:
        row = conn.execute(
            select(feedback.c.shot, feedback.c.shot_type)
            .where(feedback.c.id == feedback_id)
        ).first()
    if not row or not row[0]:
        return None, None
    return row[0], (row[1] or 'image/jpeg')


def mark_feedback_read(engine, feedback_id):
    with engine.begin() as conn:
        conn.execute(update(feedback)
                     .where(feedback.c.id == feedback_id)
                     .values(read_at=datetime.utcnow()))


def unread_feedback(engine):
    from sqlalchemy import func
    with engine.connect() as conn:
        return conn.execute(
            select(func.count()).select_from(feedback)
            .where(feedback.c.read_at.is_(None))).scalar() or 0


# --------------------------------------------------------------------------
# Console accounts
#
# Passwords are hashed with the same method the CRM's own users use. Failed
# attempts are counted and the account stops answering for a while, because
# this login can see every company in the product and nothing here was rate
# limited before.

LOCK_AFTER = 6
LOCK_MINUTES = 15

# owner > manager > helper. One rule follows from the order and covers every
# case: you may only act on somebody strictly below you, and may only hand out
# a role strictly below your own.
#
#   owner   — everything, and cannot be switched off through the console by
#             anybody, including another owner. Recovery is console_admin.py
#             from a terminal, which is the one place the founder can be sure
#             of being the only person standing.
#   manager — the eighty per cent: reads and triages every report, sees every
#             company, brings in and removes helpers. Cannot touch an owner or
#             another manager, and cannot appoint a manager.
#   helper  — reads and triages. Grants nobody anything.
RANK = {'owner': 3, 'manager': 2, 'helper': 1,
        # What the first version of this called them.
        'staff': 1}
ROLES = ('owner', 'manager', 'helper')


def rank(role):
    return RANK.get((role or '').strip().lower(), 0)


def may_act_on(actor_role, target_role):
    """Strictly below. Not beside, not above."""
    return rank(actor_role) > rank(target_role)


def may_grant(actor_role, new_role):
    """You cannot hand out your own level, only something under it."""
    return new_role in ROLES and rank(actor_role) > rank(new_role)


def console_user(engine, email):
    with engine.connect() as conn:
        row = conn.execute(select(console_users).where(
            console_users.c.email == (email or '').strip().lower())).mappings().first()
    return dict(row) if row else None


def console_users_all(engine):
    with engine.connect() as conn:
        rows = conn.execute(select(console_users).order_by(
            console_users.c.created_at)).mappings().all()
    return [dict(r) for r in rows]


def add_console_user(engine, email, name, password, role='staff'):
    from werkzeug.security import generate_password_hash
    email = (email or '').strip().lower()
    with engine.begin() as conn:
        conn.execute(insert(console_users).values(
            email=email, name=name, role=role,
            password_hash=generate_password_hash(password, method='pbkdf2:sha256'),
            active=True))
    return console_user(engine, email)


def set_console_password(engine, email, password):
    from werkzeug.security import generate_password_hash
    with engine.begin() as conn:
        conn.execute(update(console_users)
                     .where(console_users.c.email == (email or '').strip().lower())
                     .values(password_hash=generate_password_hash(
                         password, method='pbkdf2:sha256'),
                         failed=0, locked_until=None))


def set_console_active(engine, email, active):
    with engine.begin() as conn:
        conn.execute(update(console_users)
                     .where(console_users.c.email == (email or '').strip().lower())
                     .values(active=bool(active)))


def check_console_login(engine, email, password):
    """(user, why-not). Never says which half was wrong.

    "No such account" and "wrong password" told apart is how somebody learns
    which addresses are real, and this list is small enough to be worth
    guessing at.
    """
    from datetime import timedelta
    from werkzeug.security import check_password_hash
    row = console_user(engine, email)
    if not row or not row.get('active'):
        return None, 'no'
    locked = row.get('locked_until')
    if locked and locked > datetime.utcnow():
        return None, 'locked'
    if not row.get('password_hash') or not check_password_hash(
            row['password_hash'], password or ''):
        failed = (row.get('failed') or 0) + 1
        values = {'failed': failed}
        if failed >= LOCK_AFTER:
            values['locked_until'] = datetime.utcnow() + timedelta(minutes=LOCK_MINUTES)
            values['failed'] = 0
        with engine.begin() as conn:
            conn.execute(update(console_users)
                         .where(console_users.c.id == row['id']).values(**values))
        return None, 'locked' if 'locked_until' in values else 'no'

    with engine.begin() as conn:
        conn.execute(update(console_users).where(console_users.c.id == row['id'])
                     .values(failed=0, locked_until=None,
                             last_login_at=datetime.utcnow()))
    return row, None


# --------------------------------------------------------------------------
# Questions from the public site


def add_support_request(engine, **fields):
    allowed = {c.name for c in support_requests.columns} - {'id', 'created_at',
                                                            'answered_at'}
    row = {k: v for k, v in fields.items() if k in allowed}
    with engine.begin() as conn:
        conn.execute(insert(support_requests).values(**row))


def all_support_requests(engine, limit=200):
    with engine.connect() as conn:
        rows = conn.execute(select(support_requests).order_by(
            support_requests.c.created_at.desc()).limit(limit)).mappings().all()
    return [dict(r) for r in rows]


def mark_support_answered(engine, request_id):
    with engine.begin() as conn:
        conn.execute(update(support_requests)
                     .where(support_requests.c.id == request_id)
                     .values(answered_at=datetime.utcnow()))


def unanswered_support(engine):
    from sqlalchemy import func
    with engine.connect() as conn:
        return conn.execute(
            select(func.count()).select_from(support_requests)
            .where(support_requests.c.answered_at.is_(None))).scalar() or 0


# --------------------------------------------------------------------------
# What was done, and by whom


def log_console(engine, actor, action, target=None, detail=None):
    """Write one line. Never raises -- a lost log line must not lose the work."""
    try:
        with engine.begin() as conn:
            conn.execute(insert(console_log).values(
                actor=(actor or '')[:200], action=(action or '')[:40],
                target=(target or '')[:200] or None,
                detail=(detail or '')[:400] or None))
    except Exception:
        pass


def console_log_all(engine, limit=300):
    with engine.connect() as conn:
        rows = conn.execute(select(console_log).order_by(
            console_log.c.created_at.desc()).limit(limit)).mappings().all()
    return [dict(r) for r in rows]


def set_console_role(engine, email, role):
    with engine.begin() as conn:
        conn.execute(update(console_users)
                     .where(console_users.c.email == (email or '').strip().lower())
                     .values(role=role))


# --------------------------------------------------------------------------
# Playbooks -- reference material, not any one company's


def add_console_doc(engine, title, content, created_by=None, sort_order=0):
    with engine.begin() as conn:
        res = conn.execute(insert(console_docs).values(
            title=title, content=content, created_by=created_by,
            sort_order=sort_order))
    try:
        return res.inserted_primary_key[0]
    except Exception:
        return None


def all_console_docs(engine):
    with engine.connect() as conn:
        rows = conn.execute(select(console_docs).order_by(
            console_docs.c.sort_order, console_docs.c.id)).mappings().all()
    return [dict(r) for r in rows]


def console_doc(engine, doc_id):
    with engine.connect() as conn:
        row = conn.execute(select(console_docs).where(
            console_docs.c.id == doc_id)).mappings().first()
    return dict(row) if row else None


def update_console_doc(engine, doc_id, title, content):
    with engine.begin() as conn:
        conn.execute(update(console_docs)
                     .where(console_docs.c.id == doc_id)
                     .values(title=title, content=content,
                             updated_at=datetime.utcnow()))
