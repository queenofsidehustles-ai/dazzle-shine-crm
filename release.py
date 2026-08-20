#!/usr/bin/env python3
"""Promote what's on main to the customers running this CRM.

Every instance used to deploy from main, so a change pushed at eleven at night
reached a paying customer's business before anyone had used it once. Now:

    main    — this business's own instance. Moves on every push. The canary:
              whatever is wrong gets found here, on our own bookings.
    stable  — every customer instance. Moves only when this script is run.

Promoting is deliberate, tested, and reversible:

    python3 release.py            # show what would be released, change nothing
    python3 release.py --go       # run the tests, tag it, push stable
    python3 release.py --rollback # put stable back on the previous release

Nothing here touches a database or a customer's settings. It moves a git branch,
and Railway does the rest.
"""
import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAIN = 'main'
STABLE = 'stable'
REMOTE = 'origin'


def git(*args, check=True):
    r = subprocess.run(('git',) + args, cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f'git {" ".join(args)} failed:\n{r.stderr.strip()}')
    return r.stdout.strip()


def say(msg=''):
    print(msg, flush=True)


def next_tag():
    """v2026.08.20, with .2 .3 … if more than one release lands in a day."""
    today = date.today().strftime('v%Y.%m.%d')
    same_day = [t for t in git('tag', '--list', f'{today}*').split('\n') if t]
    if not same_day:
        return today
    suffixes = [int(m.group(1)) for t in same_day
                if (m := re.match(rf'{re.escape(today)}\.(\d+)$', t))]
    return f'{today}.{max(suffixes or [1]) + 1}'


def pending():
    """Commits on main that customers do not have yet."""
    out = git('log', f'{REMOTE}/{STABLE}..{REMOTE}/{MAIN}', '--oneline')
    return [l for l in out.split('\n') if l]


def run_tests():
    """Every suite must pass before anything reaches a customer."""
    tests = sorted((ROOT / 'tests').glob('test_*.py'))
    say(f'Running {len(tests)} test suites…')
    failed = []
    for t in tests:
        r = subprocess.run([sys.executable, str(t)], cwd=ROOT,
                           capture_output=True, text=True)
        if r.returncode == 0:
            say(f'  ✅ {t.name}')
        else:
            failed.append(t.name)
            say(f'  ❌ {t.name}')
            say('     ' + (r.stdout.strip().split('\n') or ['(no output)'])[-1])
    return failed


def preflight():
    if git('status', '--porcelain'):
        sys.exit('You have uncommitted changes. Commit or stash them first.')
    git('fetch', REMOTE, '--tags')
    local_main = git('rev-parse', MAIN)
    remote_main = git('rev-parse', f'{REMOTE}/{MAIN}')
    if local_main != remote_main:
        sys.exit(f'Your {MAIN} and {REMOTE}/{MAIN} differ — push or pull first.')


def show():
    commits = pending()
    current = git('rev-parse', '--short', f'{REMOTE}/{STABLE}')
    latest = git('show', f'{REMOTE}/{STABLE}:RELEASE', check=False).split('\n')[0] \
        or '(none yet)'
    say(f'Customers are on:  {current}   release {latest}')
    say(f'Ready to release:  {len(commits)} commit(s)\n')
    for c in commits:
        say(f'  · {c}')
    if not commits:
        say('  (nothing — customers already have everything on main)')
    say('\nNothing has changed. Run with --go to release.')


def go():
    preflight()
    commits = pending()
    if not commits:
        sys.exit('Nothing to release — stable already matches main.')

    say(f'Releasing {len(commits)} commit(s) to every customer instance:\n')
    for c in commits:
        say(f'  · {c}')
    say()

    failed = run_tests()
    if failed:
        sys.exit(f'\n{len(failed)} suite(s) failed — nothing was released. '
                 f'Fix them and run this again.')

    tag = next_tag()
    say(f'\nAll green. Tagging {tag} and promoting {STABLE}…')

    # The running app cannot read a git tag: Railway clones the branch to run
    # the code, not the history. So the release writes its own name into a file
    # that ships with it, and /version reads that.
    (ROOT / 'RELEASE').write_text(f'{tag}\n{date.today().isoformat()}\n')
    git('add', 'RELEASE')
    git('commit', '-m', f'Release {tag}')
    git('push', REMOTE, MAIN)

    git('tag', '-a', tag, '-m', f'Release {tag} — {len(commits)} change(s)', MAIN)
    # Fast-forward only: stable can never contain anything main does not.
    git('branch', '-f', STABLE, MAIN)
    git('push', REMOTE, f'{STABLE}:{STABLE}')
    git('push', REMOTE, tag)
    say(f'\n✅ Released {tag}. Customer instances will redeploy within a few minutes.')
    say(f'   Check any of them at /version — it should report release {tag}.')


def rollback():
    preflight()
    tags = [t for t in git('tag', '--list', '--sort=-creatordate').split('\n') if t]
    if len(tags) < 2:
        sys.exit('There is no earlier release to go back to.')
    current, previous = tags[0], tags[1]
    say(f'Rolling customers back from {current} to {previous}.')
    say('Their data is untouched — this only changes which code runs.\n')
    if input(f'Type {previous} to confirm: ').strip() != previous:
        sys.exit('Cancelled — nothing changed.')
    git('branch', '-f', STABLE, previous)
    git('push', REMOTE, '--force-with-lease', f'{STABLE}:{STABLE}')
    say(f'\n✅ Customers are back on {previous}.')
    say('   Fix the problem on main, then release forward again.')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--go', action='store_true', help='test, tag and release')
    ap.add_argument('--rollback', action='store_true',
                    help='put customers back on the previous release')
    args = ap.parse_args()
    if args.rollback:
        rollback()
    elif args.go:
        go()
    else:
        show()
