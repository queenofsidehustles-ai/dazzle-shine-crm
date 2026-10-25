"""Console -> /console/metrics.json: who is on the platform, as JSON.

P1-07 from the 25 Oct operational report: there was no authenticated,
reproducible source for tenant counts. This is tenant_report.compute over the
control plane (what `certify.py tenants` prints), with when it was read and
from which release, and counts beside each list.

Against a real disposable Postgres, with real provisioned companies.
"""
import os
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fresh_postgres
os.environ.update(DATABASE_URL=fresh_postgres.url('akye_console_metrics_test'),
                  SECRET_KEY='console-metrics-test', BASE_DOMAIN='akye.test',
                  FLASK_ENV='development', RAILWAY_GIT_COMMIT_SHA='abc1234' + '0' * 33)

from sqlalchemy import update
from app import create_app
from extensions import db
import control_plane
import provisioning

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


app = create_app()
with app.app_context():
    provisioning.provision('metricsreal', 'Metrics Real', 'real@metrics.test', quiet=True)
    provisioning.provision('metricsold', 'Metrics Old', 'old@metrics.test', quiet=True)
    provisioning.provision('metricstest', 'Metrics Test', 'test@metrics.test', quiet=True)
    db.session.remove()
engine = provisioning._engine()
now = datetime.utcnow()
with engine.begin() as conn:
    o = control_plane.organizations
    conn.execute(update(o).where(o.c.slug == 'metricsold')
                 .values(created_at=now - timedelta(days=30), activated_at=now - timedelta(days=20),
                         subscription_status='active', stripe_subscription_id='sub_x'))
    conn.execute(update(o).where(o.c.slug == 'metricstest').values(is_test=True))

PASSWORD = 'a-real-console-password-1'
control_plane.add_console_user(engine, 'ops@metrics.test', 'Ops', PASSWORD, role='manager')

print('\n1. Signed out, nothing')
r = app.test_client().get('/console/metrics.json')
check(r.status_code in (302, 401, 403) and b'metricsreal' not in r.data,
      f'signed out is sent to sign in ({r.status_code})')

print('\n2. Signed in, the counts')
c = app.test_client()
c.post('/console/login', data={'email': 'ops@metrics.test', 'password': PASSWORD})
r = c.get('/console/metrics.json')
check(r.status_code == 200 and r.is_json, f'JSON ({r.status_code})')
j = r.get_json() or {}
check(j.get('counts', {}).get('by_kind', {}).get('real') == 2
      and j['counts']['by_kind'].get('test') == 1, f'2 real, 1 test ({j.get("counts", {}).get("by_kind")})')
check('metricstest' not in j['real']['status']['active'], 'a test company is not counted as a real one')
check(j['counts']['real']['billing'].get('paying') == 1, 'the one with a live subscription is paying')
check(j['counts']['windows']['last_24h']['signed_up'] == 2,
      'two signed up in the last 24 hours (the test one included, and labelled)')
check(any('metricstest (test)' in s for s in j['windows']['last_24h']['events']['signed_up']),
      'each event says what kind of company it was')
check('signed_up' in j['today_eastern']['events'] and j['today_eastern']['since'].endswith('Z'),
      'a since-midnight-Eastern window, in UTC')
src = j.get('source', {})
check(src.get('read_at') and src.get('commit', '').startswith('abc1234') and 'control plane' in src.get('from', ''),
      'it says when it was read, from which commit, and from where')
check('@metrics.test' not in r.get_data(as_text=True), 'no email addresses')
check(r.headers.get('Cache-Control') == 'no-store', 'and is never cached')

if failures:
    print(f'\n❌ {len(failures)} failed')
    sys.exit(1)
print('\n✅ The console gives tenant counts as JSON, with where and when they came from.')
