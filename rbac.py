"""Central role and permission policy for tenant CRM users.

IAM-01 requires a written allow/deny matrix for owner, admin, dispatcher,
cleaner and limited roles. This module is the canonical server-side policy.
Unknown roles and permissions fail closed. The legacy ``team`` role is treated
as ``limited`` until an owner deliberately reassigns it.
"""
from flask import abort, request, session

CANONICAL_ROLES = frozenset({'owner', 'admin', 'dispatcher', 'cleaner', 'limited'})
LEGACY_ROLE_MAP = {'team': 'limited'}

ROLE_LABELS = {
    'owner': 'Owner',
    'admin': 'Admin',
    'dispatcher': 'Dispatcher',
    'cleaner': 'Cleaner',
    'limited': 'Limited',
}
ROLE_OPTIONS = (
    ('limited', 'Limited — booking read only'),
    ('cleaner', 'Cleaner — assigned work only'),
    ('dispatcher', 'Dispatcher — bookings and scheduling'),
    ('admin', 'Admin — operations, no finance/pay'),
    ('owner', 'Owner — full access'),
)

ROLE_PERMISSIONS = {
    'owner': frozenset({
        'booking.read', 'booking.create', 'booking.manage',
        'dispatch.manage', 'customer.communicate',
        'lead.read', 'lead.manage',
        'messages.read', 'messages.send', 'messages.templates.manage',
        'checklist.manage',
        'pay.manage', 'finance.manage', 'users.manage', 'settings.manage',
        'assigned_work.use',
    }),
    'admin': frozenset({
        'booking.read', 'booking.create', 'booking.manage',
        'dispatch.manage', 'customer.communicate', 'assigned_work.use',
        'lead.read', 'lead.manage',
        'messages.read', 'messages.send', 'messages.templates.manage',
        'checklist.manage',
    }),
    'dispatcher': frozenset({
        'booking.read', 'booking.create', 'dispatch.manage',
        'customer.communicate',
        'lead.read', 'lead.manage',
        'messages.read', 'messages.send',
    }),
    'cleaner': frozenset({'assigned_work.use'}),
    'limited': frozenset({'booking.read'}),
}

ENDPOINT_PERMISSIONS = {
    ('admin.dashboard', 'GET'): 'booking.read',
    ('bookings.index', 'GET'): 'booking.read',
    ('bookings.clients', 'GET'): 'booking.read',
    ('bookings.client_detail', 'GET'): 'booking.read',
    ('bookings.calendar', 'GET'): 'booking.read',
    ('bookings.detail', 'GET'): 'booking.read',
    ('bookings.confirmation_preview', 'GET'): 'booking.read',
    ('bookings.new', 'GET'): 'booking.create',
    ('bookings.new', 'POST'): 'booking.create',
    ('bookings.price_preview', 'GET'): 'booking.create',
    ('bookings.reschedule', 'POST'): 'dispatch.manage',
    ('bookings.notify_moved', 'POST'): 'dispatch.manage',
    ('bookings.broadcast', 'POST'): 'dispatch.manage',
    ('bookings.send_crew', 'POST'): 'dispatch.manage',
    ('bookings.send_confirmation', 'POST'): 'customer.communicate',
    ('bookings.email_customer', 'GET'): 'customer.communicate',
    ('bookings.email_customer', 'POST'): 'customer.communicate',
    ('bookings.rebuild_clients', 'POST'): 'booking.manage',
    ('bookings.detail', 'POST'): 'pay.manage',
    ('bookings.correct_price', 'GET'): 'pay.manage',
    ('bookings.correct_price', 'POST'): 'pay.manage',
    ('bookings.notify_pay', 'POST'): 'pay.manage',
    ('bookings.save_crew', 'POST'): 'pay.manage',
    ('bookings.send_payment_link_route', 'POST'): 'finance.manage',
    ('bookings.resend_deposit_receipt', 'POST'): 'finance.manage',
    ('bookings.log_ad_cost', 'POST'): 'finance.manage',
    ('bookings.re_rate', 'POST'): 'pay.manage',
    ('bookings.use_clocked_pay', 'POST'): 'pay.manage',

    ('leads.index', 'GET'): 'lead.read',
    ('leads.detail', 'GET'): 'lead.read',
    ('leads.new_quote', 'GET'): 'lead.manage',
    ('leads.new_quote', 'POST'): 'lead.manage',
    ('leads.checklist_json', 'GET'): 'lead.manage',
    ('leads.detail', 'POST'): 'lead.manage',
    ('leads.convert', 'POST'): 'lead.manage',

    ('messages.sent_log', 'GET'): 'messages.read',
    ('messages.inbox', 'GET'): 'messages.read',
    ('messages.thread', 'GET'): 'messages.read',
    ('messages.fill_template', 'GET'): 'messages.send',
    ('messages.toggle_lang', 'POST'): 'messages.send',
    ('messages.send', 'POST'): 'messages.send',
    ('messages.templates', 'GET'): 'messages.templates.manage',
    ('messages.templates', 'POST'): 'messages.templates.manage',
    ('messages.delete_template', 'POST'): 'messages.templates.manage',

    ('workorders.templates', 'GET'): 'checklist.manage',
    ('workorders.new_template', 'GET'): 'checklist.manage',
    ('workorders.new_template', 'POST'): 'checklist.manage',
    ('workorders.edit_template', 'GET'): 'checklist.manage',
    ('workorders.edit_template', 'POST'): 'checklist.manage',
    ('workorders.delete_template', 'POST'): 'checklist.manage',
    ('workorders.send_workorder', 'POST'): 'dispatch.manage',
}


def canonical_role(role):
    """Return a supported role or None. Legacy team is least-privileged."""
    value = (role or '').strip().lower()
    value = LEGACY_ROLE_MAP.get(value, value)
    return value if value in CANONICAL_ROLES else None


def role_label(role):
    """Human label for a stored role; unknown values are visibly invalid."""
    canonical = canonical_role(role)
    return ROLE_LABELS.get(canonical, 'Unknown role')


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
    """Enforce IAM for every authenticated back-office route.

    Owner keeps full legacy access. Every other role is fail-closed unless the
    endpoint/method is explicitly classified above. This prevents a newly added
    route from silently becoming available to every authenticated account.
    """
    role = canonical_role(session.get('role'))
    if role == 'owner':
        return None

    permission = required_permission()
    if permission is None or not has_permission(role, permission):
        abort(403, description='Your account is not permitted to perform this action.')
    return None
