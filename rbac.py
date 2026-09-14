"""Central role and permission policy for tenant CRM users.

IAM-01 requires a written allow/deny matrix for owner, admin, dispatcher,
cleaner and limited roles. This module is the canonical server-side policy.
Unknown roles and permissions fail closed. The legacy ``team`` role is treated
as ``limited`` until an owner deliberately reassigns it.
"""
from flask import abort, request, session

CANONICAL_ROLES = frozenset({'owner', 'admin', 'dispatcher', 'cleaner', 'limited'})
LEGACY_ROLE_MAP = {'team': 'limited'}

# Keep capabilities intentionally coarse until each route has been split along
# real authority boundaries. In particular, money/pay mutation is owner-only;
# an operational admin or dispatcher does not gain financial authority merely
# because a route currently mixes scheduling and price fields in one form.
ROLE_PERMISSIONS = {
    'owner': frozenset({
        'booking.manage', 'dispatch.manage', 'pay.manage', 'finance.manage',
        'users.manage', 'settings.manage', 'assigned_work.use',
    }),
    'admin': frozenset({
        'booking.manage', 'dispatch.manage', 'assigned_work.use',
    }),
    'dispatcher': frozenset({
        'booking.manage', 'dispatch.manage',
    }),
    'cleaner': frozenset({'assigned_work.use'}),
    'limited': frozenset(),
}

# Exact endpoint/method rules for the first high-risk IAM slice. Unlisted
# endpoints retain their existing route decorators until they are deliberately
# classified; this prevents an incomplete matrix from accidentally granting
# access. The dangerous mixed booking-detail POST stays owner-only because it
# can alter price, lead fee, pay-driving hours, assignment and status together.
ENDPOINT_PERMISSIONS = {
    ('bookings.detail', 'POST'): 'pay.manage',
    ('bookings.correct_price', 'GET'): 'pay.manage',
    ('bookings.correct_price', 'POST'): 'pay.manage',
    ('bookings.save_crew', 'POST'): 'pay.manage',
    ('bookings.log_ad_cost', 'POST'): 'finance.manage',
    ('bookings.re_rate', 'POST'): 'pay.manage',
    ('bookings.use_clocked_pay', 'POST'): 'pay.manage',
}


def canonical_role(role):
    """Return a supported role or None. Legacy team is least-privileged."""
    value = (role or '').strip().lower()
    value = LEGACY_ROLE_MAP.get(value, value)
    return value if value in CANONICAL_ROLES else None


def has_permission(role, permission):
    """Fail closed for unknown roles and unknown permissions."""
    canonical = canonical_role(role)
    if not canonical or not permission:
        return False
    return permission in ROLE_PERMISSIONS.get(canonical, frozenset())


def required_permission(endpoint=None, method=None):
    endpoint = endpoint if endpoint is not None else request.endpoint
    method = (method if method is not None else request.method or '').upper()
    return ENDPOINT_PERMISSIONS.get((endpoint, method))


def enforce_current_request():
    """Enforce any IAM rule registered for the current authenticated route."""
    permission = required_permission()
    if permission is None:
        return None
    if not has_permission(session.get('role'), permission):
        abort(403, description='Your account is not permitted to perform this action.')
    return None
