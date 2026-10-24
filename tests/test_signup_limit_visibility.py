"""Why a signup was refused is visible, not inferred.

The cap is per address. That is only true if the address recorded is the
visitor's -- behind a proxy it can quietly become the proxy's, and then a rule
meant to stop one script becomes a rule on everybody: three signups from
anywhere and the product is shut for a day. The failure looks exactly like the
rule working, which is the whole problem. It took an owner saying "it blocks my
phone too" to suspect it, and nothing in the product could answer the question.

What this holds:
- the attempts are grouped by address, so one address behind everything shows;
- the cap is readable and no longer three, which refused ordinary use;
- a company's own health page says what address the product thinks you are.
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/lim.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, ROOT)

from datetime import datetime, timedelta
import control_plane
import blueprints.signup as signup
from sqlalchemy import create_engine, event


def control_plane_engine(name):
    """A SQLite stand-in for the control plane.

    Its tables live in a `public` schema, which Postgres has and SQLite does
    not -- so one is attached by that name on every connection. Worth the
    three lines: the alternative is testing a different query from the one
    that runs.
    """
    eng = create_engine(f'sqlite:///{TMP}/{name}.db')

    @event.listens_for(eng, 'connect')
    def _attach(conn, _record):
        conn.execute(f"ATTACH DATABASE '{TMP}/{name}-public.db' AS public")

    control_plane.ensure_table(eng)
    return eng


engine = control_plane_engine('cp')
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


print('\n1. The cap is no longer three')
check(signup.SIGNUPS_PER_ADDRESS_PER_DAY >= 10,
      f'{signup.SIGNUPS_PER_ADDRESS_PER_DAY} a day from one address')

print('\n2. Attempts are grouped by the address actually recorded')
for ip, times in (('203.0.113.7', 2), ('198.51.100.4', 5)):
    for _ in range(times):
        control_plane.record_signup_attempt(engine, ip)
rows = control_plane.signup_attempts_by_ip(engine, datetime.utcnow() - timedelta(days=1))
by = {r['ip']: r['count'] for r in rows}
check(by.get('198.51.100.4') == 5 and by.get('203.0.113.7') == 2,
      f'each address carries its own count: {by}')
check(rows and rows[0]['ip'] == '198.51.100.4', 'busiest first')
check(all(r['last'] is not None for r in rows), 'and when it last tried')

print('\n3. One address behind everything is visible')
single = control_plane_engine('one')
for _ in range(6):
    control_plane.record_signup_attempt(single, '10.0.0.1')
rows = control_plane.signup_attempts_by_ip(single, datetime.utcnow() - timedelta(days=1))
check(len(rows) == 1 and rows[0]['count'] == 6,
      'six attempts, one address — which is what a proxy-shaped fault looks like')

print('\n4. It never raises on a database that cannot answer')
broken = create_engine('sqlite:///' + os.path.join(TMP, 'missing', 'nope.db'))
check(control_plane.signup_attempts_by_ip(broken, datetime.utcnow()) == [],
      'an unreadable control plane gives an empty list, not a 500')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ A refused signup can be explained from the console.')
