"""Releases a customer gets on purpose, rather than the moment something is pushed.

Every instance deployed from main, so a change pushed at eleven at night was
live in a paying customer's business three minutes later. Customers now follow
`stable`, which moves only when release.py promotes it — and it refuses to
promote anything that does not pass every suite first.
"""
import os, re, sys, tempfile, subprocess, pathlib
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/rel.db'
os.environ['SECRET_KEY'] = 'test'
ROOT = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, str(ROOT))
import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')
from app import create_app
from extensions import db
import branding
app = create_app()


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


with app.app_context():
    db.create_all()
    c = app.test_client()

    print('\n1. Any instance can be asked what it is running, without a login')
    r = c.get('/version')
    body = r.get_json()
    check(r.status_code == 200, 'the version endpoint answers')
    # Required keys, not an exact set. This endpoint is where somebody looks
    # when a deploy behaves oddly, so it is meant to grow — freezing the shape
    # made adding a diagnosis to it look like a regression.
    for key in ('build', 'channel', 'release', 'db'):
        check(key in body, f'reports {key} ({body.get(key)!r})')
    check(body['build'] and body['build'] != 'dev', f"a real commit ({body['build']})")

    print('\n1b. It says which database engine is actually in use')
    # A day was lost to this: DATABASE_URL was never set on the deployment, the
    # app silently fell back to SQLite inside the container, and the only sign
    # was one line in a deploy log reading "SQLiteImpl". Multi-tenancy gives
    # each company its own Postgres schema, so SQLite is not a degraded setup
    # there — it is one where signing anybody up cannot work at all.
    check(body['db'] in ('sqlite', 'postgresql'), f"the engine is named ({body['db']})")
    check('problem' not in body,
          'and no problem is reported on a correctly configured instance')

    print('\n2. The channel says whether this is a customer instance or ours')
    os.environ['RAILWAY_GIT_BRANCH'] = 'stable'
    check(branding.release_channel() == 'stable',
          'an instance deployed from stable reports stable')
    os.environ['RAILWAY_GIT_BRANCH'] = 'main'
    check(branding.release_channel() == 'main',
          'and one deployed from main reports main')
    del os.environ['RAILWAY_GIT_BRANCH']

    print('\n3. It is on every page, so nobody has to go looking')
    with c.session_transaction() as s:
        s['logged_in'] = True; s['role'] = 'owner'
    html = c.get('/bookings/').get_data(as_text=True)
    check(branding.version() in html, 'the build is at the foot of the sidebar')

print('\n4. The release tool refuses to guess')
r = subprocess.run([sys.executable, str(ROOT / 'release.py')],
                   capture_output=True, text=True, cwd=ROOT)
check(r.returncode == 0, 'a plain run succeeds')
check('Nothing has changed' in r.stdout,
      'and changes nothing without --go')
check('Customers are on:' in r.stdout, 'it says where customers are')

print('\n5. Releasing is spelled out where somebody will find it')
doc = (ROOT / 'RELEASING.md').read_text()
for phrase in ('stable', 'main', 'release.py --go', '--rollback', '/version'):
    check(phrase in doc, f'RELEASING.md covers {phrase}')
setup = (ROOT / 'NEW_CUSTOMER_SETUP.md').read_text()
check('ghcr.io' in setup and ':stable' in setup,
      'the setup guide gives the image a customer deploys')
check('read:packages' in setup,
      'and the read-only token scope it is pulled with')
check('"channel":"stable"' in setup.replace(' ', ''),
      'and says to check the instance reports the stable channel')

print('\n6. The release name survives the trip onto a server')
# Railway clones the branch to run the code, not the history, so `git describe`
# is empty on every deployed instance. The release stamps its own name into a
# file that ships with it.
rel = ROOT / 'RELEASE'
check(rel.exists(), 'the release leaves a RELEASE file behind')


def load_release_py():
    """release.py as a module, so the tests read its real configuration."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('release_mod', ROOT / 'release.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Either product's series. This asserted a leading 'v' when there was one line;
# on the Akye branch the file correctly reads akye-v2026.09.03, and a test that
# knows about only one product would fail every Akye release for being one. The
# prefixes are read from release.py so the two cannot drift apart.
stamp = rel.read_text().strip().splitlines()[0]
prefixes = tuple(l.tag_prefix for l in load_release_py().LINES.values())
check(stamp.startswith(prefixes), f'naming the release ({stamp})')
check('RELEASE' in (ROOT / 'release.py').read_text(),
      'and the tool writes it on every release')
check(branding.release_tag() == rel.read_text().split('\n')[0].strip(),
      'which is exactly what /version reports')

print("\n7. A customer's image is buildable and says what it is")
wf = (ROOT / '.github' / 'workflows' / 'publish-image.yml').read_text()
# Where the Dockerfile lives comes from the workflow, not from an assumption.
# This test hardcoded the repo root and went on failing after the Dockerfile was
# deliberately moved out of it, which left a red test nobody trusted — exactly
# where a real failure goes unnoticed. Reading the path from the workflow means
# the build and the test cannot disagree about it again.
_m = re.search(r'^\s*file:\s*(\S+)\s*$', wf, re.M)
check(_m is not None, 'the workflow names the Dockerfile it builds')
_df = ROOT / _m.group(1)
check(_df.exists(), f'and it is there ({_m.group(1)})')
dockerfile = _df.read_text()
check('gunicorn' in dockerfile, 'the image runs the app with gunicorn')
check("app:create_app()" in dockerfile,
      'the same entrypoint railway.toml uses, so image and source run alike')
check('tzdata' in dockerfile,
      'with a timezone database — a slim image without one silently dates '
      'everything in UTC, which is what put every calendar job on the wrong day')
check('RELEASE_SHA' in dockerfile and 'RELEASE_TAG' in dockerfile,
      'and the build stamps in which release it is')

check("tags: ['v*']" in wf, 'CI publishes on a release tag')
check(':stable' in wf or 'stable' in wf, 'pushing the stable tag customers follow')
check('packages: write' in wf, 'with permission to publish')

import os as _os
_os.environ['RELEASE_SHA'] = 'abc1234def'
_os.environ['RELEASE_TAG'] = 'v9999.01.01'
import importlib
importlib.reload(branding)
check(branding.version() == 'abc1234', 'a running container reports its build')
check(branding.release_channel() == 'stable',
      'and calls itself stable — an image only ever comes from a release')
check(branding.release_tag() == 'v9999.01.01', 'and names the release')
del _os.environ['RELEASE_SHA'], _os.environ['RELEASE_TAG']
importlib.reload(branding)

print('\n8. The tool will not promote past a failing test')
src = (ROOT / 'release.py').read_text()
check('run_tests()' in src and 'nothing was released' in src,
      'a failing suite stops the release')
check("'--force-with-lease'" in src,
      'and a rollback cannot clobber somebody else\'s push')

print('\n9. Two products, two lines, and they cannot be confused')
# Akye deployed straight off feature/tenancy on every push — untested, to
# businesses paying to use it. The product sold had weaker deployment safety
# than the business selling it.
rel = load_release_py()
dazzle, akye = rel.LINES['dazzle'], rel.LINES['akye']
# Dazzle & Shine now runs on Akye as a company, and main is Akye's working
# branch. The single-business line ships only from its archive, so a release
# can never put Akye on the single-business customers' channel.
check(dazzle.source == 'dazzle-shine-single-tenant' and dazzle.channel == 'stable',
      'the single-business CRM ships its archive → stable, never main')
check(akye.source == 'main' and akye.channel == 'akye-stable',
      'Akye ships main → akye-stable: merging is not releasing')
check(akye.channel != dazzle.channel, 'the two channels are separate branches')

# Railway deploys akye-stable the moment it moves, so the checks on the exact
# commit are the gate, before the push -- not a report after customers have it.
req = akye.required_checks
check(len(req) == 4 and not dazzle.required_checks,
      'an Akye release needs the four checks that run on every push to main')
green = [{'id': 1, 'name': n, 'status': 'completed', 'conclusion': 'success'} for n in req]
check(rel.check_problems(green, req) == [], 'all four passed: nothing stops it')
rerun = green[:3] + [{'id': 2, 'name': req[3], 'status': 'completed', 'conclusion': 'failure'},
                     {'id': 3, 'name': req[3], 'status': 'completed', 'conclusion': 'success'}]
check(rel.check_problems(rerun, req) == [], 'a check that failed and passed on re-run counts as passed')
check(rel.check_problems(green[:3], req) == [f'{req[3]}: has not run on this commit'],
      'one that never ran stops the release')
running = green[:3] + [{'id': 4, 'name': req[3], 'status': 'in_progress', 'conclusion': None}]
check(rel.check_problems(running, req) == [f'{req[3]}: still running'], 'so does one still running')
failed = green[:3] + [{'id': 5, 'name': req[3], 'status': 'completed', 'conclusion': 'failure'}]
check(rel.check_problems(failed, req) == [f'{req[3]}: failure'], 'and one that failed')
src = (ROOT / 'release.py').read_text()
go_src = src[src.index('def go('):src.index('def rollback(')]
check(go_src.index('require_green(') < go_src.index("f'{line.channel}:{line.channel}'"),
      'and the checks are asked before the channel is pushed')

# A rollback goes back from the release the channel is on, not from the newest
# tag: after one rollback the newest tag is no longer what customers run.
on = {'akye-v3': 'c3', 'akye-v2': 'c2', 'akye-v1': 'c1'}
tags_ = ['akye-v3', 'akye-v2', 'akye-v1']
check(rel.release_before(tags_, 'c3', on.get) == ('akye-v3', 'akye-v2'), 'rollback from v3 goes to v2')
check(rel.release_before(tags_, 'c2', on.get) == ('akye-v2', 'akye-v1'),
      'and a second rollback, from v2, goes to v1 rather than to v2 again')
check(rel.release_before(tags_, 'c1', on.get) == ('akye-v1', None), 'with nothing before the first')
check(rel.release_before(tags_, 'cx', on.get) is None,
      'and a channel on no release is left for a person to move')

# What a release was is kept in its tag, not only in a terminal that closes:
# the runs it was let through on, the schema it moves to, and the way back.
runs_ = [{'id': 7, 'name': n, 'status': 'completed', 'conclusion': 'success',
          'html_url': f'https://github.com/o/r/actions/runs/1/job/{i}'} for i, n in enumerate(req)]
ev = rel.check_evidence(runs_, req)
check(len(ev) == 4 and all('success (https://github.com/o/r/actions/runs/1/job/' in e for e in ev),
      'the release records each required check and the run it came from')
head = rel.migration_head()
import migrate as _mig
check(head == _mig.ScriptDirectory.from_config(_mig._config()).get_current_head(),
      f'and the migration head it takes every company to ({head})')
m = rel.release_manifest(akye, 'akye-v2026.10.21', 'abc1234def', ev,
                         ['aaa111 One change', 'bbb222 Another'], 'akye-v2026.10.06')
for part, what in (('abc1234def', 'the exact commit whose checks were required'),
                   (ev[0], 'each check run'), (head, 'the migration head'),
                   ('aaa111 One change', 'every change'),
                   ('--rollback (back to akye-v2026.10.06)', 'the way back')):
    check(part in m, f'the manifest names {what}')

# P1-09 (25 Oct report): the release commit is what akye-stable points at and
# Railway deploys, and it is a protected branch needing the checks on that
# exact commit. The tool used to push it straight away and be refused.
check(go_src.index('wait_for_checks(') < go_src.index("f'{line.channel}:{line.channel}'")
      and go_src.index("git('push', REMOTE, line.source)") < go_src.index('wait_for_checks('),
      'the release commit goes to main, its checks are waited for, and only then the channel moves')
check(go_src.index('marker_only(') < go_src.index("git('push', REMOTE, line.source)"),
      'and it is refused before any push if it changes more than RELEASE')
_git = rel.git
rel.git = lambda *a, **k: 'RELEASE' if a[0] == 'diff' else _git(*a, **k)
check(rel.marker_only('a', 'b'), 'a release commit changing only RELEASE is the checked commit plus a name')
rel.git = lambda *a, **k: 'RELEASE\napp.py' if a[0] == 'diff' else _git(*a, **k)
check(not rel.marker_only('a', 'b'), 'one that changes code as well is not')
rel.git = _git
_runs, _said = rel.check_runs, []
seq = [running, running, green]
rel.check_runs = lambda sha: seq.pop(0)
t = [0]
got = rel.wait_for_checks(akye, 'f00e8d7', timeout=600, poll=30,
                          sleep=lambda n: t.__setitem__(0, t[0] + n), clock=lambda: t[0])
check(got is not None and len(got) == 4 and t[0] == 60,
      'it waits while a check runs, and returns the four results once they pass')
rel.check_runs = lambda sha: failed
try:
    rel.wait_for_checks(akye, 'f00e8d7', timeout=600, poll=30, sleep=lambda n: None, clock=lambda: 0)
    check(False, 'a failing check on the release commit stops it')
except SystemExit as e:
    check('was not moved' in str(e) and 'failure' in str(e),
          'a failing check on the release commit stops it, and says the channel was not moved')
rel.check_runs = lambda sha: running
t = [0]
try:
    rel.wait_for_checks(akye, 'f00e8d7', timeout=90, poll=30,
                        sleep=lambda n: t.__setitem__(0, t[0] + n), clock=lambda: t[0])
    check(False, 'it gives up in the end')
except SystemExit as e:
    check('Gave up' in str(e) and 'git push origin f00e8d7:akye-stable' in str(e),
          'it gives up in the end, and says exactly what is left to do')
rel.check_runs = lambda sha: None
check(rel.wait_for_checks(akye, 'f00e8d7', sleep=lambda n: None) is None,
      'with GitHub unreachable it says so rather than guessing')
rel.check_runs = _runs
m2 = rel.release_manifest(akye, 'akye-v2026.10.25.3', 'abc1234def', ev, ['aaa111 One'], None,
                          release_sha='fff9999eee', release_evidence=ev)
check('Release commit: fff9999eee' in m2 and 'RELEASE only' in m2
      and m2.count(ev[0]) == 2 and 'Checks on the release commit:' in m2,
      'the tag records both commits, that they differ by RELEASE only, and the runs on each')
check('(no earlier release)' in rel.release_manifest(akye, 't', 's', ev, [], None),
      'a first release says there is nothing to roll back to')
check('release.py --rollback (back to v1)' in rel.release_manifest(dazzle, 'v2', 's', [], [], 'v1'),
      "and the single-business line's record rolls back its own line, without --akye")

# When GitHub cannot be asked, a typed-back hash is no evidence. Each check
# needs a link to its run, and a second person, both kept in the tag.
import builtins
_real_input, _real_git, _real_repo = builtins.input, rel.git, rel._github_repo
rel._github_repo = lambda: 'o/r'
rel.git = lambda *a, **k: 'Pat Releaser' if a[:2] == ('config', 'user.name') else ''
def by_hand(answers):
    it = iter(answers)
    builtins.input = lambda prompt='': next(it)
    try:
        return rel._attest_by_hand(akye, 'abc1234def')
    except SystemExit:
        return None
links = [f'https://github.com/o/r/actions/runs/{100 + i}' for i in range(len(req))]
try:
    ok_ev = by_hand(links + ['Sam Checker'])
    check(ok_ev and all(l in ' '.join(ok_ev) for l in links) and 'Sam Checker' in ok_ev[-1],
          'by hand: each run link and the second person go into the record')
    check(by_hand(['abc1234'] + links[1:] + ['Sam Checker']) is None,
          'a typed-back hash instead of a run link is refused')
    check(by_hand(['https://github.com/other/repo/actions/runs/1'] + links[1:] + ['Sam Checker']) is None,
          "a run from another repository is refused")
    check(by_hand([links[0]] * len(links) + ['Sam Checker']) is None
          and by_hand([links[0], links[0] + '/job/7'] + links[2:] + ['Sam Checker']) is None,
          'one run given for two checks is refused (each runs in its own workflow)')
    check(by_hand(links + ['']) is None and by_hand(links + ['pat releaser']) is None,
          'and so is no second person, or the releaser naming themselves')
finally:
    builtins.input, rel.git, rel._github_repo = _real_input, _real_git, _real_repo
src2 = (ROOT / 'release.py').read_text()
go2 = src2[src2.index('def go('):src2.index('def rollback(')]
check("'-m', manifest" in go2, 'and go() writes it as the tag message')

check(dazzle.tag_prefix != akye.tag_prefix,
      'each line has its own tag series, so same-day releases cannot collide')
check(akye.tag_prefix.startswith('akye-'), "Akye's releases are named for it")

# A rollback that walked one product back onto the other's release would put a
# cleaning company on software written for a different product entirely.
tags = ['v2026.09.03', 'akye-v2026.09.03', 'v2026.09.02', 'akye-v2026.09.01']
_real = rel.git
rel.git = lambda *a, **k: '\n'.join(tags) if a[:2] == ('tag', '--list') else _real(*a, **k)
try:
    check(all(t.startswith('akye-') for t in rel.line_tags(akye)),
          "a rollback of Akye only ever sees Akye's own releases")
    check(not any(t.startswith('akye-') for t in rel.line_tags(dazzle)),
          "and a rollback of Dazzle never sees Akye's")
finally:
    rel.git = _real

print('\n9b. A suite that already passed on this commit is not run twice')
_cr = rel.check_runs
_suite_ok = [{'id': 5, 'name': 'Every test suite', 'status': 'completed', 'conclusion': 'success',
              'html_url': 'https://github.com/o/r/actions/runs/1/job/5'}]
rel.check_runs = lambda sha: _suite_ok
got = rel.ci_covers_suites(akye, 'abc1234')
check(got and 'Every test suite: success' in got and 'actions/runs/1' in got,
      'a passed suite on the commit is found, with the run it came from')
rel.check_runs = lambda sha: [dict(_suite_ok[0], conclusion='failure')]
check(rel.ci_covers_suites(akye, 'abc1234') is None, 'a failed one is not trusted')
rel.check_runs = lambda sha: [dict(_suite_ok[0], status='in_progress', conclusion=None)]
check(rel.ci_covers_suites(akye, 'abc1234') is None, 'nor one still running')
rel.check_runs = lambda sha: []
check(rel.ci_covers_suites(akye, 'abc1234') is None, 'nor one that never ran')
rel.check_runs = lambda sha: None
check(rel.ci_covers_suites(akye, 'abc1234') is None,
      'with GitHub unreachable nothing vouches for it, so the suites run')
rel.check_runs = _cr
check(rel.ci_covers_suites(rel.LINES['dazzle'], 'abc1234') is None,
      'a line that does not require the suite check is never skipped')
src = (ROOT / 'release.py').read_text()
go_src = src[src.index('def go('):src.index('def rollback(')]
check('retest=False' in go_src and 'ci_covers_suites(line, checked)' in go_src,
      'go() asks about the checked commit, not the release commit')
check(go_src.index('ci_covers_suites(') > go_src.index('require_green('),
      'and only after the checks themselves passed')
check('--retest' in src, 'and --retest runs them anyway')

print('\n10. A release tests the code it is actually shipping')
# The suites run against the working tree. Releasing one line while checked out
# on the other would test one product and ship the other — green, and
# meaningless.
check('--abbrev-ref' in src and 'line.source' in src,
      'preflight refuses unless the checkout is the branch being released')

print('\n🎉 Release checks passed.')

print('\n The gate runs on the version the customers run')
# The tests passing means nothing if they passed somewhere production is not.
# Python 3.12 changed sum() to compensated summation for floats, so ten dimes
# come to $1.00 there and $0.9999999999999999 on 3.9 -- a suite green on the
# older one was recording money behaviour production did not have.
import release as _rel
check(_rel.PRODUCTION_PYTHON == (3, 12),
      'the gate knows what the customer image is built on')
_dockerfile = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'docker', 'Dockerfile')
if os.path.exists(_dockerfile):
    _v = '.'.join(str(n) for n in _rel.PRODUCTION_PYTHON)
    check(f'python:{_v}' in open(_dockerfile).read(),
          f'and it is the same version the Dockerfile builds ({_v})')
check(hasattr(_rel, 'check_python'), 'and refuses to gate from an older one')

# Homebrew's python will not install packages into itself (PEP 668), so the
# right Python and the packages the tests import are in different places. Making
# somebody remember which interpreter to type is how the wrong one gets typed,
# so an old interpreter hands over to the project's .venv instead.
_src = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'release.py')).read()
check('.venv' in _src and 'execv' in _src,
      'an older Python hands over to the project .venv rather than refusing')
check('RELEASE_HANDED_OVER' in _src,
      'once only, so a .venv that is also too old cannot loop')
