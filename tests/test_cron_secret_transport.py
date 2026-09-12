import os
import sys
import tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/cron-secret.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['REMINDER_API_KEY'] = 'cron-secret'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db

app = create_app()

with app.app_context():
    db.create_all()

client = app.test_client()


def test_reminders_accepts_header_secret():
    r = client.post('/api/reminders', headers={'X-Api-Key': 'cron-secret'})
    assert r.status_code == 200


def test_reminders_rejects_query_string_secret():
    r = client.post('/api/reminders?api_key=cron-secret')
    assert r.status_code == 403


def test_reminders_rejects_query_secret_even_with_wrong_header():
    r = client.post(
        '/api/reminders?api_key=cron-secret',
        headers={'X-Api-Key': 'wrong'},
    )
    assert r.status_code == 403


def test_charge_balances_accepts_header_secret():
    r = client.post('/api/charge-balances', headers={'X-Api-Key': 'cron-secret'})
    assert r.status_code == 200


def test_charge_balances_rejects_query_string_secret():
    r = client.post('/api/charge-balances?api_key=cron-secret')
    assert r.status_code == 403


def test_charge_balances_rejects_query_secret_even_with_wrong_header():
    r = client.post(
        '/api/charge-balances?api_key=cron-secret',
        headers={'X-Api-Key': 'wrong'},
    )
    assert r.status_code == 403


def test_missing_and_wrong_header_still_fail():
    assert client.post('/api/reminders').status_code == 403
    assert client.post('/api/reminders', headers={'X-Api-Key': 'wrong'}).status_code == 403
    assert client.post('/api/charge-balances').status_code == 403
    assert client.post('/api/charge-balances', headers={'X-Api-Key': 'wrong'}).status_code == 403
