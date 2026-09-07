"""Every company's automations run, and one company's trouble stays its own.

A cleaning company owner was expected to sign up for cron-job.org and paste six
URLs before their reminders would send. That is the self-hosted assumption
leaking into a product where we are the host, and in practice it means the ones
who never get round to it send nothing and find out from a customer.

Running it centrally moves the failure onto us, which is the right trade and the
reason for most of what is checked here: a company that is slow, suspended, or
misconfigured must not take the others' reminders down with it.
"""
import os, sys, tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/sch.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['REMINDER_API_KEY'] = 'key-under-the-mat'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scheduler

# Held before any section stubs it out, so the newline check further down can
# build a real header rather than reassigning a stub to itself.
REAL_CALL = scheduler.call

failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


print('\n1. It runs what the Automations page says runs')
# Both read automations.JOBS, so the page and the timetable cannot drift apart
# and leave a job nobody is calling.
import automations
check(set(scheduler.all_jobs()) == {k for k, _l, _b, _c in automations.JOBS},
      f'all six jobs, from one list ({len(scheduler.all_jobs())})')
check(scheduler.jobs_for('hourly') == ['charge-balances'],
      'balances are the hourly one — they are charged at each job\'s start time')
check(len(scheduler.jobs_for('daily')) == 5, 'the other five are daily')
check(set(scheduler.jobs_for('hourly')) | set(scheduler.jobs_for('daily'))
      == set(scheduler.all_jobs()),
      'and every job is on one timetable or the other, none forgotten')


print('\n2. Every company gets called, at its own address')
CALLED = []
scheduler.companies = lambda: [
    {'slug': 'acme', 'status': 'active'},
    {'slug': 'baker', 'status': 'active'},
]
scheduler.time.sleep = lambda *_: None
scheduler.call = lambda slug, job, base, key: (
    CALLED.append((slug, job, base, key)), (True, 'ok'))[1]

scheduler.run(['reminders'], quiet=True)
check([c[0] for c in CALLED] == ['acme', 'baker'], 'both companies')
check(all(c[2] == 'akye.test' for c in CALLED),
      'each at its own subdomain of the product domain')
check(all(c[3] == 'key-under-the-mat' for c in CALLED),
      'with the key the endpoints check')


print('\n3. A suspended company is not still texting its customers')
scheduler.companies = lambda: [
    {'slug': 'acme', 'status': 'active'},
    {'slug': 'gone', 'status': 'suspended'},
    {'slug': 'shut', 'status': 'closed'},
]
CALLED.clear()
scheduler.run(['reminders'], quiet=True)
check([c[0] for c in CALLED] == ['acme'],
      'only the active one is called')


print('\n4. One company failing does not stop the rest')
# The whole reason for per-company calls. A bad Stripe key at one business must
# not mean nine others get no reminders that night.
scheduler.companies = lambda: [
    {'slug': 'first', 'status': 'active'},
    {'slug': 'broken', 'status': 'active'},
    {'slug': 'last', 'status': 'active'},
]
CALLED.clear()
scheduler.call = lambda slug, job, base, key: (
    CALLED.append(slug),
    (False, 'HTTP 500') if slug == 'broken' else (True, 'ok'))[1]
bad = scheduler.run(['reminders'], quiet=True)
check(CALLED == ['first', 'broken', 'last'],
      'the ones after the failure are still called')
check(len(bad) == 1 and bad[0][0] == 'broken',
      'and the failure is reported rather than raised')


print('\n5. A failed run is a failed run')
# Moving this off the customer means a silent failure is now ours to notice,
# and a green tick on a night nothing sent would be worse than the old way.
check(bool(bad), 'failures come back so the job can exit non-zero')
scheduler.call = lambda *a: (True, 'ok')
check(scheduler.run(['reminders'], quiet=True) == [],
      'and a clean run reports nothing')


print('\n6. It refuses to run half-configured')
for var, why in [('BASE_DOMAIN', 'no company address could be built'),
                 ('REMINDER_API_KEY', 'every call would come back 403')]:
    keep = os.environ.pop(var)
    try:
        scheduler.run(['reminders'], quiet=True)
        check(False, f'missing {var} is refused — {why}')
    except SystemExit as e:
        check(var in str(e), f'missing {var} is refused — {why}')
    finally:
        os.environ[var] = keep


print('\n7. A secret with a stray newline still works')
# What actually happened on the first real run: the key was pasted into GitHub
# with a trailing newline, and urllib refused the header outright -- "Invalid
# header value" -- which reads as a bug in the caller rather than a stray
# keystroke in a settings box. Every job for every company failed on it.
import scheduler as _s
seen = {}
_s.urllib.request.urlopen = lambda req, timeout=None: (_ for _ in ()).throw(
    AssertionError('should not reach the network'))


class _Resp:
    def read(self, n=None): return b'{"ok": true}'
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _capture(req, timeout=None):
    seen['key'] = req.get_header('X-api-key')
    return _Resp()


_s.urllib.request.urlopen = _capture
os.environ['REMINDER_API_KEY'] = 'key-under-the-mat\n'
_s.companies = lambda: [{'slug': 'acme', 'status': 'active'}]
_s.call = REAL_CALL                 # the real one, so the header is really built
_s.run(['reminders'], quiet=True)
check(seen.get('key') == 'key-under-the-mat',
      'the newline is trimmed before it reaches the header')
os.environ['REMINDER_API_KEY'] = 'key-under-the-mat'

print('\n8. The workflow runs the branch that knows what a company is')
wf = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  '.github', 'workflows', 'automations.yml')
y = open(wf).read()
check('ref: akye-stable' in y,
      'checks out akye-stable — main has no tenancy and no company list')
check('cron:' in y and "'5 * * * *'" in y, 'hourly for balances')
check("'0 22 * * *'" in y, 'and daily for the rest, the evening before')
check('concurrency:' in y, 'one at a time, so balances cannot be charged twice')
check('python-version: \'3.12\'' in y, 'on the version production runs')

print()
if failures:
    print(f'❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    sys.exit(1)
print('✅ Every company\'s automations run, and one company\'s trouble stays its own.')
