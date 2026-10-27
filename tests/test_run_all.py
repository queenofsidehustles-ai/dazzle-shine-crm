"""The test runner can run suites in parallel without them meeting.

What has to hold: the default is still one at a time, the slow suites start
first, every parallel worker gets a PostgreSQL database of its own (43 suites
share the one in TEST_POSTGRES_URL and several create fixed-name schemas in it),
and a failing suite is still a failing run.
"""
import os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import argparse
import run_all as ra

failures = []


def check(ok, label):
    print(('  ok   ' if ok else '  FAIL ') + label)
    if not ok:
        failures.append(label)


print('1. How many at once')
check(ra.parse_jobs('1') == 1 and ra.parse_jobs(3) == 3, 'a number is a number')
check(ra.parse_jobs('auto') == ra.auto_jobs(), '"auto" is one per CPU')
check(ra.auto_jobs(1) == 1 and ra.auto_jobs(2) == 2 and ra.auto_jobs(64) == ra.MAX_AUTO_JOBS,
      'one per CPU, never more than the cap')
for bad in ('0', '-2', 'lots'):
    try:
        ra.parse_jobs(bad)
        check(False, f'{bad!r} is refused')
    except argparse.ArgumentTypeError:
        check(True, f'{bad!r} is refused')
check('default=parse_jobs(os.environ.get(\'RUN_ALL_JOBS\') or 1)' in (ROOT / 'tests' / 'run_all.py').read_text(),
      'and the default is still one at a time')

print('\n2. The slow suites go first')
paths = [Path(f'tests/{n}.py') for n in ('test_zzz', 'test_aaa', 'test_signup', 'test_demo_company', 'test_bbb')]
got = [p.stem for p in ra.order_suites(paths)]
check(got[:2] == ['test_demo_company', 'test_signup'], f'the known slow ones lead, longest first ({got[:2]})')
check(got[2:] == ['test_aaa', 'test_bbb', 'test_zzz'], 'the rest follow by name')
check(all((ROOT / 'tests' / f'{n}.py').exists() for n in ra.SLOW_FIRST),
      'every name in the slow list is a suite that exists')

print('\n3. A database for each worker')
base = 'postgresql://postgres:pw@localhost:5432/akye_full_suite'
check(ra.worker_url(base, 3) == 'postgresql+psycopg2://postgres:pw@localhost:5432/akye_full_suite_w3',
      'the worker URL is the same server and login, a different database, driver named')
check(ra.worker_url('postgresql+psycopg2://u:p@h/db', 1).endswith('/db_w1'), 'an already-named driver is kept')
check(len({ra.worker_url(base, n) for n in range(1, 5)}) == 4, 'every worker gets its own')

print('\n4. A suite runs in its own process with the worker\'s environment')
with tempfile.TemporaryDirectory() as d:
    ok_script = Path(d) / 'test_ok.py'
    ok_script.write_text("import os, sys\nprint(os.environ.get('TEST_POSTGRES_URL'))\nsys.exit(0)\n")
    bad_script = Path(d) / 'test_bad.py'
    bad_script.write_text("import sys\nprint('boom')\nsys.exit(1)\n")
    env = dict(os.environ, TEST_POSTGRES_URL='postgresql://x/y_w2')
    ok, out, err, secs = ra.run_suite(ok_script, env)
    check(ok and 'y_w2' in out, 'it gets the worker\'s database, not the shared one')
    ok, out, err, secs = ra.run_suite(bad_script, env)
    check(not ok and 'boom' in out, 'and a failing suite is reported as failing, with its output')

print()
if failures:
    print(f'{len(failures)} FAILED:')
    for f in failures:
        print('  - ' + f)
    sys.exit(1)
print('all good')
