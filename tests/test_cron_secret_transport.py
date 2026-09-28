import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from flask import Flask

import security

ROOT = Path(__file__).resolve().parents[1]
CRON_PATHS = sorted(security.QUERY_SECRET_FORBIDDEN_PATHS)


def run_probe(path, header=None):
    """Exercise one real cron request in a fresh interpreter."""
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ)
        env.update({
            'DATABASE_URL': f'sqlite:///{tmp}/cron-secret.db',
            'SECRET_KEY': 'test',
            'REMINDER_API_KEY': 'cron-secret',
        })
        code = f"""
from app import create_app
from extensions import db
app = create_app()
with app.app_context():
    db.create_all()
client = app.test_client()
headers = {header!r}
r = client.post({path!r}, headers=headers or {{}})
print(r.status_code)
"""
        proc = subprocess.run(
            [sys.executable, '-c', code],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        return int(proc.stdout.strip().splitlines()[-1])


def build_transport_guard_app():
    app = Flask(__name__)
    app.before_request(security.reject_query_credentials)
    for idx, path in enumerate(CRON_PATHS):
        app.add_url_rule(
            path,
            endpoint=f'cron_{idx}',
            view_func=lambda: ('ok', 200),
            methods=['POST'],
        )
    return app


@pytest.mark.parametrize('path', CRON_PATHS)
def test_every_cron_route_rejects_query_string_secret(path):
    client = build_transport_guard_app().test_client()
    assert client.post(f'{path}?api_key=cron-secret').status_code == 403


@pytest.mark.parametrize('path', CRON_PATHS)
def test_header_transport_is_not_blocked_by_query_guard(path):
    client = build_transport_guard_app().test_client()
    assert client.post(path, headers={'X-Api-Key': 'cron-secret'}).status_code == 200


def test_reminders_accepts_header_secret_in_real_app():
    assert run_probe('/api/reminders', {'X-Api-Key': 'cron-secret'}) == 200


def test_reminders_rejects_query_string_secret_in_real_app():
    assert run_probe('/api/reminders?api_key=cron-secret') == 403


def test_charge_balances_accepts_header_secret_in_real_app():
    assert run_probe('/api/charge-balances', {'X-Api-Key': 'cron-secret'}) == 200


def test_charge_balances_rejects_query_string_secret_in_real_app():
    assert run_probe('/api/charge-balances?api_key=cron-secret') == 403


def test_missing_and_wrong_header_still_fail_in_real_app():
    assert run_probe('/api/reminders') == 403
    assert run_probe('/api/reminders', {'X-Api-Key': 'wrong'}) == 403
    assert run_probe('/api/charge-balances') == 403
    assert run_probe('/api/charge-balances', {'X-Api-Key': 'wrong'}) == 403
