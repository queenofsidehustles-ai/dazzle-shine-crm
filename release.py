#!/usr/bin/env python3
"""Promote tested code to the people running it. Two products, two lines.

Every instance used to deploy from main, so a change pushed at eleven at night
reached a paying customer's business before anyone had used it once. That was
fixed for the CRM itself and never fixed for Akye — which deployed
straight off `feature/tenancy` on every push, untested, to businesses paying to
use it. The product being sold had weaker deployment safety than the business
selling it.

    The single-business CRM (retired)            Akye
    ──────────────────────────────────            ────
    dazzle-shine-single-tenant → its archive      main        → nobody. The working branch:
    stable  → its customer instances                              every pull request lands here.
                                                  akye-stable → every company on Akye
                                                                (Railway deploys it)

Dazzle & Shine now runs on Akye as one of its companies, so the single-business
line is kept only to rebuild an old instance. Akye reaches customers only when
`--akye --go` promotes main to akye-stable, fast-forward, after every suite
passes.

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
import ast
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REMOTE = 'origin'


class Line:
    """One product's path from working branch to the people running it."""

    def __init__(self, key, source, channel, tag_prefix, product, audience,
                 required_checks=()):
        self.key = key
        self.source = source            # where the work lands
        self.channel = channel          # what deployed instances follow
        self.tag_prefix = tag_prefix    # keeps two tag series apart
        self.product = product
        self.audience = audience
        # GitHub checks that must have passed on the exact commit released.
        self.required_checks = required_checks


LINES = {
    'dazzle': Line('dazzle', source='dazzle-shine-single-tenant', channel='stable',
                   tag_prefix='v', product='the single-business CRM',
                   audience='every customer instance'),
    'akye': Line('akye', source='main', channel='akye-stable',
                 tag_prefix='akye-v', product='Akye',
                 audience='every cleaning company on Akye',
                 # The four workflows that run on every push to main. The
                 # suites here run on this machine; the browser journeys and
                 # the Postgres-only suites run there.
                 required_checks=('Every test suite',
                                  'Exact-head P0 launch certification',
                                  'Local disposable Akye business and accessibility journeys',
                                  'Destructive lifecycle P1 falsification')),
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


def check_problems(runs, required):
    """What stops a commit being released, from its GitHub check runs.

    `runs` is the API's list ({'name', 'status', 'conclusion', 'id'}); a check
    re-run leaves both attempts there, so the newest of each name counts."""
    newest = {}
    for r in runs:
        if r.get('name') in required and r.get('id', 0) >= newest.get(r['name'], {}).get('id', -1):
            newest[r['name']] = r
    out = []
    for name in required:
        r = newest.get(name)
        if r is None:
            out.append(f'{name}: has not run on this commit')
        elif r.get('status') != 'completed':
            out.append(f'{name}: still running')
        elif r.get('conclusion') != 'success':
            out.append(f'{name}: {r.get("conclusion")}')
    return out


def _github_repo():
    url = git('remote', 'get-url', REMOTE, check=False)
    m = re.search(r'github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$', url)
    return m.group(1) if m else None


def check_runs(sha):
    """The commit's check runs from GitHub, or None if they cannot be read
    (no `gh`, not logged in, no network)."""
    import json
    repo = _github_repo()
    if not repo:
        return None
    try:
        r = subprocess.run(['gh', 'api', f'repos/{repo}/commits/{sha}/check-runs?per_page=100'],
                           cwd=ROOT, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout).get('check_runs') or []
    except ValueError:
        return None


def require_green(line, sha):
    """Refuse to promote a commit whose checks did not all pass.

    Railway deploys the channel the moment it moves, so the checks on the
    exact commit are the gate, before the push, not a report after it."""
    if not line.required_checks:
        return []
    runs = check_runs(sha)
    if runs is None:
        repo = _github_repo() or 'the repository'
        say(f'Could not ask GitHub for the checks on {sha[:7]} (is `gh` installed '
            f'and logged in?). Open https://github.com/{repo}/commit/{sha} and '
            f'confirm these passed:')
        for name in line.required_checks:
            say(f'  · {name}')
        if input(f'Type {sha[:7]} if every one is green: ').strip() != sha[:7]:
            sys.exit('Not released — nothing changed.')
        return [f'{name}: confirmed green by hand at https://github.com/{repo}/commit/{sha}'
                for name in line.required_checks]
    problems = check_problems(runs, line.required_checks)
    if problems:
        sys.exit(f'{line.source} at {sha[:7]} is not ready to release:\n'
                 + '\n'.join(f'  · {p}' for p in problems)
                 + '\nNothing was released.')
    say(f'All {len(line.required_checks)} checks passed on {sha[:7]}.')
    return check_evidence(runs, line.required_checks)


def check_evidence(runs, required):
    """One line per required check: its result and the run it came from, so
    the release records which runs it was let through on."""
    newest = {}
    for r in runs:
        if r.get('name') in required and r.get('id', 0) >= newest.get(r['name'], {}).get('id', -1):
            newest[r['name']] = r
    return [f'{name}: {newest[name].get("conclusion")} ({newest[name].get("html_url") or newest[name].get("id")})'
            for name in required if name in newest]


def migration_head():
    """The schema revision this release migrates every company to."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        cfg = Config()
        cfg.set_main_option('script_location', str(ROOT / 'migrations'))
        return ScriptDirectory.from_config(cfg).get_current_head()
    except Exception as e:  # noqa: BLE001
        return f'(could not read: {e})'


def release_manifest(line, tag, checked_sha, evidence, commits, previous):
    """What a release was, written into its tag: the evidence a later reader
    needs without going back to the Actions page or the terminal."""
    out = [f'Release {tag} — {len(commits)} change(s)', '',
           f'Promotes {line.source} to {line.channel} ({line.audience}).',
           f'Checked commit: {checked_sha} (the release commit adds only RELEASE).', '',
           'Checks on the checked commit:']
    out += [f'  {e}' for e in evidence] or ['  (none required)']
    out += ['', f'Migrations: every company to {migration_head()}.', '',
            'Changes:'] + [f'  {c}' for c in commits]
    flag = ' --akye' if line.key == 'akye' else ''
    out += ['', f'Rollback: python3 release.py{flag} --rollback'
            + (f' (back to {previous}).' if previous else ' (no earlier release).')]
    return '\n'.join(out)


def release_before(tags, current, commit_of):
    """(the release the channel is on, the one before it), from `tags`
    newest first; None if the channel is not on one of them."""
    for i, tag in enumerate(tags):
        if commit_of(tag) == current:
            return (tag, tags[i + 1]) if i + 1 < len(tags) else (tag, None)
    return None


def pending(line):
    """Commits on the source branch that the deployed instances do not have."""
    if not remote_has(line.channel):
        return git('log', f'{REMOTE}/{line.source}', '--oneline').split('\n')[:1] \
            and ['(first release — the channel does not exist yet)']
    out = git('log', f'{REMOTE}/{line.channel}..{REMOTE}/{line.source}', '--oneline')
    return [l for l in out.split('\n') if l]


# What the customer image is built on -- see docker/Dockerfile. The gate has to
# run on it, because "passes the tests" means nothing if the tests ran somewhere
# else. This is not pedantry: Python 3.12 changed sum() to compensated summation
# for floats, so ten dimes come to $1.00 there and to $0.9999999999999999 on
# 3.9. A suite green on the older one was recording money behaviour production
# did not have.
PRODUCTION_PYTHON = (3, 12)


def check_python():
    """Refuse to gate a release from a Python the customers do not run.

    Homebrew's python refuses to install packages into itself (PEP 668), so the
    right version of Python and the packages the tests import do not live in the
    same place. Rather than make somebody remember which interpreter to type,
    this hands over to the project's own .venv when the one in use is too old.
    """
    if sys.version_info[:2] >= PRODUCTION_PYTHON:
        return

    want = '.'.join(str(n) for n in PRODUCTION_PYTHON)
    venv = ROOT / '.venv' / 'bin' / 'python'

    # The sentinel stops this looping if the venv is itself too old: it gets one
    # attempt, and then falls through to the message below.
    if venv.exists() and not os.environ.get('RELEASE_HANDED_OVER'):
        say(f'Handing over to .venv (Python {want}) — the version customers run.\n')
        os.environ['RELEASE_HANDED_OVER'] = '1'
        os.execv(str(venv), [str(venv), str(ROOT / 'release.py')] + sys.argv[1:])

    have = '.'.join(str(n) for n in sys.version_info[:3])
    sys.exit(
        f'You are on Python {have}; the customer image is built on {want}.\n'
        f'The tests would pass on a version nobody runs, which is not a gate.\n\n'
        f'There is no usable .venv to hand over to. Make one:\n\n'
        f'  brew install python@{want}\n'
        f'  python{want} -m venv .venv\n'
        f'  .venv/bin/python -m pip install -r requirements.txt\n\n'
        f'Then run this again exactly as you did.')


def _is_pytest_style(path):
    """True for a suite whose checks only run if pytest calls them.

    A `def test_*` function is not executed by importing its module -- only by
    something that collects and calls it. A suite written that way (no
    module-level assert/check() of its own) run as `python file.py` just
    defines the functions and exits 0, having verified nothing; it needs
    `python -m pytest file.py` to actually run. A suite that checks itself at
    import time (module-level assert/check() calls, the older style in this
    repo) is exactly backwards under pytest: collecting zero test functions is
    itself a failure (exit 5), even though every check it ran passed.
    """
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return False
    if not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name.startswith('test_') for n in tree.body):
        return False
    for i, n in enumerate(tree.body):
        if i == 0 and isinstance(n, ast.Expr) and isinstance(
                getattr(n, 'value', None), ast.Constant) and isinstance(
                n.value.value, str):
            continue  # the module docstring, not an executable check
        if isinstance(n, (ast.Expr, ast.Assert, ast.If, ast.For, ast.While, ast.With)):
            return False  # runs its own checks at import time -- a script
    return True


def run_tests():
    """Every suite must pass before anything reaches anybody."""
    check_python()
    tests = sorted((ROOT / 'tests').glob('test_*.py'))
    say(f'Running {len(tests)} test suites…')
    failed = []
    for t in tests:
        cmd = ([sys.executable, '-m', 'pytest', '-q', str(t)]
               if _is_pytest_style(t) else [sys.executable, str(t)])
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
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

    checked = git('rev-parse', f'{REMOTE}/{line.source}')
    evidence = require_green(line, checked)

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
    # that ships with it, and /version reads that. It is the only change on top
    # of the commit whose checks were required above.
    (ROOT / 'RELEASE').write_text(f'{tag}\n{date.today().isoformat()}\n')
    git('add', 'RELEASE')
    git('commit', '-m', f'Release {tag}')
    git('push', REMOTE, line.source)

    earlier = line_tags(line)
    manifest = release_manifest(line, tag, checked, evidence, commits,
                                earlier[0] if earlier else None)
    git('tag', '-a', tag, '-m', manifest, line.source)
    # Fast-forward only: the channel can never contain anything the source does not.
    git('branch', '-f', line.channel, line.source)
    git('push', REMOTE, f'{line.channel}:{line.channel}')
    git('push', REMOTE, tag)
    say(f'\n{manifest}')
    say(f'\n✅ Released {tag}. Instances will redeploy within a few minutes.')
    say(f'   The above is kept as the tag\'s message: git show {tag}')
    say(f'   Check one at /version — it should report release {tag} '
        f'on channel {line.channel}.')


def rollback(line):
    preflight(line)
    tags = line_tags(line)
    on = git('rev-parse', f'{REMOTE}/{line.channel}')
    # From the release the channel is actually on: the newest tag is wrong
    # after one rollback, and walks forward if it was moved back by hand.
    found = release_before(tags, on, lambda t: git('rev-list', '-n', '1', t))
    if found is None:
        sys.exit(f'{line.channel} is at {on[:7]}, which is no {line.product} release. '
                 f'Move it by hand.')
    current, previous = found
    if previous is None:
        sys.exit(f'There is no {line.product} release before {current} to go back to.')
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
