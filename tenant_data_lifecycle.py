"""Akye tenant closure and permanent-purge boundary.

Closure is reversible containment. Purge is destructive and is unavailable until
30 calendar days after the immutable closure timestamp. This module deliberately
operates from the public control plane; it never relies on a tenant request
context to decide what may be destroyed.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import text

import control_plane
import tenancy

RETENTION_DAYS = 30


class LifecycleError(RuntimeError):
    pass


class RetentionNotExpired(LifecycleError):
    pass


def ensure_columns(engine) -> None:
    """Add additive control-plane lifecycle columns for existing deployments."""
    control_plane.ensure_table(engine)
    if engine.dialect.name != 'postgresql':
        raise LifecycleError('tenant lifecycle requires PostgreSQL')
    with engine.begin() as conn:
        conn.execute(text(
            'ALTER TABLE public.organizations '
            'ADD COLUMN IF NOT EXISTS closed_at TIMESTAMP'))
        conn.execute(text(
            'ALTER TABLE public.organizations '
            'ADD COLUMN IF NOT EXISTS purged_at TIMESTAMP'))


def _org(engine, slug):
    if not tenancy.valid_slug(slug):
        raise LifecycleError(f'invalid tenant slug: {slug!r}')
    ensure_columns(engine)
    with engine.connect() as conn:
        row = conn.execute(text(
            'SELECT slug, name, schema_name, status, owner_email, closed_at, purged_at '
            'FROM public.organizations WHERE slug = :slug'), {'slug': slug}).mappings().first()
    return dict(row) if row else None


def close_tenant(engine, slug, *, now=None):
    """Immediately deny tenant access and start the immutable retention clock."""
    now = now or datetime.utcnow()
    org = _org(engine, slug)
    if not org:
        raise LifecycleError(f'no tenant {slug!r}')
    if org.get('purged_at'):
        raise LifecycleError('a purged tenant cannot be reopened or re-closed')
    expected = tenancy.schema_for(slug)
    if org.get('schema_name') != expected:
        raise LifecycleError('control-plane schema assignment does not match tenant slug')

    with engine.begin() as conn:
        # COALESCE makes closed_at immutable across repeated close requests.
        conn.execute(text(
            "UPDATE public.organizations "
            "SET status = 'closed', closed_at = COALESCE(closed_at, :now) "
            "WHERE slug = :slug AND purged_at IS NULL"),
            {'slug': slug, 'now': now})
    return lifecycle_state(engine, slug)


def lifecycle_state(engine, slug):
    org = _org(engine, slug)
    if not org:
        return None
    closed_at = org.get('closed_at')
    eligible_at = closed_at + timedelta(days=RETENTION_DAYS) if closed_at else None
    return {**org, 'eligible_at': eligible_at}


def purge_eligible(engine, slug, *, now=None):
    """Return whether permanent purge is allowed *now* without mutating data.

    This is the operator/CLI preflight only. ``purge_tenant`` independently
    re-checks the same conditions under its destructive transaction, so a
    successful preflight can never bypass the retention or lifecycle boundary.
    Already-purged tombstones return False because there is nothing left for an
    operator to destroy.
    """
    now = now or datetime.utcnow()
    state = lifecycle_state(engine, slug)
    if not state or state.get('purged_at'):
        return False
    if state.get('status') != 'closed' or not state.get('closed_at'):
        return False
    if state.get('schema_name') != tenancy.schema_for(slug):
        return False
    return now >= state['eligible_at']


def _delete_private_media(slug):
    """Delete only authenticated Cloudinary assets under this tenant's prefix.

    If Cloudinary is configured, deletion is mandatory and fail-closed. If it is
    not configured there can be no provider assets created by private_media.py,
    so the database-only purge may proceed.
    """
    import private_media
    if not private_media.is_ready():
        return {'provider': 'cloudinary', 'configured': False, 'deleted': 0}

    private_media._configure()
    import cloudinary.api
    prefix = f'akye-private/{slug}/'
    deleted = 0
    cursor = None
    while True:
        kwargs = {
            'resource_type': 'image',
            'type': 'authenticated',
            'invalidate': True,
        }
        if cursor:
            kwargs['next_cursor'] = cursor
        result = cloudinary.api.delete_resources_by_prefix(prefix, **kwargs) or {}
        deleted += len(result.get('deleted') or {})
        cursor = result.get('next_cursor')
        if not cursor:
            break
    return {'provider': 'cloudinary', 'configured': True, 'deleted': deleted}


def purge_tenant(engine, slug, *, now=None, media_delete=None):
    """Permanently purge one eligible closed tenant, leaving a minimal tombstone.

    External private media is deleted before the database transaction. A media
    failure therefore cannot erase the only database copy while provider bytes
    remain. If the later database transaction fails, the tenant stays closed and
    a retry is safe.
    """
    now = now or datetime.utcnow()
    state = lifecycle_state(engine, slug)
    if not state:
        raise LifecycleError(f'no tenant {slug!r}')
    if state.get('purged_at'):
        return {**state, 'already_purged': True}
    if state.get('status') != 'closed' or not state.get('closed_at'):
        raise LifecycleError('tenant must be closed before purge')
    if now < state['eligible_at']:
        raise RetentionNotExpired(
            f"tenant is retained until {state['eligible_at'].isoformat()}")

    schema = tenancy.schema_for(slug)
    if state.get('schema_name') != schema:
        raise LifecycleError('control-plane schema assignment does not match tenant slug')

    media_result = (media_delete or _delete_private_media)(slug)

    # The slug has already passed valid_slug(), so schema is derived rather than
    # accepted from operator input. The advisory lock serializes repeated purge
    # attempts for the same tenant without blocking unrelated tenants.
    lock_key = f'akye-purge:{slug}'
    with engine.begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'), {'key': lock_key})
        current = conn.execute(text(
            'SELECT status, closed_at, purged_at, schema_name '
            'FROM public.organizations WHERE slug = :slug FOR UPDATE'),
            {'slug': slug}).mappings().first()
        if not current:
            raise LifecycleError('tenant disappeared during purge')
        if current['purged_at']:
            return {**lifecycle_state(engine, slug), 'already_purged': True}
        if current['status'] != 'closed' or not current['closed_at']:
            raise LifecycleError('tenant lifecycle changed during purge')
        if now < current['closed_at'] + timedelta(days=RETENTION_DAYS):
            raise RetentionNotExpired('retention window no longer permits purge')
        if current['schema_name'] != schema:
            raise LifecycleError('schema assignment changed during purge')

        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        # Feedback is tenant-linked control-plane content, including screenshots.
        conn.execute(text('DELETE FROM public.feedback WHERE org_slug = :slug'),
                     {'slug': slug})
        # Keep only the narrow tenant/billing/audit tombstone. Ordinary owner PII
        # and display content are no longer needed to serve a purged workspace.
        conn.execute(text(
            "UPDATE public.organizations SET "
            "status = 'closed', name = :name, owner_email = NULL, "
            "nudges_sent = NULL, purged_at = :now "
            "WHERE slug = :slug"),
            {'slug': slug, 'name': f'Purged tenant {slug}', 'now': now})

    return {**lifecycle_state(engine, slug), 'already_purged': False,
            'media': media_result}


def restored_closed_tenants_requiring_repurge(engine, *, now=None):
    """Find closed tenants whose restored schemas must never be reactivated.

    A backup taken during the 30-day retention window legitimately contains the
    closed tenant schema. Restoring it is safe only because status remains closed;
    once its original retention deadline has passed, recovery must re-run purge
    before external traffic is restored.
    """
    now = now or datetime.utcnow()
    ensure_columns(engine)
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT slug, schema_name, closed_at, purged_at FROM public.organizations "
            "WHERE status = 'closed' AND closed_at IS NOT NULL"),).mappings().all()
    out = []
    for row in rows:
        eligible_at = row['closed_at'] + timedelta(days=RETENTION_DAYS)
        if row.get('purged_at') or now >= eligible_at:
            out.append({**dict(row), 'eligible_at': eligible_at})
    return out
