from types import SimpleNamespace

import pytest
from flask import Flask, session

import auth
import models


class _FakeQuery:
    def __init__(self, user):
        self.user = user

    def get(self, user_id):
        if self.user is None or self.user.id != user_id:
            return None
        return self.user


@pytest.fixture
def app():
    app = Flask(__name__)
    app.secret_key = 'session-invalidation-test'
    return app


def _user(role='dispatcher', active=True, password_hash='hash-v1'):
    return SimpleNamespace(id=7, role=role, active=active, password_hash=password_hash)


def _bind_session(user):
    session['logged_in'] = True
    session['user_id'] = user.id
    session['role'] = user.role
    session['auth_fingerprint'] = auth._auth_fingerprint(user.password_hash)


def _install_user(monkeypatch, user):
    monkeypatch.setattr(models.User, 'query', _FakeQuery(user))


def test_current_account_state_accepts_matching_session(app, monkeypatch):
    user = _user()
    with app.test_request_context('/'):
        _install_user(monkeypatch, user)
        _bind_session(user)
        assert auth.session_matches_current_user() is True


def test_disabling_account_invalidates_existing_session(app, monkeypatch):
    user = _user(active=True)
    with app.test_request_context('/'):
        _install_user(monkeypatch, user)
        _bind_session(user)
        user.active = False
        assert auth.session_matches_current_user() is False


def test_deleting_account_invalidates_existing_session(app, monkeypatch):
    user = _user()
    with app.test_request_context('/'):
        _bind_session(user)
        _install_user(monkeypatch, None)
        assert auth.session_matches_current_user() is False


def test_role_change_invalidates_existing_session(app, monkeypatch):
    user = _user(role='dispatcher')
    with app.test_request_context('/'):
        _install_user(monkeypatch, user)
        _bind_session(user)
        user.role = 'limited'
        assert auth.session_matches_current_user() is False


def test_password_reset_invalidates_existing_session(app, monkeypatch):
    user = _user(password_hash='hash-v1')
    with app.test_request_context('/'):
        _install_user(monkeypatch, user)
        _bind_session(user)
        user.password_hash = 'hash-v2'
        assert auth.session_matches_current_user() is False


def test_legacy_session_without_credential_binding_fails_closed(app, monkeypatch):
    user = _user()
    with app.test_request_context('/'):
        _install_user(monkeypatch, user)
        session['logged_in'] = True
        session['user_id'] = user.id
        session['role'] = user.role
        assert auth.session_matches_current_user() is False


def test_unknown_database_role_invalidates_existing_session(app, monkeypatch):
    user = _user(role='dispatcher')
    with app.test_request_context('/'):
        _install_user(monkeypatch, user)
        _bind_session(user)
        user.role = 'unexpected-role'
        assert auth.session_matches_current_user() is False
