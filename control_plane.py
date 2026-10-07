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
from datetime import datetime, timedelta

from sqlalchemy import (Column, DateTime, Integer, String, Boolean, MetaData,
                        LargeBinary, Text, UniqueConstraint,
                        Table, select, insert, update, text, func)

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
    # She asked not to be emailed about her trial or courted as a lead. Set by
    # the owner herself from Settings, never by the console -- an opt-out a
    # business cannot see or control is not one. trial_nudges.due() checks
    # this before anything else a trial's state would otherwise call for.
    Column('nudges_opted_out', Boolean, default=False),

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
    # A fictional company for showing the product (demo_company.py). Implies
    # is_test, and more: demo_guard.py stops anything it does from leaving
    # Akye -- no email, text, Stripe or subscription -- and only a demo
    # company can be rebuilt by the demo seed.
    Column('is_demo', Boolean),
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
    # When she agreed to the Terms of Service, at signup. Not optional: signup
    # refuses to create the account at all without it (see blueprints/signup.py
    # _validate). Kept as a timestamp rather than a boolean because "she agreed"
    # is a fact worth being able to point to later, not just a flag.
    Column('terms_accepted_at', DateTime),
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
    # Set the moment the console sends this person a signup invite. Separate
    # from contacted_at: an invite is one specific email with a signup link in
    # it, not "we have been in touch" -- and it is what stops the same list
    # being emailed twice by two people working it at once.
    Column('invited_at', DateTime),
    # Outreach from the console (lead_outreach.py). The two opt-outs are kept
    # apart because the law keeps them apart: an unsubscribe link covers email,
    # a STOP reply covers texts, and neither implies the other.
    Column('last_emailed_at', DateTime),
    Column('last_texted_at', DateTime),
    Column('unsubscribed_at', DateTime),
    Column('sms_opted_out_at', DateTime),
    # How many times they have asked for early access. One row per person, so
    # nobody is emailed twice; asking again is counted here instead, because
    # somebody who asks twice is the warmest lead on the list.
    Column('times_asked', Integer),
    Column('last_asked_at', DateTime),
    # Somebody here decided this number is not to be texted -- it is on the
    # National Do Not Call list, say, or the list it came from was bought.
    # Separate from sms_opted_out_at: that is the person's own STOP, which
    # their START undoes; this is ours, and only the console undoes it.
    Column('do_not_text_at', DateTime),
)


# Every email and text the console sends a prospect, sent or refused: what
# went, to whom, who pressed the button, and what the provider said.
product_lead_messages = Table(
    'product_lead_messages', control_metadata,
    Column('id', Integer, primary_key=True),
    Column('lead_id', Integer, index=True),
    Column('channel', String(10)),                  # email | sms
    Column('to_address', String(200)),
    Column('subject', String(300)),
    Column('body', Text),
    Column('ok', Boolean, default=False),
    Column('detail', String(400)),
    Column('sent_by', String(200)),
    Column('sent_at', DateTime, default=datetime.utcnow, index=True),
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
    # Two-factor. A console login sees every company, so a password alone is
    # one phished email away from all of them. Same authenticator-app codes
    # and one-time backup codes as a company's own logins (totp.py).
    Column('totp_secret', String(64)),
    Column('totp_enabled', Boolean, default=False),
    Column('totp_backup_codes', Text),
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


# One switch token, once. The city switcher hands the browser a short-lived
# signed token and redirects it to the other city, which trades the token for a
# session there -- a session cannot simply be carried across, because sessions
# are bound to one tenant on purpose (see auth.bind_session_to_current_tenant).
# The signature and the ninety-second expiry are what make the token hard to
# forge; this table is what stops a token that leaked -- into a log, a Referer,
# somebody's shoulder -- being spent twice.
switch_tokens = Table(
    'switch_tokens', control_metadata,
    Column('id', Integer, primary_key=True),
    Column('jti', String(64), nullable=False, unique=True, index=True),
    Column('used_at', DateTime, default=datetime.utcnow),
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


# One row per signup attempt, by address, purely to rate limit it. Every
# signup creates a whole schema for a company; without a limit, a script could
# create thousands of them and take the database down for every real company.
signup_attempts = Table(
    'signup_attempts', control_metadata,
    Column('id', Integer, primary_key=True),
    Column('ip', String(45), nullable=False, index=True),
    Column('created_at', DateTime, default=datetime.utcnow, index=True),
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


def _ensure_table_columns(engine, table):
    """Add any column `table` declares that the live table does not have.

    `create_all` creates missing tables. It does not touch a table that
    already exists, so a column added to a Table object after a deployment
    went live would simply never appear there — and every read of it would
    fail on the one database that matters.

    Per-company schemas have alembic for this. The control plane sits outside
    it by design, so it needs its own small version: additive only, one column
    at a time, and silent when there is nothing to do.

    Derived from the Table object's own declared columns rather than a
    separately hand-maintained list — a hand-maintained list is exactly how
    `suspended_at`, `closed_at` and `purged_at` were each independently
    missed here before, one at a time, as `organizations` grew and this
    function did not.
    """
    from sqlalchemy import inspect as sa_inspect
    try:
        have = {c['name'] for c in sa_inspect(engine).get_columns(
            table.name, schema='public')}
    except Exception:
        return                      # table is not there yet; create_all will make it
    for column in table.columns:
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
                    f'ALTER TABLE public.{table.name} ADD COLUMN {column.name} {sqltype}'))
            print(f'  ✅ control plane: added {table.name}.{column.name}')
        except Exception as e:
            print(f'  ⚠️  could not add {table.name}.{column.name}: {e}')


def ensure_columns(engine):
    """The additive backfill above, for every control-plane table that has
    grown a column since it was first deployed."""
    _ensure_table_columns(engine, organizations)
    _ensure_table_columns(engine, product_leads)
    _ensure_table_columns(engine, console_users)


def ensure_table(engine):
    """Create the control-plane table if it is not there. Safe to call always."""
    control_metadata.create_all(
        engine, tables=[organizations, product_leads, feedback,
                        console_users, support_requests, console_log,
                        tenant_logins, login_lookup_requests, console_docs,
                        switch_tokens,
                        promo_codes, product_lead_messages, signup_attempts])
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


def create(engine, slug, name, owner_email=None, attribution=None,
           terms_accepted_at=None):
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
            terms_accepted_at=terms_accepted_at,
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


def set_demo_company(engine, slug):
    """Mark a company as the fictional demo: test account and demo both."""
    with engine.begin() as conn:
        conn.execute(update(organizations).where(organizations.c.slug == slug)
                     .values(is_test=True, is_demo=True))


def set_test_account(engine, slug, is_test):
    """Mark a company as a test account or a real one.

    The demo company stays a test account whatever is asked: it is fictional,
    and counting it would put made-up customers into the funnel and sales
    numbers."""
    with engine.begin() as conn:
        q = update(organizations).where(organizations.c.slug == slug)
        if not is_test:
            q = q.where(organizations.c.is_demo.isnot(True))
        conn.execute(q.values(is_test=bool(is_test)))


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
               'nudges_opted_out',
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


def add_lead(engine, count_repeat=False, do_not_text=False, **fields):
    """Record somebody who asked for early access. Never raises.

    A form that loses the person filling it in is worse than no form. If the
    table is missing or the write fails, the caller still emails the details
    on, so the lead reaches a human either way.

    True when a row was added -- or, with count_repeat, when somebody already
    on the list asked again and it was counted on their existing row. False
    for a duplicate that was skipped (an uploaded list repeating somebody).
    None when the write failed -- falsy like a duplicate for callers that only
    ask "was it added", but distinct for one that has to report what happened.

    do_not_text marks the row as not to be texted -- the existing one too, if
    this is a duplicate, since an upload flagged "do not text" is usually the
    same people again after checking them against the Do Not Call list.
    """
    allowed = {'name', 'company', 'email', 'phone', 'cleaners', 'note', 'source'}
    row = {k: (v or None) for k, v in fields.items() if k in allowed}
    if row.get('email'):
        row['email'] = row['email'].strip().lower()
    if row.get('phone'):
        row['phone'] = row['phone'].strip()
    row['created_at'] = datetime.utcnow()
    if do_not_text:
        row['do_not_text_at'] = row['created_at']
    try:
        ensure_table(engine)
        # A CSV can be uploaded twice, or the same business can appear in two
        # prospect lists. Email and phone are contact identities; do not turn
        # either into duplicate outreach records. Phone comparison ignores
        # punctuation so "(240) 555-0100" and "240-555-0100" are the same.
        email = row.get('email')
        phone_digits = ''.join(ch for ch in (row.get('phone') or '') if ch.isdigit())
        with engine.begin() as conn:
            if email or phone_digits:
                # Asked of the database, not by reading every lead into Python
                # for every row: an upload of a few thousand against a long
                # list did that thousands of times over and ran out of time.
                same = []
                if email:
                    same.append(func.lower(func.trim(product_leads.c.email)) == email)
                if phone_digits:
                    same.append(func.regexp_replace(
                        func.coalesce(product_leads.c.phone, ''), '[^0-9]', '', 'g')
                        == phone_digits)
                from sqlalchemy import or_
                existing = conn.execute(select(product_leads.c.id).where(
                    or_(*same)).order_by(product_leads.c.id).limit(1)).scalar()
                if existing is not None:
                    if do_not_text:
                        conn.execute(update(product_leads).where(
                            product_leads.c.id == existing,
                            product_leads.c.do_not_text_at.is_(None))
                            .values(do_not_text_at=row['created_at']))
                    if not count_repeat:
                        return False
                    conn.execute(update(product_leads)
                                 .where(product_leads.c.id == existing)
                                 .values(times_asked=func.coalesce(
                                             product_leads.c.times_asked, 1) + 1,
                                         last_asked_at=row['created_at']))
                    return True
            conn.execute(insert(product_leads).values(**row))
        return True
    except Exception:
        return None


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


def mark_lead_invited(engine, lead_id):
    """Claim this lead for an invite, before sending. Returns True for
    whichever caller gets there first; a second caller (two people working
    the same uploaded list at once, or a bulk invite racing a single one)
    gets False and must not send -- claiming after the email is already out
    cannot stop a second one from going too."""
    with engine.begin() as conn:
        result = conn.execute(
            update(product_leads)
            .where(product_leads.c.id == lead_id,
                   product_leads.c.invited_at.is_(None))
            .values(invited_at=datetime.utcnow()))
        return result.rowcount > 0


def unmark_lead_invited(engine, lead_id):
    """Release a claim from mark_lead_invited() after the send failed, so the
    lead is eligible again rather than permanently (and wrongly) marked
    invited for an email that never arrived."""
    with engine.begin() as conn:
        conn.execute(update(product_leads).where(product_leads.c.id == lead_id)
                    .values(invited_at=None))


def lead_by_id(engine, lead_id):
    with engine.connect() as conn:
        row = conn.execute(select(product_leads).where(
            product_leads.c.id == lead_id)).mappings().first()
    return dict(row) if row else None


def record_lead_message(engine, lead_id, channel, to_address, subject, body,
                        ok, detail, sent_by):
    """Write one outreach attempt down, and stamp the lead if it went."""
    now = datetime.utcnow()
    with engine.begin() as conn:
        conn.execute(insert(product_lead_messages).values(
            lead_id=lead_id, channel=channel, to_address=(to_address or '')[:200],
            subject=(subject or '')[:300] or None, body=body, ok=bool(ok),
            detail=(detail or '')[:400], sent_by=sent_by, sent_at=now))
        if ok:
            stamp = 'last_emailed_at' if channel == 'email' else 'last_texted_at'
            conn.execute(update(product_leads).where(product_leads.c.id == lead_id)
                         .values(**{stamp: now}))


def lead_messages(engine, limit=100):
    """The most recent outreach, newest first, with who it was to."""
    try:
        with engine.connect() as conn:
            q = (select(product_lead_messages, product_leads.c.name,
                        product_leads.c.company)
                 .select_from(product_lead_messages.outerjoin(
                     product_leads, product_leads.c.id == product_lead_messages.c.lead_id))
                 .order_by(product_lead_messages.c.sent_at.desc()).limit(limit))
            return [dict(r) for r in conn.execute(q).mappings()]
    except Exception:
        return []


def mark_leads_unsubscribed(engine, email):
    """Every lead at this address stops getting email. Returns how many."""
    email = (email or '').strip().lower()
    if not email:
        return 0
    with engine.begin() as conn:
        return conn.execute(
            update(product_leads)
            .where(func.lower(product_leads.c.email) == email,
                   product_leads.c.unsubscribed_at.is_(None))
            .values(unsubscribed_at=datetime.utcnow())).rowcount


def _same_number(phone):
    """A WHERE clause for every lead whose phone is this number, however it
    was written: the last ten digits, the way texts are addressed (send_text
    turns both 555-123-4567 and +1 555 123 4567 into the same destination).
    None for something too short to be a number."""
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())[-10:]
    if len(digits) < 10:
        return None
    return func.right(func.regexp_replace(
        func.coalesce(product_leads.c.phone, ''), '[^0-9]', '', 'g'), 10) == digits


def set_lead_do_not_text(engine, lead_id, on=True):
    """Mark a lead as not to be texted, or clear it. It is the number that is
    marked: every lead with the same phone changes together, so a second row
    for the same person cannot be texted around the mark. True if any changed."""
    col = product_leads.c.do_not_text_at
    with engine.begin() as conn:
        phone = conn.execute(select(product_leads.c.phone).where(
            product_leads.c.id == lead_id)).scalar()
        same = _same_number(phone)
        who = same if same is not None else (product_leads.c.id == lead_id)
        return conn.execute(
            update(product_leads)
            .where(who, col.is_(None) if on else col.isnot(None))
            .values(do_not_text_at=datetime.utcnow() if on else None)).rowcount > 0


def number_text_block(engine, phone):
    """Why this number cannot be texted right now, read fresh from the database:
    'replied STOP' or 'marked do not text' if ANY lead with the same number
    says so, else None. Checked again immediately before every text, because
    the lead dict a send was started with can be minutes old, and a STOP or a
    mark on one row has to cover every row with that number."""
    same = _same_number(phone)
    if same is None:
        return None
    with engine.connect() as conn:
        row = conn.execute(select(
            func.count(product_leads.c.sms_opted_out_at),
            func.count(product_leads.c.do_not_text_at)).where(same)).first()
    if row and row[0]:
        return 'replied STOP'
    if row and row[1]:
        return 'marked do not text'
    return None


def set_leads_sms_opt_out(engine, phone, opted_out=True):
    """STOP (or START) from a number: every lead with it, compared by digits.
    Returns how many leads changed."""
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())[-10:]
    if len(digits) < 10:
        return 0
    with engine.begin() as conn:
        ids = [r.id for r in conn.execute(
                   select(product_leads.c.id, product_leads.c.phone))
               if ''.join(ch for ch in (r.phone or '') if ch.isdigit())[-10:] == digits]
        if not ids:
            return 0
        return conn.execute(
            update(product_leads).where(product_leads.c.id.in_(ids))
            .values(sms_opted_out_at=datetime.utcnow() if opted_out else None)).rowcount


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


def new_leads_count(engine):
    """Neither contacted nor invited yet -- the ones nobody has acted on."""
    from sqlalchemy import func
    with engine.connect() as conn:
        return conn.execute(
            select(func.count()).select_from(product_leads)
            .where(product_leads.c.contacted_at.is_(None),
                   product_leads.c.invited_at.is_(None))).scalar() or 0


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

    A right password on a login with two-factor switched on returns the user
    too: the caller must still ask for the code (check_console_code) before
    treating them as signed in.
    """
    from werkzeug.security import check_password_hash
    row = console_user(engine, email)
    if not row or not row.get('active'):
        return None, 'no'
    locked = row.get('locked_until')
    if locked and locked > datetime.utcnow():
        return None, 'locked'
    if not row.get('password_hash') or not check_password_hash(
            row['password_hash'], password or ''):
        return None, _console_login_failed(engine, row)

    if row.get('totp_enabled'):
        # Right password, second step still to come. Not a completed login,
        # so neither the failure count nor last_login_at moves yet.
        return row, None
    _console_login_succeeded(engine, row)
    return row, None


def _console_login_failed(engine, row):
    """Count a wrong password or code against the same lockout. 'locked' or 'no'."""
    from datetime import timedelta
    failed = (row.get('failed') or 0) + 1
    values = {'failed': failed}
    if failed >= LOCK_AFTER:
        values['locked_until'] = datetime.utcnow() + timedelta(minutes=LOCK_MINUTES)
        values['failed'] = 0
    with engine.begin() as conn:
        conn.execute(update(console_users)
                     .where(console_users.c.id == row['id']).values(**values))
    return 'locked' if 'locked_until' in values else 'no'


def _console_login_succeeded(engine, row):
    with engine.begin() as conn:
        conn.execute(update(console_users).where(console_users.c.id == row['id'])
                     .values(failed=0, locked_until=None,
                             last_login_at=datetime.utcnow()))


def check_console_code(engine, email, code):
    """Second step: a live authenticator code, or one unused backup code.
    (user, why-not), with wrong codes counting toward the same lockout as
    wrong passwords -- six digits are guessable in bulk otherwise."""
    import totp
    row = console_user(engine, email)
    if not row or not row.get('active') or not row.get('totp_enabled'):
        return None, 'no'
    locked = row.get('locked_until')
    if locked and locked > datetime.utcnow():
        return None, 'locked'
    code = (code or '').strip()
    if totp.verify_totp(row.get('totp_secret') or '', code):
        _console_login_succeeded(engine, row)
        return row, None
    remaining = totp.consume_backup_code(row.get('totp_backup_codes'), code)
    if remaining is not None:
        with engine.begin() as conn:
            conn.execute(update(console_users).where(console_users.c.id == row['id'])
                         .values(totp_backup_codes=remaining))
        _console_login_succeeded(engine, row)
        return row, None
    return None, _console_login_failed(engine, row)


def start_console_totp(engine, email):
    """A fresh secret, saved but not switched on until a code proves it works."""
    import totp
    secret = totp.generate_secret()
    with engine.begin() as conn:
        conn.execute(update(console_users)
                     .where(console_users.c.email == (email or '').strip().lower())
                     .values(totp_secret=secret, totp_enabled=False))
    return secret


def enable_console_totp(engine, email, code):
    """Switch two-factor on if `code` came from the saved secret. Returns the
    backup codes -- shown once, only their hashes kept -- or None."""
    import totp
    row = console_user(engine, email)
    if not row or not row.get('totp_secret') or not totp.verify_totp(row['totp_secret'], code):
        return None
    codes = totp.generate_backup_codes()
    with engine.begin() as conn:
        conn.execute(update(console_users).where(console_users.c.id == row['id'])
                     .values(totp_enabled=True,
                             totp_backup_codes=totp.hash_backup_codes(codes)))
    return codes


def disable_console_totp(engine, email):
    with engine.begin() as conn:
        conn.execute(update(console_users)
                     .where(console_users.c.email == (email or '').strip().lower())
                     .values(totp_secret=None, totp_enabled=False,
                             totp_backup_codes=None))


# --------------------------------------------------------------------------
# Signup rate limits


def record_signup_attempt(engine, ip):
    try:
        with engine.begin() as conn:
            conn.execute(insert(signup_attempts).values(ip=(ip or 'unknown')[:45]))
            # Only the last day is ever counted (signup._refused). A week is
            # kept for looking back at a flood; anything older goes.
            conn.execute(signup_attempts.delete().where(
                signup_attempts.c.created_at < datetime.utcnow() - timedelta(days=7)))
    except Exception:
        pass


def signup_attempts_since(engine, ip, since):
    try:
        with engine.connect() as conn:
            return conn.execute(select(func.count()).select_from(signup_attempts).where(
                signup_attempts.c.ip == (ip or 'unknown')[:45],
                signup_attempts.c.created_at >= since)).scalar() or 0
    except Exception:
        return 0


def orgs_created_since(engine, since):
    try:
        with engine.connect() as conn:
            return conn.execute(select(func.count()).select_from(organizations).where(
                organizations.c.created_at >= since)).scalar() or 0
    except Exception:
        return 0


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


def claim_switch_token(engine, jti):
    """True the first time this token id is seen, False ever after.

    The uniqueness constraint does the work rather than a read-then-write: two
    requests arriving together both find nothing, and without the constraint
    both would proceed. Here the second insert raises and that request is
    refused, which is the behaviour wanted from a token that may be spent once.
    """
    jti = (jti or '').strip()
    if not jti:
        return False
    try:
        with engine.begin() as conn:
            conn.execute(insert(switch_tokens).values(jti=jti))
        return True
    except Exception:
        return False
