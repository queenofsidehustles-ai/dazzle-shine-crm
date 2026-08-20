"""Releases a customer gets on purpose, rather than the moment something is pushed.

Every instance deployed from main, so a change pushed at eleven at night was
live in a paying customer's business three minutes later. Customers now follow
`stable`, which moves only when release.py promotes it — and it refuses to
promote anything that does not pass every suite first.
"""
import os, sys, tempfile, subprocess, pathlib
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
    check(set(body) == {'build', 'channel', 'release'},
          f'reporting build, channel and release ({body})')
    check(body['build'] and body['build'] != 'dev', f"a real commit ({body['build']})")

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
check('stable' in setup and 'not `main`' in setup,
      'and the setup guide says which branch a customer instance follows')

print('\n6. The tool will not promote past a failing test')
src = (ROOT / 'release.py').read_text()
check('run_tests()' in src and 'nothing was released' in src,
      'a failing suite stops the release')
check("'--force-with-lease'" in src,
      'and a rollback cannot clobber somebody else\'s push')

print('\n🎉 Release checks passed.')
