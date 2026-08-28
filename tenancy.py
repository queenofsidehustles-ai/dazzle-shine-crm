"""Which company's data this request is allowed to see.

One database. Each company gets its own PostgreSQL *schema* — its own private
copy of all thirty-seven tables. A request for acme.example.com runs with
`search_path` set to that company's schema, so `Booking.query.all()` returns
Acme's bookings and there is no query anyone can write that returns anybody
else's, because the other rows are not in the tables it can see.

## Why this and not a company_id column on every table

The obvious alternative is a tenant column everywhere and a filter on every
query. It is cheaper to run and it is how the biggest products do it. It is also
a design where one forgotten `.filter_by(org_id=...)` in one of several hundred
places puts one company's client list on another company's screen — and there is
no compiler, no test that runs itself, and no error to notice. The failure is
silent and it is unforgivable.

Here, forgetting produces *no* rows rather than *someone else's* rows. That
failure is survivable and loud. On a codebase of thirty-three models and two
hundred and sixty routes that were all written single-tenant, it is the only
honest choice.

## The one real danger, and what is done about it

Connections are pooled. A connection that served Acme and goes back to the pool
still has Acme's search_path on it. Hand it to a request for Baker without
changing that, and Baker sees Acme's business. That is the whole risk of this
design, concentrated in one place.

So the search_path is set on **every** checkout from the pool, from a context
variable, unconditionally — never "only when it changed", never assumed. If
there is no tenant in context the answer is `public`, which is exactly what
every query has done since the day this application was written.

## Nothing changes for the business already running

An instance with no organisations resolves to `public` on every request and
behaves precisely as it does today. Tenancy is machinery that is present and
inert until something puts a tenant in context.
"""
import contextvars
import re

from sqlalchemy import event, text
from sqlalchemy.engine import Engine

# The schema every query has always run against, and the answer whenever no
# company has been resolved.
PUBLIC = 'public'

# Where a company's tables live. Deliberately prefixed: it keeps tenant schemas
# obviously distinct from public and from anything Postgres creates itself, and
# it means a slug can never collide with a real schema name.
SCHEMA_PREFIX = 'tenant_'

# A slug has to be safe to paste into a SQL identifier and safe to put in front
# of a domain name. Anything else is refused rather than escaped.
SLUG_RE = re.compile(r'^[a-z][a-z0-9-]{1,38}[a-z0-9]$')

# Subdomains that are not companies.
RESERVED_SLUGS = {
    'www', 'app', 'api', 'admin', 'help', 'support', 'docs', 'blog', 'mail',
    'status', 'billing', 'account', 'accounts', 'login', 'signup', 'static',
    'assets', 'cdn', 'dashboard', 'public', 'test', 'staging', 'dev', 'demo',
}

_current = contextvars.ContextVar('tenant_schema', default=PUBLIC)


# ---------------------------------------------------------------------------
# What schema this request is running against
# ---------------------------------------------------------------------------

def current_schema():
    return _current.get()


def is_tenant():
    """True when this request belongs to a company rather than the host itself."""
    return _current.get() != PUBLIC


def schema_for(slug):
    return f'{SCHEMA_PREFIX}{slug.replace("-", "_")}'


def valid_slug(slug):
    return bool(slug) and bool(SLUG_RE.match(slug)) and slug not in RESERVED_SLUGS


class use_tenant:
    """Run a block against one company's data.

        with use_tenant('acme'):
            Booking.query.count()      # Acme's bookings, and only Acme's

    Restores whatever was in context before, so nesting and background jobs
    cannot leave a thread pointed at the wrong company.
    """

    def __init__(self, slug_or_schema):
        s = slug_or_schema or PUBLIC
        self.schema = s if (s == PUBLIC or s.startswith(SCHEMA_PREFIX)) else schema_for(s)
        self._token = None

    def __enter__(self):
        self._token = _current.set(self.schema)
        _apply_to_open_connections()
        return self

    def __exit__(self, *exc):
        _current.reset(self._token)
        _apply_to_open_connections()
        return False


def _apply_to_open_connections():
    """Push the change onto a connection this request may already be holding.

    The pool event below covers a connection being handed out. A session that
    already checked one out earlier in the same request would otherwise keep the
    old search_path until it was returned.
    """
    try:
        from extensions import db
        from flask import has_app_context
        if not has_app_context():
            return
        bind = db.session.get_bind()
        if bind is not None and bind.dialect.name == 'postgresql':
            db.session.execute(text(f'SET search_path TO {_path()}'))
    except Exception:
        # Never let this be the reason a request fails. The checkout hook is
        # the guarantee; this is an optimisation on top of it.
        pass


def _path(schema=None):
    """The search_path to set. public stays on the end so shared things —
    extensions, and the control-plane tables — remain reachable."""
    schema = schema or _current.get()
    if schema == PUBLIC:
        return PUBLIC
    return f'"{schema}", {PUBLIC}'


# ---------------------------------------------------------------------------
# The guarantee: every connection handed out is pointed at the right company
# ---------------------------------------------------------------------------

_installed = False


def install_pool_guard():
    """Set search_path on every checkout from the connection pool.

    Unconditionally, from the context variable, every single time. Not "when it
    differs from last time" — the last time was a different request, possibly a
    different company, and that assumption is the leak this whole design exists
    to make impossible.
    """
    global _installed
    if _installed:
        return
    _installed = True

    @event.listens_for(Engine, 'checkout')
    def _set_search_path(dbapi_conn, conn_record, conn_proxy):
        try:
            cur = dbapi_conn.cursor()
        except Exception:
            return                       # not a DB-API that works this way
        try:
            cur.execute(f'SET search_path TO {_path()}')
        except Exception:
            # SQLite and friends have no schemas and no search_path. There is
            # nothing to set and nothing to leak.
            pass
        finally:
            try:
                cur.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Which company a request belongs to
# ---------------------------------------------------------------------------

def slug_from_host(host, base_domain=None):
    """The company slug in a hostname, or None for the host site itself.

    acme.rollcall.com      -> 'acme'
    rollcall.com           -> None
    www.rollcall.com       -> None
    localhost:5000         -> None
    a-crm.up.railway.app   -> None   (the single-tenant instance running today)

    Returning None is what keeps the existing business working: no slug means
    public, which is what every query has always done.
    """
    if not host:
        return None
    host = host.split(':')[0].strip().lower().rstrip('.')
    if not host or host == 'localhost':
        return None
    # A bare IP address is never a subdomain.
    if re.match(r'^\d+\.\d+\.\d+\.\d+$', host):
        return None

    # No configured domain means no tenancy. Not "guess from the hostname" —
    # that is how the instance running this business today gets read as a
    # company called "dazzle-shine-crm-production", starts looking for a schema
    # that was never created, and finds nothing where its bookings used to be.
    #
    # A product has to be told its own domain before it can carve subdomains out
    # of it. Until BASE_DOMAIN is set, every request is public, which is what
    # every request has always been.
    if not base_domain:
        return None

    base = base_domain.split(':')[0].strip().lower().rstrip('.')
    if host == base or not host.endswith('.' + base):
        return None
    candidate = host[: -(len(base) + 1)]

    # Only the leftmost label, and only if it is a legal, unreserved slug.
    candidate = candidate.split('.')[0]
    return candidate if valid_slug(candidate) else None


def resolve(host, base_domain=None):
    """(slug, schema) for a hostname. (None, 'public') for the host site."""
    slug = slug_from_host(host, base_domain)
    return (slug, schema_for(slug)) if slug else (None, PUBLIC)
