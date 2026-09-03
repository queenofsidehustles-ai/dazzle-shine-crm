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
check(rel.read_text().strip().split('\n')[0].startswith('v'),
      f'naming the release ({rel.read_text().strip().splitlines()[0]})')
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
sys.path.insert(0, str(ROOT))
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location('release_mod', ROOT / 'release.py')
rel = _ilu.module_from_spec(_spec); _spec.loader.exec_module(rel)

dazzle, akye = rel.LINES['dazzle'], rel.LINES['akye']
check(dazzle.source == 'main' and dazzle.channel == 'stable',
      'Dazzle still ships main → stable, exactly as before')
check(akye.source == 'feature/tenancy' and akye.channel == 'akye-stable',
      'Akye ships feature/tenancy → akye-stable, not straight to customers')
check(akye.channel != dazzle.channel, 'the two channels are separate branches')

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

print('\n10. A release tests the code it is actually shipping')
# The suites run against the working tree. Releasing one line while checked out
# on the other would test one product and ship the other — green, and
# meaningless.
check('--abbrev-ref' in src and 'line.source' in src,
      'preflight refuses unless the checkout is the branch being released')

print('\n🎉 Release checks passed.')
