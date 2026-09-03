#!/usr/bin/env python3
"""Promote tested code to the people running it. Two products, two lines.

Every instance used to deploy from main, so a change pushed at eleven at night
reached a paying customer's business before anyone had used it once. That was
fixed for the CRM itself and never fixed for Akye — which deployed
straight off `feature/tenancy` on every push, untested, to businesses paying to
use it. The product being sold had weaker deployment safety than the business
selling it.

    This business's own CRM    Akye
    ──────────────────────    ────
    main    → this business    feature/tenancy → nobody. The working branch.
              (the canary)
    stable  → its customers    akye-stable     → every company on Akye

Each line moves only when this script runs, and only if every test passes.

    python3 release.py                  # this CRM: what would go out
    python3 release.py --go             # this CRM: test, tag, promote
    python3 release.py --akye           # Akye: what would go out
    python3 release.py --akye --go      # Akye: test, tag, promote
    python3 release.py --rollback       # put a line back one release

Tags are namespaced per line — v2026.09.03 and akye-v2026.09.03 — so two
releases on one day cannot take each other's number, and a rollback cannot walk
a line back onto the other product's release.

Nothing here touches a database or a customer's settings. It moves a git
branch, and Railway does the rest.
"""
import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REMOTE = 'origin'


class Line:
    """One product's path from working branch to the people running it."""

    def __init__(self, key, source, channel, tag_prefix, product, audience):
        self.key = key
        self.source = source            # where the work lands
        self.channel = channel          # what deployed instances follow
        self.tag_prefix = tag_prefix    # keeps two tag series apart
        self.product = product
        self.audience = audience


LINES = {
    'dazzle': Line('dazzle', source='main', channel='stable', tag_prefix='v',
                   product='this CRM',
                   audience='every customer instance'),
    'akye': Line('akye', source='feature/tenancy', channel='akye-stable',
                 tag_prefix='akye-v', product='Akye',
                 audience='every cleaning company on Akye'),
}


def git(*args, check=True):
    r = subprocess.run(('git',) + args, cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f'git {" ".join(args)} failed:\n{r.stderr.strip()}')
    return r.stdout.strip()


def say(msg=''):
    print(msg, flush=True)


def remote_has(branch):
    return bool(git('ls-remote', '--heads', REMOTE, branch, check=False))


def next_tag(line):
    """akye-v2026.09.03, with .2 .3 … if more than one lands in a day.

    Namespaced per line. Sharing one series let a CRM release and an Akye
    release on the same day fight over the same number, and made --rollback
    walk one product back onto a release belonging to the other."""
    today = date.today().strftime(f'{line.tag_prefix}%Y.%m.%d')
    same_day = [t for t in git('tag', '--list', f'{today}*').split('\n') if t]
    if not same_day:
        return today
    suffixes = [int(m.group(1)) for t in same_day
                if (m := re.match(rf'{re.escape(today)}\.(\d+)$', t))]
    return f'{today}.{max(suffixes or [1]) + 1}'


def line_tags(line):
    """This line's releases, newest first — and only this line's.

    'v' is a prefix of 'akye-v' in neither direction, but a bare --list on the
    CRM prefix would still be wrong if it ever matched, so both are filtered
    explicitly rather than by luck."""
    tags = [t for t in git('tag', '--list', f'{line.tag_prefix}*',
                           '--sort=-creatordate').split('\n') if t]
    other = [l.tag_prefix for l in LINES.values() if l.key != line.key]
    return [t for t in tags if not any(t.startswith(p) for p in other)]


def pending(line):
    """Commits on the source branch that the deployed instances do not have."""
    if not remote_has(line.channel):
        return git('log', f'{REMOTE}/{line.source}', '--oneline').split('\n')[:1] \
            and ['(first release — the channel does not exist yet)']
    out = git('log', f'{REMOTE}/{line.channel}..{REMOTE}/{line.source}', '--oneline')
    return [l for l in out.split('\n') if l]


def run_tests():
    """Every suite must pass before anything reaches anybody."""
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


def preflight(line):
    if git('status', '--porcelain'):
        sys.exit('You have uncommitted changes. Commit or stash them first.')

    # The tests run against the working tree, so the working tree has to BE the
    # thing being released. Releasing one line while checked out on the other
    # would test one product and ship the other — green, and meaningless.
    here = git('rev-parse', '--abbrev-ref', 'HEAD')
    if here != line.source:
        sys.exit(f'You are on “{here}” but releasing {line.product}, which ships '
                 f'from “{line.source}”.\nThe tests run against whatever is '
                 f'checked out, so switch first:\n\n    git checkout {line.source}\n')

    git('fetch', REMOTE, '--tags')
    local = git('rev-parse', line.source)
    remote = git('rev-parse', f'{REMOTE}/{line.source}', check=False)
    if not remote:
        sys.exit(f'{REMOTE}/{line.source} does not exist — push it first.')
    if local != remote:
        sys.exit(f'Your {line.source} and {REMOTE}/{line.source} differ — '
                 f'push or pull first.')


def show(line):
    commits = pending(line)
    if not remote_has(line.channel):
        say(f'{line.product}: no {line.channel} branch yet — this would be the '
            f'first release.')
        say(f'Everything on {line.source} would go out to {line.audience}.')
        say(f'\nNothing has changed. Run with --go to release.')
        return
    current = git('rev-parse', '--short', f'{REMOTE}/{line.channel}')
    latest = git('show', f'{REMOTE}/{line.channel}:RELEASE',
                 check=False).split('\n')[0] or '(none yet)'
    say(f'{line.product} — {line.audience}')
    say(f'Customers are on:  {current}   release {latest}')
    say(f'Ready to release:  {len(commits)} commit(s)\n')
    for c in commits:
        say(f'  · {c}')
    if not commits:
        say(f'  (nothing — they already have everything on {line.source})')
    say('\nNothing has changed. Run with --go to release.')


def go(line):
    preflight(line)
    first = not remote_has(line.channel)
    commits = pending(line)
    if not commits and not first:
        sys.exit(f'Nothing to release — {line.channel} already matches '
                 f'{line.source}.')

    say(f'Releasing {line.product} to {line.audience}:\n')
    for c in commits:
        say(f'  · {c}')
    say()

    failed = run_tests()
    if failed:
        sys.exit(f'\n{len(failed)} suite(s) failed — nothing was released. '
                 f'Fix them and run this again.')

    tag = next_tag(line)
    say(f'\nAll green. Tagging {tag} and promoting {line.channel}…')

    # The running app cannot read a git tag: Railway clones the branch to run
    # the code, not the history. So the release writes its own name into a file
    # that ships with it, and /version reads that.
    (ROOT / 'RELEASE').write_text(f'{tag}\n{date.today().isoformat()}\n')
    git('add', 'RELEASE')
    git('commit', '-m', f'Release {tag}')
    git('push', REMOTE, line.source)

    git('tag', '-a', tag, '-m', f'Release {tag} — {len(commits)} change(s)',
        line.source)
    # Fast-forward only: the channel can never contain anything the source does not.
    git('branch', '-f', line.channel, line.source)
    git('push', REMOTE, f'{line.channel}:{line.channel}')
    git('push', REMOTE, tag)
    say(f'\n✅ Released {tag}. Instances will redeploy within a few minutes.')
    say(f'   Check one at /version — it should report release {tag} '
        f'on channel {line.channel}.')


def rollback(line):
    preflight(line)
    tags = line_tags(line)
    if len(tags) < 2:
        sys.exit(f'There is no earlier {line.product} release to go back to.')
    current, previous = tags[0], tags[1]
    say(f'Rolling {line.audience} back from {current} to {previous}.')
    say('Their data is untouched — this only changes which code runs.\n')
    if input(f'Type {previous} to confirm: ').strip() != previous:
        sys.exit('Cancelled — nothing changed.')
    git('branch', '-f', line.channel, previous)
    git('push', REMOTE, '--force-with-lease', f'{line.channel}:{line.channel}')
    say(f'\n✅ Back on {previous}.')
    say(f'   Fix the problem on {line.source}, then release forward again.')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--akye', action='store_true',
                    help="release Akye rather than this business's own CRM")
    ap.add_argument('--go', action='store_true', help='test, tag and release')
    ap.add_argument('--rollback', action='store_true',
                    help='put them back on the previous release')
    args = ap.parse_args()
    chosen = LINES['akye' if args.akye else 'dazzle']
    if args.rollback:
        rollback(chosen)
    elif args.go:
        go(chosen)
    else:
        show(chosen)
