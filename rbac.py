"""Central role and permission policy for tenant CRM users.

IAM-01 requires a written allow/deny matrix for owner, admin, dispatcher,
cleaner and limited roles. This module is the canonical server-side policy.
Unknown roles and permissions fail closed. The legacy ``team`` role is treated
as ``limited`` until an owner deliberately reassigns it.
"""
from flask import abort, request, session

CANONICAL_ROLES = frozenset({'owner', 'admin', 'dispatcher', 'sales', 'cleaner', 'limited'})
LEGACY_ROLE_MAP = {'team': 'limited'}

ROLE_LABELS = {
    'owner': 'Owner',
    'admin': 'Admin',
    'dispatcher': 'Dispatcher',
    'sales': 'Sales',
    'cleaner': 'Cleaner',
    'limited': 'Limited',
}
ROLE_OPTIONS = (
    ('limited', 'Limited — booking read only'),
    ('cleaner', 'Cleaner — assigned work only'),
    ('dispatcher', 'Dispatcher — bookings and scheduling'),
    ('sales', 'Sales — finding and working leads only'),
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
        'assigned_work.use', 'account.manage',
        'prospect.work',
    }),
    'admin': frozenset({
        'booking.read', 'booking.create', 'booking.manage',
        'dispatch.manage', 'customer.communicate', 'assigned_work.use',
        'lead.read', 'lead.manage',
        'messages.read', 'messages.send', 'messages.templates.manage',
        'checklist.manage', 'account.manage',
    }),
    'dispatcher': frozenset({
        'booking.read', 'booking.create', 'dispatch.manage',
        'customer.communicate',
        'lead.read', 'lead.manage',
        'messages.read', 'messages.send', 'account.manage',
    }),
    # Every role gets account.manage, owner included above -- it is a login
    # managing itself, which has nothing to do with what that login is
    # otherwise allowed to touch.
    # Somebody whose whole job is finding business: the call list, searching
    # for businesses, calling, emailing and walking them through -- and
    # nothing else. No bookings, no customers, no inbox (which is every
    # customer's and cleaner's texts), no money. Quoting stays with the owner.
    'sales': frozenset({'prospect.work', 'account.manage'}),
    'cleaner': frozenset({'assigned_work.use', 'account.manage'}),
    'limited': frozenset({'booking.read', 'account.manage'}),
}

ENDPOINT_PERMISSIONS = {
    ('account.my_account', 'GET'): 'account.manage',
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
    # Find leads -- the prospecting module, end to end. Its own permission
    # rather than lead.read/lead.manage (website leads and quotes) so a Sales
    # login can have all of this and none of that. Deleting a lead stays
    # owner-only below.
    ('places_finder.dashboard', 'GET'): 'prospect.work',
    ('places_finder.search', 'POST'): 'prospect.work',
    ('places_finder.import_selected', 'POST'): 'prospect.work',
    ('places_finder.call_sheet', 'GET'): 'prospect.work',
    ('places_finder.log_call', 'POST'): 'prospect.work',
    ('places_finder.update_status', 'POST'): 'prospect.work',
    ('places_finder.snooze', 'POST'): 'prospect.work',
    ('places_finder.send_outreach', 'POST'): 'prospect.work',
    ('places_finder.export_csv', 'GET'): 'prospect.work',
    ('places_finder.lead_page', 'GET'): 'prospect.work',
    ('places_finder.edit_lead', 'POST'): 'prospect.work',
    ('places_finder.set_kind', 'POST'): 'prospect.work',
    ('places_finder.add_by_hand', 'POST'): 'prospect.work',
    ('places_finder.book_walkthrough', 'POST'): 'prospect.work',
    ('places_finder.save_walkthrough', 'POST'): 'prospect.work',

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

# Endpoints that stay owner-only by default rather than by a granted
# permission: nobody has asked for admin/dispatcher/cleaner/limited to reach
# these yet, and money (commercial, invoices), hiring/pay (staff) and a
# destructive or PII-adjacent action (deleting a lead, re-requesting someone's
# background check) are exactly the surfaces where "unclassified defers to
# route-local authority" is the wrong default. Deliberately not entered into
# ENDPOINT_PERMISSIONS: that table grants a permission a role can hold, and no
# non-owner role holds one for any of these — a dedicated set says so directly
# rather than by omission, and keeps `required_permission` honest about there
# being no permission-based grant here at all.
OWNER_ONLY_ENDPOINTS = frozenset({
    ('leads.delete', 'POST'),
    ('places_finder.delete', 'POST'),
    ('messages.request_bgcheck', 'POST'),
    ('staff.index', 'GET'),
    ('staff.edit', 'POST'),
    ('commercial.index', 'GET'),
    ('commercial.detail', 'POST'),
    ('commercial.mark_first_paid', 'POST'),
    ('quotes.index', 'GET'),
    ('quotes.new', 'POST'),
    ('quotes.send_quote', 'POST'),
    ('invoices.index', 'GET'),
    # Contractor payouts: real money out (a Stripe transfer, or a manual
    # payment recorded as paid). Route-decorator-only here would repeat the
    # exact gap this set exists to close for staff/hiring/commercial — moved
    # money is at least as sensitive as those.
    ('contractors.pay_contractor', 'POST'),
    ('contractors.pay_manual', 'POST'),
    # Business data export: a full customer/job/worker CSV is the same class
    # of surface as the ones above, even though nothing here moves money.
    ('settings.export', 'GET'),
    ('settings.export_customers_csv', 'GET'),
    ('settings.export_jobs_csv', 'GET'),
    ('settings.export_workers_csv', 'GET'),
    # Migration Toolbox: bulk-creates real team and customer records (and,
    # for team, sends real invite emails) from an uploaded file -- the same
    # class of surface as a hand-typed hire or a customer export, at bulk
    # scale.
    ('migration.index', 'GET'),
    ('migration.team', 'GET'),
    ('migration.team', 'POST'),
    ('migration.clients', 'GET'),
    ('migration.clients', 'POST'),
})


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


# Roles for which "not in the matrix" means no, not "ask the route". The older
# roles defer to route-local checks on unclassified pages because most of the
# app predates this matrix; a role created to reach one module only cannot
# inherit that, or "prospecting only" would mean "prospecting, and every
# unclassified form in the app" -- deleting bookings, hiring, discounts.
FAIL_CLOSED_ROLES = frozenset({'sales'})

# What such a role may still reach unclassified: managing its own login, and
# the few things every back-office page offers -- feedback, the brand lens,
# a city switch, signing out.
UNCLASSIFIED_ALLOWED = frozenset({
    'feedback.send', 'settings.switch_brand', 'admin.switch_city', 'admin.logout',
})
UNCLASSIFIED_ALLOWED_PREFIXES = ('account.',)


def _unclassified_allowed(endpoint):
    endpoint = endpoint or ''
    return (endpoint in UNCLASSIFIED_ALLOWED
            or endpoint.startswith(UNCLASSIFIED_ALLOWED_PREFIXES))


# Where a role lands when it opens the back office. The dashboard is bookings
# and money; a role that may not see it would otherwise sign in to a refusal.
ROLE_HOME = {'sales': 'places_finder.dashboard'}


def enforce_current_request():
    """Enforce IAM on routes deliberately classified in the central matrix.

    ``login_required`` is the authentication boundary used by a large legacy
    route surface. Unclassified routes retain their existing authorization
    contract (including ``owner_required`` and route-local checks); treating
    absence from this incremental matrix as an implicit deny would lock every
    non-owner out of unrelated product surfaces. A recognised role is
    therefore deferred to that route-local authority for anything not in
    either ``ENDPOINT_PERMISSIONS`` or ``OWNER_ONLY_ENDPOINTS``.

    A missing or unrecognised role is never deferred, classified or not:
    there is no route-local authority to defer to when the session itself
    does not name one of the five roles this application knows, so that
    case fails closed here rather than falling through as an implicit
    allow.
    """
    role = canonical_role(session.get('role'))
    if role == 'owner':
        return None
    if role is None:
        abort(403, description='Your account is not permitted to perform this action.')
    if (request.endpoint, (request.method or '').upper()) in OWNER_ONLY_ENDPOINTS:
        abort(403, description='Your account is not permitted to perform this action.')

    permission = required_permission()
    if permission is None:
        if role in FAIL_CLOSED_ROLES and not _unclassified_allowed(request.endpoint):
            abort(403, description='Your account is not permitted to perform this action.')
        return None
    if not has_permission(role, permission):
        home = ROLE_HOME.get(role)
        if (home and request.endpoint == 'admin.dashboard'
                and (request.method or '').upper() == 'GET'):
            from flask import redirect, url_for
            return redirect(url_for(home))
        abort(403, description='Your account is not permitted to perform this action.')
    return None
