"""The clock shim does what the weekly clock check relies on it doing.

If it quietly did nothing the check would pass on every date and say nothing,
which is worse than not having it.
"""
import os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIM = os.path.join(ROOT, 'tests', 'clock_shim')
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


def run(code, fake=None):
    env = {k: v for k, v in os.environ.items() if k not in ('FAKE_NOW', 'PYTHONPATH')}
    env['PYTHONPATH'] = SHIM
    if fake:
        env['FAKE_NOW'] = fake
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, env=env, cwd=ROOT)
    return r.stdout.strip(), r.stderr.strip()


PROBE = ('import datetime, time\\n'
         'from datetime import datetime as D, date, timedelta\\n'
         'print(D.utcnow().isoformat()[:16], D.now().isoformat()[:10], date.today().isoformat(), '
         'int(time.time()) // 86400, isinstance(datetime.datetime(2020, 1, 1), D), '
         '(D.utcnow() + timedelta(days=1)).date().isoformat())').replace('\\n', '\n')

print('1. With FAKE_NOW set, the process believes it is that moment')
out, err = run(PROBE, '2028-02-29T23:30:00')
check(out.startswith('2028-02-29T23:30 ') and out.split()[2] == '2028-02-29' and not err,
      f'utcnow and date.today read the leap day ({out})')
check(out.split()[-1] == '2028-03-01' and out.split()[-2] == 'True',
      'arithmetic goes on from there, and real datetimes are still datetimes')

print('\n2. The clock keeps running from there')
out, _ = run('import time, datetime\nfrom datetime import datetime as D\n'
             'a = D.utcnow(); time.sleep(1.1); b = D.utcnow()\nprint((b - a).total_seconds() >= 1)',
             '2026-12-31T23:30:00')
check(out == 'True', 'one second later it is one second later')

print('\n3. Without FAKE_NOW it does nothing at all')
out, _ = run(PROBE)
from datetime import datetime, timezone
check(out.startswith(datetime.now(timezone.utc).isoformat()[:10]), f'the real date ({out[:16]})')

print('\n4. The workflow uses it')
wf = open(os.path.join(ROOT, '.github', 'workflows', 'clock-check.yml')).read()
check('tests/clock_shim' in wf and 'FAKE_NOW' in wf and "2028-02-29T12:00:00" in wf and "2027-01-01T00:30:00" in wf,
      'the weekly check sets FAKE_NOW and puts the shim on PYTHONPATH, with a leap day and a night after midnight UTC')

print()
if failures:
    print(f'❌ {len(failures)} clock-shim check(s) failed.')
    sys.exit(1)
print('🎉 The clock check is not a no-op.')
