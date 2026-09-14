import pytest
from flask import Flask, session

import rbac
from auth import login_required
from navigation import sidebar


def _app(endpoint, method='GET'):
    app = Flask(__name__)
    app.secret_key = 'iam-operational-test-secret'
    app.add_url_rule('/admin/login', endpoint='admin.login', view_func=lambda: 'login')

    def protected():
        return 'allowed'

    app.add_url_rule('/protected', endpoint=endpoint,
                     view_func=login_required(protected), methods=[method])
    return app


def _status(role, endpoint, method='GET'):
    client = _app(endpoint, method).test_client()
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['role'] = role
    return client.open('/protected', method=method).status_code


def _nav_endpoints(role):
    app = Flask(__name__)
    app.secret_key = 'iam-navigation-test-secret'
    with app.test_request_context('/'):
        session['logged_in'] = True
        session['role'] = role
        return {
            item['endpoint']
            for section in sidebar(role=role)
            for item in section['items']
        }


def _nav_tabs(role, endpoint):
    app = Flask(__name__)
    app.secret_key = 'iam-navigation-test-secret'
    with app.test_request_context('/'):
        session['logged_in'] = True
        session['role'] = role
        for section in sidebar(role=role):
            for item in section['items']:
                if item['endpoint'] == endpoint:
                    return {tab['endpoint'] for tab in item['tabs']}
    return set()


@pytest.mark.parametrize('role', ['owner', 'admin', 'dispatcher'])
def test_operational_roles_can_read_leads(role):
    assert _status(role, 'leads.index') == 200
    assert _status(role, 'leads.detail') == 200


@pytest.mark.parametrize('role', ['owner', 'admin', 'dispatcher'])
def test_operational_roles_can_manage_non_destructive_lead_workflow(role):
    assert _status(role, 'leads.new_quote') == 200
    assert _status(role, 'leads.new_quote', 'POST') == 200
    assert _status(role, 'leads.detail', 'POST') == 200
    assert _status(role, 'leads.convert', 'POST') == 200


@pytest.mark.parametrize('role', ['cleaner', 'limited', 'team', 'unknown'])
def test_non_operational_roles_cannot_read_or_manage_leads(role):
    assert _status(role, 'leads.index') == 403
    assert _status(role, 'leads.detail', 'POST') == 403


def test_destructive_lead_delete_stays_owner_only_by_default():
    assert rbac.required_permission('leads.delete', 'POST') is None
    assert _status('owner', 'leads.delete', 'POST') == 200
    assert _status('admin', 'leads.delete', 'POST') == 403
    assert _status('dispatcher', 'leads.delete', 'POST') == 403


@pytest.mark.parametrize('role', ['owner', 'admin', 'dispatcher'])
def test_operational_roles_can_read_messages(role):
    assert _status(role, 'messages.inbox') == 200
    assert _status(role, 'messages.sent_log') == 200
    assert _status(role, 'messages.thread') == 200


@pytest.mark.parametrize('role', ['owner', 'admin', 'dispatcher'])
def test_operational_roles_can_reply_and_change_thread_language(role):
    assert _status(role, 'messages.send', 'POST') == 200
    assert _status(role, 'messages.toggle_lang', 'POST') == 200
    assert _status(role, 'messages.fill_template') == 200


@pytest.mark.parametrize('role', ['cleaner', 'limited', 'team', 'unknown'])
def test_non_operational_roles_cannot_read_or_send_messages(role):
    assert _status(role, 'messages.inbox') == 403
    assert _status(role, 'messages.send', 'POST') == 403


@pytest.mark.parametrize('role', ['owner', 'admin'])
def test_only_owner_and_admin_can_manage_message_templates(role):
    assert _status(role, 'messages.templates') == 200
    assert _status(role, 'messages.templates', 'POST') == 200
    assert _status(role, 'messages.delete_template', 'POST') == 200


@pytest.mark.parametrize('role', ['dispatcher', 'cleaner', 'limited', 'team', 'unknown'])
def test_dispatcher_and_lower_roles_cannot_manage_message_templates(role):
    assert _status(role, 'messages.templates') == 403
    assert _status(role, 'messages.delete_template', 'POST') == 403


def test_applicant_background_check_request_stays_owner_only():
    assert rbac.required_permission('messages.request_bgcheck', 'POST') is None
    assert _status('owner', 'messages.request_bgcheck', 'POST') == 200
    assert _status('admin', 'messages.request_bgcheck', 'POST') == 403
    assert _status('dispatcher', 'messages.request_bgcheck', 'POST') == 403


@pytest.mark.parametrize('endpoint,method', [
    ('staff.index', 'GET'),
    ('staff.edit', 'POST'),
    ('commercial.index', 'GET'),
    ('commercial.detail', 'POST'),
    ('commercial.mark_first_paid', 'POST'),
    ('quotes.index', 'GET'),
    ('quotes.new', 'POST'),
    ('quotes.send_quote', 'POST'),
])
def test_pay_hiring_and_commercial_surfaces_remain_owner_only(endpoint, method):
    assert rbac.required_permission(endpoint, method) is None
    assert _status('owner', endpoint, method) == 200
    assert _status('admin', endpoint, method) == 403
    assert _status('dispatcher', endpoint, method) == 403


@pytest.mark.parametrize('role', ['admin', 'dispatcher'])
def test_operational_navigation_matches_server_grants(role):
    endpoints = _nav_endpoints(role)
    assert {'admin.dashboard', 'bookings.index', 'bookings.calendar',
            'bookings.clients', 'messages.inbox', 'leads.index'} <= endpoints
    assert 'money.pnl' not in endpoints
    assert 'settings.business' not in endpoints
    assert 'places_finder.dashboard' not in endpoints
    assert 'contractors.team' not in endpoints
    assert 'contractors.applications' not in endpoints
    if role == 'admin':
        assert 'workorders.templates' in endpoints
    else:
        assert 'workorders.templates' not in endpoints


def test_dispatcher_cannot_see_message_template_tab_but_admin_can():
    assert 'messages.templates' not in _nav_tabs('dispatcher', 'messages.inbox')
    assert 'messages.templates' in _nav_tabs('admin', 'messages.inbox')


@pytest.mark.parametrize('role', ['limited', 'team'])
def test_limited_navigation_contains_only_explicit_read_workspace(role):
    endpoints = _nav_endpoints(role)
    assert {'admin.dashboard', 'bookings.index', 'bookings.calendar',
            'bookings.clients'} <= endpoints
    assert 'messages.inbox' not in endpoints
    assert 'leads.index' not in endpoints
    assert 'money.pnl' not in endpoints
    assert 'settings.business' not in endpoints
    assert 'contractors.team' not in endpoints
    assert 'workorders.templates' not in endpoints


def test_cleaner_has_no_back_office_navigation_without_explicit_get_grant():
    assert _nav_endpoints('cleaner') == set()


def test_request_session_role_cannot_be_elevated_by_navigation_argument():
    app = Flask(__name__)
    app.secret_key = 'iam-navigation-test-secret'
    with app.test_request_context('/'):
        session['logged_in'] = True
        session['role'] = 'dispatcher'
        endpoints = {
            item['endpoint']
            for section in sidebar(role='owner')
            for item in section['items']
        }
    assert 'money.pnl' not in endpoints
    assert 'settings.business' not in endpoints
    assert 'messages.inbox' in endpoints


@pytest.mark.parametrize('role', ['owner', 'admin'])
def test_owner_and_admin_can_manage_checklist_templates(role):
    assert _status(role, 'workorders.templates') == 200
    assert _status(role, 'workorders.new_template') == 200
    assert _status(role, 'workorders.new_template', 'POST') == 200
    assert _status(role, 'workorders.edit_template', 'POST') == 200
    assert _status(role, 'workorders.delete_template', 'POST') == 200


@pytest.mark.parametrize('role', ['dispatcher', 'cleaner', 'limited', 'team', 'unknown'])
def test_non_admin_roles_cannot_manage_checklist_templates(role):
    assert _status(role, 'workorders.templates') == 403
    assert _status(role, 'workorders.edit_template', 'POST') == 403


@pytest.mark.parametrize('role', ['owner', 'admin', 'dispatcher'])
def test_dispatch_roles_can_send_existing_workorder(role):
    assert _status(role, 'workorders.send_workorder', 'POST') == 200


@pytest.mark.parametrize('role', ['cleaner', 'limited', 'team', 'unknown'])
def test_non_dispatch_roles_cannot_send_workorder(role):
    assert _status(role, 'workorders.send_workorder', 'POST') == 403


def test_invoice_back_office_list_remains_owner_only():
    assert rbac.required_permission('invoices.index', 'GET') is None
    assert _status('owner', 'invoices.index') == 200
    assert _status('admin', 'invoices.index') == 403
    assert _status('dispatcher', 'invoices.index') == 403
