"""The back office menu, in one place.

The sidebar used to be thirty-one links, each carrying its own hand-written
`active if request.endpoint == ...` expression. Every page was a peer of every
other page, so one idea — money, or settings, or the things you send people —
was spread across five entries and the menu didn't fit on a laptop screen.

Here a section is one sidebar link, and the pages inside it are tabs shown under
the page title. Nothing was deleted and no URL changed: a page that used to be
its own menu entry is now a tab, and its old address still works.

Adding a page means adding a line here, not editing the sidebar template and
inventing another active-state expression.
"""

# A section is: (endpoint, icon, label, owner_only, tabs)
# A tab is:     (endpoint, label, owner_only)
#
# `endpoint` is where the sidebar link goes. When a section has tabs, that is
# the first tab. Everything is matched on Flask endpoint names, so a renamed
# route breaks the menu loudly in tests rather than quietly in production.

SECTIONS = [
    ('Dashboard', [
        ('admin.dashboard', '🏠', 'Dashboard', False, []),
    ]),

    ('Jobs & Schedule', [
        ('bookings.index', '📋', 'Bookings', False, [
            ('bookings.index', 'All jobs', False),
            ('invoices.index', 'Invoices', False),
        ]),
        ('bookings.calendar', '📅', 'Calendar', False, []),
        ('bookings.clients', '👥', 'Clients', False, []),
        ('messages.inbox', '💬', 'Messages', False, [
            ('messages.inbox', 'Inbox', False),
            ('messages.sent_log', 'Sent log', False),
            ('messages.templates', 'Text templates', False),
        ]),
    ]),

    ('Get Customers', [
        ('leads.index', '💡', 'Leads', False, [
            ('leads.index', 'Website leads', False),
            ('lsa.index', 'Google Ads leads', False),
        ]),
        ('places_finder.dashboard', '🏢', 'Commercial', False, [
            ('places_finder.dashboard', 'Find leads', False),
            ('commercial.index', 'Accounts', False),
            ('quotes.index', 'Quotes', False),
        ]),
        ('discounts.index', '🏷️', 'Discounts', False, []),
    ]),

    ('My Team', [
        ('contractors.team', '🧹', 'Team', False, [
            ('contractors.team', 'Cleaners', False),
            ('team.availability', 'Availability', True),
            ('team.broadcast', 'Message the team', True),
        ]),
        ('contractors.applications', '📥', 'Hiring', False, [
            ('contractors.applications', 'Applications', False),
            ('interviews.admin_interviews', 'Interviews', False),
        ]),
    ]),

    ('Money', [
        ('money.pnl', '📈', 'Money', True, [
            ('money.pnl', 'Profit & Loss', True),
            ('admin.reports', 'Trends', True),
            ('money.expenses', 'Expenses', True),
            ('money.job_economics', 'Job economics', True),
            ('contractors.payroll', 'Payroll', True),
            ('money.tax_forms', '1099 & W-9', True),
            ('commissions.index', 'VA commissions', True),
        ]),
    ]),

    ('Toolkit', [
        ('workorders.templates', '✅', 'Checklists', False, []),
        ('sops.index', '📖', 'SOP Library', False, []),
        ('content.index', '✨', 'Content Studio', False, []),
        ('email_templates.index', '✉️', 'Templates', False, [
            ('email_templates.index', 'Emails', False),
            ('scripts.index', 'Call scripts & outreach', False),
            ('messages.templates', 'Text templates', False),
        ]),
    ]),

    ('Setup', [
        ('settings.pricing', '⚙️', 'Settings', True, [
            ('settings.pricing', 'Pricing', True),
            ('settings.business', 'Business', True),
            ('settings.commercial', 'Commercial brand', True),
            ('settings.connections', 'Connections', True),
            ('settings.automations_page', 'Automations', True),
            ('team_logins.index', 'Team logins', True),
        ]),
    ]),
]

# Endpoints that belong to a section without being one of its tabs — detail
# pages, edit forms, the drawer behind a list. They keep the right sidebar item
# lit and the right tab bar on screen instead of dropping the menu back to
# nothing the moment you open a record.
BELONGS_TO = {
    'bookings.detail': 'bookings.index',
    'bookings.new': 'bookings.index',
    'bookings.dispute_evidence': 'bookings.index',
    'bookings.correct_price': 'bookings.index',
    'bookings.confirmation_preview': 'bookings.index',
    'bookings.client_detail': 'bookings.clients',
    'invoices.view': 'invoices.index',
    'messages.thread': 'messages.inbox',
    'leads.detail': 'leads.index',
    'lsa.import_csv': 'lsa.index',
    'lsa.preview': 'lsa.index',
    'commercial.detail': 'commercial.index',
    'commercial.convert': 'commercial.index',
    'commercial.calculator': 'commercial.index',
    'quotes.new': 'quotes.index',
    'quotes.detail': 'quotes.index',
    'contractors.staff_detail': 'contractors.team',
    'contractors.training_guide': 'contractors.team',
    'contractors.onboarding_hub': 'contractors.team',
    'contractors.application_detail': 'contractors.applications',
    'contractors.pay_statement': 'contractors.payroll',
    'interviews.review_interview': 'interviews.admin_interviews',
    'interviews.offer_preview': 'interviews.admin_interviews',
    'staff.index': 'contractors.team',
    'staff.new': 'contractors.team',
    'staff.edit': 'contractors.team',
    'scripts.new': 'scripts.index',
    'scripts.edit': 'scripts.index',
    'sops.edit': 'sops.index',
    'sops.new': 'sops.index',
    'email_templates.edit': 'email_templates.index',
    'workorders.edit_template': 'workorders.templates',
    'workorders.new_template': 'workorders.templates',
    'discounts.new': 'discounts.index',
    'discounts.edit': 'discounts.index',
    'commissions.settings': 'commissions.index',
    'money.export_csv': 'money.pnl',
    'money.sync_fees': 'money.pnl',
    'money.add_expense': 'money.expenses',
    'money.edit_expense': 'money.expenses',
    'settings.setup': 'settings.pricing',
}


def _is_owner(role):
    return (role or 'owner') == 'owner'


def sidebar(role='owner'):
    """The menu to draw, already filtered to what this person may see."""
    out = []
    for heading, items in SECTIONS:
        visible = [
            {'endpoint': ep, 'icon': icon, 'label': label,
             'tabs': [{'endpoint': t[0], 'label': t[1]}
                      for t in tabs if _is_owner(role) or not t[2]]}
            for ep, icon, label, owner_only, tabs in items
            if _is_owner(role) or not owner_only
        ]
        if visible:
            out.append({'heading': heading, 'items': visible})
    return out


def _resolve(endpoint):
    """The endpoint whose place in the menu we should be showing."""
    return BELONGS_TO.get(endpoint, endpoint)


def active_item(endpoint):
    """Which sidebar item to light up for the page being viewed."""
    target = _resolve(endpoint)
    for _, items in SECTIONS:
        for ep, _icon, _label, _owner, tabs in items:
            if target == ep or any(target == t[0] for t in tabs):
                return ep
    return None


def tabs_for(endpoint, role='owner'):
    """(tabs, active_endpoint) for the page being viewed.

    Empty when the page's section has only one page in it — a lone tab is just
    the page title written twice.
    """
    target = _resolve(endpoint)
    for _, items in SECTIONS:
        for ep, _icon, _label, _owner, tabs in items:
            if not tabs:
                continue
            if target == ep or any(target == t[0] for t in tabs):
                allowed = [{'endpoint': t[0], 'label': t[1]}
                           for t in tabs if _is_owner(role) or not t[2]]
                return (allowed if len(allowed) > 1 else []), target
    return [], target
