"""Nana's use is counted, so "nobody used it" can be told from "nobody saw it".

The console's Nana page used to show only the offers that wait for a button to
be pressed. Most of what an owner does with Nana is typing and reading, none of
which is an offer, so a company could talk to her all week and the page would
still say nobody had. This holds the counter that fills the gap:

  * one row per company, day and kind, bumped in place; two messages in the
    same moment are both counted;
  * counting can never be the reason an answer fails;
  * a message to the setup chat and one to Ask Nana are counted apart, for the
    right company, from the real routes;
  * the console lists who has used her, and marks test and demo companies.

Runs against a real PostgreSQL: the control plane lives in the `public` schema.
"""
import inspect
import os
import secrets
import sys
import threading
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


def postgres_url():
    from sqlalchemy import create_engine, text
    for candidate in (os.environ.get('TEST_POSTGRES_URL'),
                      'postgresql://app_user:localtest@127.0.0.1:5432/postgres',
                      f'postgresql://{os.environ.get("USER", "postgres")}@localhost/postgres'):
        if not candidate:
            continue
        try:
            e = create_engine(candidate)
            with e.connect() as c:
                c.execute(text('SELECT 1'))
            return candidate
        except Exception:
            continue
    return None


PG = postgres_url()
if not PG:
    print('\n  ⚠️  SKIPPED: no PostgreSQL server found.')
    sys.exit(0)

from sqlalchemy import create_engine, text

DB = 'dsm_nana_usage_test'
admin = create_engine(PG, isolation_level='AUTOCOMMIT')
with admin.connect() as conn:
    conn.execute(text(f'DROP DATABASE IF EXISTS {DB} WITH (FORCE)'))
    conn.execute(text(f'CREATE DATABASE {DB}'))
os.environ.update(DATABASE_URL=f'{PG.rsplit("/", 1)[0]}/{DB}', SECRET_KEY='nana-usage',
                  BASE_DOMAIN='akyehq.test', SIGNUPS_OPEN='1',
                  ANTHROPIC_API_KEY='sk-ant-test')
for k in ('ADMIN_USER', 'ADMIN_PASS', 'CANONICAL_HOST'):
    os.environ.pop(k, None)

import notifications
notifications.send_email = lambda *a, **k: (True, 'stub')
notifications.send_sms = lambda *a, **k: (True, 'stub')
from app import create_app
import assistant
import auth
import control_plane
import provisioning
import setup_assistant
import tenancy
from extensions import db

app = create_app()
TAG = secrets.token_hex(3)
NOW = datetime.utcnow()

with app.app_context():
    engine = provisioning._engine()
    control_plane.ensure_table(engine)


def rows(slug=None):
    q = 'select org_slug, kind, messages, day from public.nana_usage'
    args = {}
    if slug:
        q += ' where org_slug = :s'; args['s'] = slug
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(q + ' order by id'), args).mappings()]


print('\n1. One row per company, day and kind, counted in place')
a = f'usea{TAG}'
check(control_plane.note_nana_use(engine, a, 'setup', NOW), 'a message is counted')
control_plane.note_nana_use(engine, a, 'setup', NOW)
control_plane.note_nana_use(engine, a, 'ask', NOW)
r = rows(a)
check(len(r) == 2, f'two rows, not three ({len(r)})')
check({x['kind']: x['messages'] for x in r} == {'setup': 2, 'ask': 1},
      'setup and ask are counted apart')
control_plane.note_nana_use(engine, a, 'setup', NOW + timedelta(days=1))
check(len(rows(a)) == 3, 'a new day is a new row')

print('\n2. Two at once are both counted')
b = f'useb{TAG}'
def hit():
    control_plane.note_nana_use(engine, b, 'ask', NOW)
threads = [threading.Thread(target=hit) for _ in range(20)]
[t.start() for t in threads]; [t.join() for t in threads]
check(rows(b)[0]['messages'] == 20 and len(rows(b)) == 1,
      f'20 simultaneous messages: one row, 20 counted ({[x["messages"] for x in rows(b)]})')

print('\n3. Counting can never be the reason an answer fails')
check(control_plane.note_nana_use(engine, '', 'ask') is False, 'no company: nothing counted, no error')
check(control_plane.note_nana_use(engine, 'x', '') is False, 'no kind: nothing counted, no error')
check(control_plane.note_nana_use(None, a, 'ask') is False, 'no database: returns False, does not raise')

print('\n4. The summary: recent use only, newest first, per company')
c = f'usec{TAG}'
control_plane.note_nana_use(engine, c, 'ask', NOW - timedelta(days=60))
control_plane.note_nana_use(engine, a, 'ask', NOW - timedelta(days=3))
summary = {u['slug']: u for u in control_plane.nana_usage_summary(engine, 30, NOW)}
check(c not in summary, 'use 60 days ago is outside the window')
check(summary[a]['setup'] == 3 and summary[a]['ask'] == 2,
      f'a company\'s messages add up across days and kinds ({summary[a]["setup"]}/{summary[a]["ask"]})')
check(list(summary)[0] in (a, b), 'most recent first')

print('\n5. The real routes count, for the right company')
SLUG = f'shop{TAG}'
with app.app_context():
    provisioning.provision(SLUG, 'Shop Co', owner_email=f'shop{TAG}@example.com', quiet=True)
    from models import User
    with tenancy.use_tenant(SLUG):
        u = User(name='Owner', username='owner', role='owner', password_hash='x')
        db.session.add(u)
        db.session.commit()
        UID = u.id
base = f'http://{SLUG}.akyehq.test'
oc = app.test_client()
with oc.session_transaction(base_url=base) as sess:
    sess.update(logged_in=True, role='owner', user_id=UID, user_name='Owner',
                tenant_slug=SLUG, auth_fingerprint=auth._auth_fingerprint('x'))
setup_assistant.ask = lambda text, history=None, opening='': {'say': 'ok', 'cards': []}
assistant.ask = lambda q, history=None: {'say': 'ok'}
r = oc.post('/settings/getting-started/assistant/ask', json={'q': 'hello'}, base_url=base)
check(r.status_code == 200, f'the setup chat answers ({r.status_code})')
r = oc.post('/ask', json={'q': 'how much did I make'}, base_url=base)
check(r.status_code == 200, f'Ask Nana answers ({r.status_code})')
oc.post('/ask', json={'q': 'and last month'}, base_url=base)
mine = {x['kind']: x['messages'] for x in rows(SLUG)}
check(mine == {'setup': 1, 'ask': 2}, f'counted for this company by kind ({mine})')
r = oc.post('/settings/getting-started/assistant/ask', json={'q': ''}, base_url=base)
check({x['kind']: x['messages'] for x in rows(SLUG)}['setup'] == 1,
      'an empty message is not counted')

print('\n6. The console says who has used her, and marks tests')
with app.app_context():
    control_plane.set_test_account(engine, c, True) if control_plane.find(engine, c) else None
    control_plane.create(engine, f'tst{TAG}', 'Tst Co', owner_email=f'tst{TAG}@example.com')
    control_plane.set_test_account(engine, f'tst{TAG}', True)
    control_plane.note_nana_use(engine, f'tst{TAG}', 'ask', NOW)
    import blueprints.console as cons
    view = inspect.unwrap(cons.nana_proposals)
    with app.test_request_context('/console/nana'):
        from flask import request
        request.console_user = {'email': 'op@akyehq.test', 'role': 'owner', 'name': 'Op'}
        html = view()
check('Shop Co' in html and 'Ask Nana' in html, 'the page lists the company that used her')
check('Tst Co' in html and '(test)' in html, 'and marks a test company')
check('1 real company' in html, 'and counts only the real one')

print()
if failures:
    print(f'❌ {len(failures)} failed:')
    for f in failures:
        print('   -', f)
    sys.exit(1)
print('✅ Nana\'s use is counted, per company, without ever failing an answer.')
