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

PUBLIC = 'public'
SCHEMA_PREFIX = 'tenant_'
SLUG_RE = re.compile(r'^[a-z][a-z0-9-]{1,38}[a-z0-9]$')
RESERVED_SLUGS = {
    'www', 'app', 'api', 'admin', 'help', 'support', 'docs', 'blog', 'mail',
    'status', 'billing', 'account', 'accounts', 'login', 'signup', 'static',
    'assets', 'cdn', 'dashboard', 'public', 'test', 'staging', 'dev', 'demo',
}
_current = contextvars.ContextVar('tenant_schema', default=PUBLIC)


def current_schema():
    return _current.get()


def is_tenant():
    return _current.get() != PUBLIC


def schema_for(slug):
    return f'{SCHEMA_PREFIX}{slug.replace("-", "_")}'


def valid_slug(slug):
    return bool(slug) and bool(SLUG_RE.match(slug)) and slug not in RESERVED_SLUGS


class use_tenant:
    """Run a block against one company's data and restore the prior tenant."""

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
    """Push the tenant change onto a connection this request may already hold."""
    try:
        from extensions import db
        from flask import has_app_context
        if not has_app_context():
            return
        bind = db.session.get_bind()
        if bind is not None and bind.dialect.name == 'postgresql':
            db.session.execute(text(f'SET search_path TO {_path()}'))
    except Exception:
        # The checkout hook below remains the primary guard. This helper handles
        # an already checked-out connection during an explicit context switch.
        pass


def _path(schema=None):
    schema = schema or _current.get()
    if schema == PUBLIC:
        return PUBLIC
    return f'"{schema}", {PUBLIC}'


_installed = False


def install_pool_guard():
    """Set search_path unconditionally on every connection checkout."""
    global _installed
    if _installed:
        return
    _installed = True

    @event.listens_for(Engine, 'checkout')
    def _set_search_path(dbapi_conn, conn_record, conn_proxy):
        try:
            cur = dbapi_conn.cursor()
        except Exception:
            return
        try:
            cur.execute(f'SET search_path TO {_path()}')
        except Exception:
            # SQLite and other non-schema databases do not support search_path.
            pass
        finally:
            try:
                cur.close()
            except Exception:
                pass


def slug_from_host(host, base_domain=None):
    """Return exactly one legal tenant label before base_domain, or None.

    Only ``<tenant>.<base-domain>`` is a tenant host. Deeper hostnames are
    rejected rather than silently aliasing their leftmost label to a tenant.
    """
    if not host:
        return None
    host = host.split(':')[0].strip().lower().rstrip('.')
    if not host or host == 'localhost':
        return None
    if re.match(r'^\d+\.\d+\.\d+\.\d+$', host):
        return None
    if not base_domain:
        return None

    base = base_domain.split(':')[0].strip().lower().rstrip('.')
    if host == base or not host.endswith('.' + base):
        return None

    candidate = host[: -(len(base) + 1)]
    # Tenant routing is deliberately one-label only.  Treating
    # alpha.attacker.example.com as alpha.example.com creates a host-alias
    # capability and weakens every host-scoped token/session boundary.
    if '.' in candidate:
        return None
    return candidate if valid_slug(candidate) else None


def resolve(host, base_domain=None):
    """(slug, schema) for a hostname. (None, 'public') for the host site."""
    slug = slug_from_host(host, base_domain)
    return (slug, schema_for(slug)) if slug else (None, PUBLIC)
