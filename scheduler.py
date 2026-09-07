"""Run every company's automations, so no company has to run its own.

The six jobs — reminders, balance charges, follow-ups, drips, applicant chases,
Google Ads chases — are HTTP endpoints that something has to wake up on a
timetable. On a single-business CRM that something is the owner's own cron job,
which is right: they run the instance, so they run the clock.

On Akye they do not run the instance. Asking a cleaning company owner to sign up
for cron-job.org and paste six URLs is the self-hosted assumption leaking into a
product where we are the host. In practice it means the ones who never get round
to it quietly send no reminders and charge no balances, and find out from a
customer.

So this runs centrally, the way ZenMaid and Jobber do it: one timetable, walking
every company. A cleaning company signs up and its automations are already
running, because there was never anything for it to switch on.

## What it does not do

It does not reimplement any job. It calls the same endpoint a customer's own
cron would have called, against that company's own address, with the same key.
Nothing here knows what a reminder is.

## Failure is per company

One company's database being slow, or its Stripe key being wrong, must not stop
the other nine from getting their reminders. Each is called on its own and a
failure is recorded and reported at the end, not raised in the middle.

## Using it

    python3 scheduler.py --job reminders        # one job, every company
    python3 scheduler.py --cadence hourly       # every job due hourly
    python3 scheduler.py --cadence daily        # every job due daily
    python3 scheduler.py --cadence daily --only kojo    # one company, for testing

Needs three things in the environment:

    AKYE_DATABASE_URL   the Akye database, to read the list of companies
    BASE_DOMAIN         akyehq.com — what a company's address is built from
    REMINDER_API_KEY    the key the endpoints check; the same one Railway has
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

# Cadence per job, taken from the same table the Automations page reads so the
# two cannot disagree about what is supposed to run when.
try:
    from automations import JOBS
except Exception:                                   # pragma: no cover
    JOBS = []

# How long to wait on one company before moving on. Charging balances talks to
# Stripe for every job due, so it is the slow one; nothing should take minutes.
TIMEOUT = 120

# A company being suspended or closed is not a company whose customers should
# still be getting texts.
RUNNABLE = ('active',)


def jobs_for(cadence):
    return [key for key, _label, _blurb, cad in JOBS if cad == cadence]


def all_jobs():
    return [key for key, _label, _blurb, _cad in JOBS]


def companies():
    """Every company that should have its automations run, from the registry.

    Read from the control plane rather than a list kept anywhere else: a company
    that exists is a company whose customers are expecting reminders, and the
    registry is the only thing that knows.
    """
    import control_plane
    from sqlalchemy import create_engine
    url = os.environ.get('AKYE_DATABASE_URL') or os.environ.get('DATABASE_URL') or ''
    if not url:
        sys.exit('AKYE_DATABASE_URL is not set — nothing to read the companies from.')
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    if url.startswith('postgresql://') and '+psycopg2' not in url:
        url = url.replace('postgresql://', 'postgresql+psycopg2://', 1)
    engine = create_engine(url)
    control_plane.ensure_table(engine)
    return [o for o in control_plane.all_orgs(engine)
            if (o.get('status') or 'active') in RUNNABLE]


def call(slug, job, base, key):
    """Wake one job for one company. Returns (ok, detail)."""
    url = f'https://{slug}.{base}/api/{job}'
    req = urllib.request.Request(url, data=b'{}', method='POST', headers={
        'Content-Type': 'application/json',
        'X-Api-Key': key,
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read(2000).decode('utf8', 'replace')
            try:
                detail = json.dumps(json.loads(body))[:160]
            except ValueError:
                detail = body[:160]
            return True, detail
    except urllib.error.HTTPError as e:
        # 403 is the one worth calling out by name: it means the key here and
        # the key the app checks are different, which looks like "nothing is
        # running" rather than like a misconfiguration.
        hint = ' (REMINDER_API_KEY does not match the one the app expects)' if e.code == 403 else ''
        return False, f'HTTP {e.code}{hint}'
    except Exception as e:
        return False, f'{type(e).__name__}: {e}'


def run(jobs, only=None, quiet=False):
    base = (os.environ.get('BASE_DOMAIN') or '').strip().lower()
    # Trimmed, and not only for tidiness: a secret pasted with a trailing
    # newline makes urllib refuse the header outright -- "Invalid header value"
    # -- which reads as a bug in the caller rather than a stray keystroke in a
    # settings box. Whitespace around a secret should never be the difference
    # between working and not.
    key = (os.environ.get('REMINDER_API_KEY') or '').strip()
    if not base:
        sys.exit('BASE_DOMAIN is not set — cannot work out any company\'s address.')
    if not key:
        sys.exit('REMINDER_API_KEY is not set — every call would be refused.')

    # Filtered here as well as in companies(). A suspended company's customers
    # must not be texted, and that guarantee should not depend on which piece of
    # code assembled the list -- including a future caller that builds it some
    # other way.
    orgs = [o for o in companies()
            if (o.get('status') or 'active') in RUNNABLE]
    if only:
        orgs = [o for o in orgs if o['slug'] == only]
        if not orgs:
            sys.exit(f'No active company called {only!r}.')

    if not quiet:
        print(f'{len(orgs)} compan{"y" if len(orgs) == 1 else "ies"} × '
              f'{len(jobs)} job{"" if len(jobs) == 1 else "s"}\n')

    failures = []
    for o in orgs:
        slug = o['slug']
        for job in jobs:
            ok, detail = call(slug, job, base, key)
            if not quiet:
                mark = '✅' if ok else '❌'
                print(f'  {mark} {slug:<20} {job:<20} {detail}')
            if not ok:
                failures.append((slug, job, detail))
            # Gentle on a shared database: these are background jobs and
            # nothing is waiting on them, so there is no reason to stampede.
            time.sleep(0.4)

    if not quiet:
        print()
        if failures:
            print(f'❌ {len(failures)} failed:')
            for slug, job, detail in failures:
                print(f'   {slug} · {job} — {detail}')
            print('\nThe companies that succeeded are unaffected; each is called '
                  'on its own.')
        else:
            print('✅ Every company, every job.')
    return failures


def main():
    p = argparse.ArgumentParser(description='Run every company\'s automations.')
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--job', help='one job, for every company')
    g.add_argument('--cadence', choices=['hourly', 'daily'],
                   help='every job that runs on this timetable')
    g.add_argument('--all', action='store_true', help='every job, whatever its cadence')
    p.add_argument('--only', help='a single company slug, for testing')
    p.add_argument('--quiet', action='store_true')
    args = p.parse_args()

    if args.job:
        jobs = [args.job]
    elif args.cadence:
        jobs = jobs_for(args.cadence)
    else:
        jobs = all_jobs()

    if not jobs:
        sys.exit('No jobs to run — automations.JOBS is empty or the cadence matched none.')

    return 1 if run(jobs, only=args.only, quiet=args.quiet) else 0


if __name__ == '__main__':
    sys.exit(main())
