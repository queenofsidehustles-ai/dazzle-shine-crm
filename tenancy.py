"""Which company's data this request is allowed to see.

Akye uses one PostgreSQL database with one schema per tenant. The security
boundary depends on every checked-out PostgreSQL connection being pointed at the
schema selected for the current request.
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
        try:
            _apply_to_open_connections()
        except Exception:
            # __exit__ is never called when __enter__ raises. Without this
            # rollback, one failed tenant switch contaminates the context for
            # everything that runs later in the same worker/task.
            _current.reset(self._token)
            self._token = None
            raise
        return self

    def __exit__(self, *exc):
        _current.reset(self._token)
        self._token = None
        _apply_to_open_connections()
        return False


def _apply_to_open_connections():
    """Push a tenant switch onto a connection the session already holds.

    PostgreSQL failures are security failures and must propagate. A failed
    search_path change must never leave a request running on the previous
    tenant's schema.
    """
    from extensions import db
    from flask import has_app_context

    if not has_app_context():
        return
    bind = db.session.get_bind()
    if bind is not None and bind.dialect.name == 'postgresql':
        db.session.execute(text(f'SET search_path TO {_path()}'))


def _path(schema=None):
    schema = schema or _current.get()
    if schema == PUBLIC:
        return PUBLIC
    return f'"{schema}", {PUBLIC}'


def _is_postgres_dbapi_connection(dbapi_conn):
    """Identify supported PostgreSQL DB-API connections without executing SQL."""
    module = type(dbapi_conn).__module__.lower()
    return module.startswith('psycopg2') or module.startswith('psycopg')


def _set_search_path_on_checkout(dbapi_conn, conn_record=None, conn_proxy=None):
    """Pool checkout guard.

    PostgreSQL is fail-closed: failure to obtain a cursor or execute SET aborts
    checkout. Other DB-APIs are ignored because SQLite and similar test backends
    do not implement PostgreSQL schemas/search_path.
    """
    if not _is_postgres_dbapi_connection(dbapi_conn):
        return

    cur = dbapi_conn.cursor()
    try:
        cur.execute(f'SET search_path TO {_path()}')
    finally:
        cur.close()


_installed = False


def install_pool_guard():
    """Set search_path unconditionally on every PostgreSQL connection checkout."""
    global _installed
    if _installed:
        return
    _installed = True
    event.listen(Engine, 'checkout', _set_search_path_on_checkout)


def slug_from_host(host, base_domain=None):
    """Return exactly one legal tenant label before base_domain, or None."""
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
    if '.' in candidate:
        return None
    return candidate if valid_slug(candidate) else None


def _authoritative_request_host(fallback):
    """Return the client-facing Host header that entered the WSGI app.

    Werkzeug ProxyFix preserves pre-proxy-rewrite values under
    ``werkzeug.proxy_fix.orig``. Akye may trust forwarded scheme/client data for
    link generation and logging, but tenant identity is a security boundary and
    must never be selected by a visitor-controlled X-Forwarded-Host value.

    Outside a request context (scheduler/tests/helpers), keep the explicit host
    supplied by the caller.
    """
    try:
        from flask import has_request_context, request
        if not has_request_context():
            return fallback
        original = request.environ.get('werkzeug.proxy_fix.orig') or {}
        return original.get('HTTP_HOST') or fallback
    except Exception:
        # Host resolution must remain deterministic even in non-Flask callers.
        return fallback


def _enforce_request_lifecycle(slug):
    """Authorize a hosted tenant against the public control plane.

    Hostname resolution says which schema a request *would* target. The control
    plane decides whether that company is currently allowed to use it. This is
    deliberately enforced before ``g.tenant_slug`` and the tenant search_path
    are installed, so a suspended/closed company cannot reach authenticated
    pages, public token links, cron routes, or provider callbacks.

    Suspension also clears a presented Flask session. Re-enabling a company
    therefore restores the tenant but not stale pre-suspension authentication;
    the owner/team must sign in again.
    """
    try:
        from flask import has_request_context, session
        if not has_request_context():
            return

        import control_plane
        from extensions import db
        org = control_plane.find(db.engine, slug)
        if not org:
            session.clear()
            from werkzeug.exceptions import NotFound
            raise NotFound()

        expected_schema = schema_for(slug)
        assigned_schema = (org.get('schema_name') or '').strip()
        if assigned_schema != expected_schema:
            # An active status is not enough. The control plane is the authority
            # assigning a company to its schema, so disagreement with the host-
            # derived schema is a containment failure, never permission to guess.
            session.clear()
            from werkzeug.exceptions import ServiceUnavailable
            raise ServiceUnavailable(
                description='Tenant schema assignment could not be verified.')

        status = (org.get('status') or '').strip().lower()
        if status == 'active':
            return

        session.clear()
        if status == 'suspended':
            from werkzeug.exceptions import Locked
            raise Locked(description='This workspace is temporarily suspended.')

        # Closed and unknown lifecycle values fail indistinguishably from a
        # nonexistent tenant. Unknown values are denied rather than implicitly
        # becoming active if the control plane is malformed or upgraded badly.
        from werkzeug.exceptions import NotFound
        raise NotFound()
    except Exception as exc:
        # Preserve deliberate HTTP lifecycle decisions. Any control-plane read
        # failure is an availability problem, never permission to fall through
        # into a tenant schema.
        from werkzeug.exceptions import HTTPException, ServiceUnavailable
        if isinstance(exc, HTTPException):
            raise
        raise ServiceUnavailable(
            description='Tenant lifecycle could not be verified.') from exc


def resolve(host, base_domain=None):
    """(slug, schema) for a hostname. (None, 'public') for the host site.

    During a Flask request, tenant selection is bound to the original Host
    header before ProxyFix can rewrite it from X-Forwarded-Host. Hosted tenant
    requests must also be active in the public control plane before their
    schema is selected.
    """
    host = _authoritative_request_host(host)
    slug = slug_from_host(host, base_domain)
    if not slug:
        return None, PUBLIC
    _enforce_request_lifecycle(slug)
    return slug, schema_for(slug)