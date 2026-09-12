import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_probe(path, header=None):
    """Exercise one cron request in a fresh interpreter.

    Several legacy test modules execute application setup at import time and
    monkeypatch notification functions before importing ``app``. Importing the
    application here in pytest's own process would therefore contaminate their
    module cache and make unrelated tests order-dependent. A short subprocess
    gives this security check a clean application instance every time.
    """
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


def test_reminders_accepts_header_secret():
    assert run_probe('/api/reminders', {'X-Api-Key': 'cron-secret'}) == 200


def test_reminders_rejects_query_string_secret():
    assert run_probe('/api/reminders?api_key=cron-secret') == 403


def test_reminders_rejects_query_secret_even_with_wrong_header():
    assert run_probe(
        '/api/reminders?api_key=cron-secret',
        {'X-Api-Key': 'wrong'},
    ) == 403


def test_charge_balances_accepts_header_secret():
    assert run_probe('/api/charge-balances', {'X-Api-Key': 'cron-secret'}) == 200


def test_charge_balances_rejects_query_string_secret():
    assert run_probe('/api/charge-balances?api_key=cron-secret') == 403


def test_charge_balances_rejects_query_secret_even_with_wrong_header():
    assert run_probe(
        '/api/charge-balances?api_key=cron-secret',
        {'X-Api-Key': 'wrong'},
    ) == 403


def test_missing_and_wrong_header_still_fail():
    assert run_probe('/api/reminders') == 403
    assert run_probe('/api/reminders', {'X-Api-Key': 'wrong'}) == 403
    assert run_probe('/api/charge-balances') == 403
    assert run_probe('/api/charge-balances', {'X-Api-Key': 'wrong'}) == 403
