import pytest
from flask import Flask, session

import rbac
from auth import login_required


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
