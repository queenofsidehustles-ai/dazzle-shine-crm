"""Production authentication must fail closed at its outer boundary."""
import os
import sys

from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import security


def test_production_rejects_default_session_secret(monkeypatch):
    monkeypatch.setenv('RAILWAY_ENVIRONMENT', 'production')
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'dev-secret-change-me'

    try:
        security.validate_secret(app)
        assert False, 'weak production secret should stop application boot'
    except RuntimeError as exc:
        assert 'at least 32 characters' in str(exc)


def test_production_accepts_long_session_secret(monkeypatch):
    monkeypatch.setenv('RAILWAY_ENVIRONMENT', 'production')
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'a-unique-production-secret-with-32-plus-characters'
    security.validate_secret(app)


def test_login_throttle_uses_proxy_resolved_remote_addr(monkeypatch):
    monkeypatch.delenv('RAILWAY_ENVIRONMENT', raising=False)
    app = Flask(__name__)
    with app.test_request_context(
        '/', environ_base={'REMOTE_ADDR': '203.0.113.7'},
        headers={'X-Forwarded-For': '198.51.100.99, 192.0.2.10'},
    ):
        assert security.client_ip() == '203.0.113.7'
