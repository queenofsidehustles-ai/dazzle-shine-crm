"""The line a demo company cannot cross: nothing it does leaves Akye.

A demo company (organizations.is_demo, see demo_company.py) is a fictional
business shown to prospects. Its customers have example.com addresses and
555 numbers, and anyone given its login can press every button. So it must
never send an email, a text or a MailerLite signup, never reach Stripe with a
real key, and never start a subscription on Akye's own account.

That is enforced here, on the server, at the few places every outbound path
goes through -- not by hiding buttons:

  integrations.get()        every tenant Stripe, Twilio and Resend key.
                            A company with no keys of its own falls back to
                            the platform's environment keys, so without this a
                            demo company would send on Akye's accounts.
  notifications.send_*      email, SMS, marketing SMS, MailerLite: refused and
                            written to the Sent Log as "Demo company — not
                            sent", even when the caller passes a key directly.
                            The one exception is email to Akye's own support
                            inbox (a crash alert or feedback about the demo).
  tenant Stripe webhook     refused without a secret, which the demo never has
                            (blueprints/api.py).
  billing checkout/portal   Akye's own Stripe: a demo company never subscribes.
  scheduler.companies()     a demo company's daily automations never run, so
                            its seeded state does not drift.

Its sign-in and its connection keys are fixed too: the login may be handed to
many people, and one of them changing the password or turning on two-factor
would lock the rest out, while keys pasted into a shared demo would be kept
where the next visitor works.

  account password / 2FA    refused (blueprints/account.py)
  Settings -> Connections   saving keys refused (blueprints/settings.py)

`active()` answers "is the work in hand a demo company's?" three ways, and any
one of them is enough:

  * inside a request, the company the request belongs to is marked is_demo;
  * outside one (the seed, a CLI, a test), the database schema in use belongs
    to a company marked is_demo, or is the demo's staging schema;
  * the code asked for it explicitly with `forced()` (the seed does, from its
    first line, before the company is even registered).
"""
import contextlib
import contextvars
import time

BLOCKED_DETAIL = 'Demo company — not sent. Demo companies never contact anybody.'
FIXED_DETAIL = ('This is the demo company, so its sign-in and connections stay '
                'as they are for everyone who is given them.')
STAGING_SUFFIX = '__next'

_forced = contextvars.ContextVar('demo_guard_forced', default=False)
_schemas_cache = {'at': 0.0, 'schemas': frozenset()}
_CACHE_SECONDS = 30


@contextlib.contextmanager
def forced():
    """Treat everything inside the block as a demo company's work."""
    token = _forced.set(True)
    try:
        yield
    finally:
        _forced.reset(token)


def _demo_schemas():
    """Schemas that belong to demo companies, including their staging copies."""
    now = time.monotonic()
    if now - _schemas_cache['at'] < _CACHE_SECONDS:
        return _schemas_cache['schemas']
    schemas = set()
    try:
        import control_plane
        import provisioning
        for org in control_plane.all_orgs(provisioning._engine()):
            if org.get('is_demo') and org.get('schema_name'):
                schemas.add(org['schema_name'])
                schemas.add(org['schema_name'] + STAGING_SUFFIX)
    except Exception:
        return _schemas_cache['schemas']      # keep the last known answer
    _schemas_cache.update(at=now, schemas=frozenset(schemas))
    return _schemas_cache['schemas']


def forget_cache():
    _schemas_cache.update(at=0.0, schemas=frozenset())


def active():
    """True if the work in hand belongs to a demo company."""
    if _forced.get():
        return True
    try:
        from flask import has_request_context
        if has_request_context():
            import billing
            org = billing.current_org()
            if org is not None:
                return bool(org.get('is_demo'))
    except Exception:
        pass
    try:
        import tenancy
        schema = tenancy.current_schema()
        if schema and schema != tenancy.PUBLIC:
            return schema in _demo_schemas()
    except Exception:
        pass
    return False


class DemoBlocked(RuntimeError):
    """Raised where an outbound action cannot simply report failure."""
