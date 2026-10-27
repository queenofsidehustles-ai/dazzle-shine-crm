"""Run every test suite, the way release.py does, and fail if any fails.

    TEST_POSTGRES_URL=postgresql://... python tests/run_all.py
    TEST_POSTGRES_URL=postgresql://... python tests/run_all.py --jobs auto

Each suite runs in its own process: many set environment variables and build
their own app at import time, so sharing one interpreter would let one suite's
settings leak into the next. Style is detected per file (release._is_pytest_style).

--jobs N (or `auto`: one per CPU, at most four) runs N suites at a time. Most
suites take a few seconds and the rest a minute or so, so the whole run is
close to the sum of them divided by N. The suites that share a PostgreSQL
database (43 read TEST_POSTGRES_URL directly, several create fixed-name schemas
in it) cannot share it between workers, so each worker gets a database of its
own -- <name>_w1, <name>_w2, ... -- created before the run and dropped after.
The other suites make their own differently named databases or use SQLite files
in their own temporary directories, and each suite runs once, so they cannot
meet. The default is one job, which is exactly the old behaviour.
"""
import argparse
import os
import queue
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import release  # noqa: E402

PER_SUITE_SECONDS = 900
MAX_AUTO_JOBS = 4

# The slowest suites, longest first (seconds on one CPU, October 2026). Started
# first so the last minutes of a parallel run are short suites, not one long
# one left running alone. Only the order depends on this: a suite missing from
# the list, or renamed, still runs.
SLOW_FIRST = (
    'test_demo_company',               # 78
    'test_launch_security',            # 76
    'test_console_lifecycle',          # 65
    'test_signup',                     # 62
    'test_cohort_30_tenant_isolation', # 46
    'test_evidence_certification',     # 45
    'test_tenancy_cohort_30',          # 44
    'test_backup',                     # 43
    'test_commercial_lead_by_hand',    # 37
    'test_console_operations',         # 33
    'test_affiliates',                 # 32
    'test_cron_secret_transport',      # 28
)


def auto_jobs(cpus=None):
    """One job per CPU, at most MAX_AUTO_JOBS."""
    return max(1, min(MAX_AUTO_JOBS, cpus or os.cpu_count() or 1))


def parse_jobs(value):
    if str(value).strip().lower() == 'auto':
        return auto_jobs()
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f'--jobs wants a number or "auto", not {value!r}')
    if n < 1:
        raise argparse.ArgumentTypeError('--jobs must be at least 1')
    return n


def order_suites(paths):
    """The slowest known suites first, then the rest by name."""
    rank = {name: i for i, name in enumerate(SLOW_FIRST)}
    return sorted(paths, key=lambda p: (rank.get(p.stem, len(rank)), p.name))


def _url(base):
    """A SQLAlchemy URL naming the psycopg2 driver, as fresh_postgres does:
    from SQLAlchemy 2.1 a bare postgresql:// means psycopg 3, which is not here."""
    from sqlalchemy.engine import make_url
    u = make_url(base)
    if u.drivername in ('postgresql', 'postgres'):
        u = u.set(drivername='postgresql+psycopg2')
    return u


def worker_url(base, n):
    """`base` with its database renamed <database>_w<n>."""
    u = _url(base)
    return u.set(database=f'{u.database}_w{n}').render_as_string(hide_password=False)


def _admin(base):
    from sqlalchemy import create_engine
    return create_engine(_url(base), isolation_level='AUTOCOMMIT')


def create_worker_databases(base, jobs):
    """One empty database per worker, from the same server as `base`."""
    from sqlalchemy import text
    urls = {}
    engine = _admin(base)
    try:
        with engine.connect() as c:
            for n in range(1, jobs + 1):
                name = _url(base).set(database=f'{_url(base).database}_w{n}').database
                c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
                c.execute(text(f'CREATE DATABASE "{name}"'))
                urls[n] = worker_url(base, n)
    finally:
        engine.dispose()
    return urls


def drop_worker_databases(base, jobs):
    """Best effort: a database left behind is dropped by the next run."""
    from sqlalchemy import text
    try:
        engine = _admin(base)
        with engine.connect() as c:
            for n in range(1, jobs + 1):
                name = _url(base).set(database=f'{_url(base).database}_w{n}').database
                c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        engine.dispose()
    except Exception:  # noqa: BLE001
        pass


def run_suite(path, env):
    """One suite in its own process. (ok, stdout, stderr, seconds)."""
    cmd = ([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', str(path)]
           if release._is_pytest_style(path) else [sys.executable, str(path)])
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=PER_SUITE_SECONDS, env=env)
        ok, out, err = r.returncode == 0, r.stdout, r.stderr
    except subprocess.TimeoutExpired as e:
        ok, out, err = False, f'TIMED OUT after {PER_SUITE_SECONDS}s\n{e.stdout or ""}', ''
    return ok, out, err, time.time() - t0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--jobs', '-j', type=parse_jobs,
                    default=parse_jobs(os.environ.get('RUN_ALL_JOBS') or 1),
                    help='suites to run at a time: a number, or "auto" (default: 1)')
    args = ap.parse_args(argv)

    suites = order_suites((ROOT / 'tests').glob('test_*.py'))
    jobs = min(args.jobs, len(suites))
    base = os.environ.get('TEST_POSTGRES_URL')
    worker_urls = {}
    if jobs > 1 and base:
        worker_urls = create_worker_databases(base, jobs)
    if jobs > 1:
        print(f'Running {len(suites)} suites, {jobs} at a time'
              + (' (a database each)' if worker_urls else ''), flush=True)

    failed = []
    started = time.time()
    lock = threading.Lock()
    slots = queue.Queue()
    for n in range(1, jobs + 1):
        slots.put(n)

    def one(path):
        n = slots.get()
        try:
            env = dict(os.environ)
            if worker_urls:
                env['TEST_POSTGRES_URL'] = worker_urls[n]
                if 'PGURL' in env:
                    env['PGURL'] = worker_urls[n]
            env['TEST_WORKER'] = str(n)
            ok, out, err, secs = run_suite(path, env)
        finally:
            slots.put(n)
        with lock:
            print(f'{"✅" if ok else "❌"} {path.name} ({secs:.0f}s)', flush=True)
            if not ok:
                failed.append(path.name)
                # The two streams apart: a suite's own checks report on stdout, and
                # one that logs a lot to stderr (every alembic migration it runs)
                # would otherwise push what failed out of the tail entirely.
                tail = '\n'.join(out.strip().splitlines()[-40:])
                err_tail = '\n'.join(str(err or '').strip().splitlines()[-20:])
                print(f'::group::{path.name} output\n{tail}\n'
                      f'--- stderr ---\n{err_tail}\n::endgroup::', flush=True)

    try:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            list(pool.map(one, suites))
    finally:
        if worker_urls:
            drop_worker_databases(base, jobs)

    failed.sort()
    summary = (f'{len(suites) - len(failed)}/{len(suites)} suites passed '
               f'in {(time.time() - started) / 60:.0f} min')
    print(f'\n{summary}')
    # On GitHub Actions the database service's shutdown log follows this and
    # buries it, so the result also goes where it is read: the job summary,
    # and one annotation per failing suite on the check itself.
    step_summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if step_summary:
        with open(step_summary, 'a') as fh:
            fh.write(f'### {summary}\n\n')
            for name in failed:
                fh.write(f'- ❌ `{name}`\n')
    for name in failed:
        print(f'::error title=Test suite failed::{name}')
    if failed:
        print('Failed: ' + ', '.join(failed))
        sys.exit(1)


if __name__ == '__main__':
    main()
