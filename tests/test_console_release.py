"""Console → Release: see what main has that companies lack, and start a release.

GitHub is replaced by a recording stand-in, so this checks what the page shows,
who may press the button, and that the dispatch asks for exactly the commit
that was on screen.
"""
import os
import secrets
import sys

os.environ['DATABASE_URL'] = os.environ.get(
    'TEST_POSTGRES_URL', 'postgresql://app_user:localtest@127.0.0.1:5432/postgres')
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['BASE_DOMAIN'] = 'akyehq.test'
os.environ['GITHUB_RELEASE_TOKEN'] = 'test-token'
os.environ['GITHUB_REPO'] = 'someone/their-repo'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
import control_plane
import provisioning
import release_control

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


HEAD = 'a' * 40
STABLE = 'b' * 40
TAG = secrets.token_hex(4)
OWNER = f'owner-{TAG}@example.com'
HELPER = f'helper-{TAG}@example.com'
PW = 'a-real-console-password-1'

state = {'checks': 'success', 'head': HEAD, 'running': False, 'ahead': 2, 'dispatched': []}
NAMES = release_control.required_checks()


def fake_call(method, path, **kw):
    if path.startswith('compare/'):
        commits = [{'sha': 'c' * 40, 'html_url': 'http://x/c',
                    'commit': {'message': 'Add the thing\n\nbody', 'author': {'name': 'A'}},
                    'author': {'login': 'dev'}}] * state['ahead']
        return 200, {'ahead_by': state['ahead'], 'behind_by': 0, 'commits': commits,
                     'files': [{'filename': 'migrations/versions/0035_x.py', 'status': 'added',
                                'additions': 10, 'deletions': 0},
                               {'filename': 'app.py', 'status': 'modified',
                                'additions': 3, 'deletions': 1}]}
    if path == 'branches/main':
        return 200, {'commit': {'sha': state['head']}}
    if path == 'branches/akye-stable':
        return 200, {'commit': {'sha': STABLE}}
    if path == 'contents/RELEASE':
        return 200, 'akye-v2026.10.23\n2026-10-23\n'
    if path.endswith('/check-runs'):
        return 200, {'check_runs': [
            {'id': i, 'name': n, 'status': 'completed', 'conclusion': state['checks'],
             'html_url': 'http://x/run'} for i, n in enumerate(NAMES)]}
    if path.startswith('actions/workflows/') and path.endswith('/runs'):
        return 200, {'workflow_runs': [{'id': 1, 'status': 'in_progress' if state['running'] else 'completed',
                                        'conclusion': None if state['running'] else 'success',
                                        'html_url': 'http://x/r', 'created_at': '2026-10-23T12:00:00Z',
                                        'head_sha': HEAD}]}
    if path == 'tags':
        return 200, [{'name': 'akye-v2026.10.23', 'commit': {'sha': STABLE}},
                     {'name': 'akye-v2026.10.06', 'commit': {'sha': 'e' * 40}},
                     {'name': 'akye-v2026.09.09.9', 'commit': {'sha': 'f' * 40}},
                     {'name': 'v2026.09.21', 'commit': {'sha': '1' * 40}}]
    if path.endswith('/dispatches'):
        state['dispatched'].append(kw['json'])
        return 204, ''
    return 404, {}


release_control._call = fake_call

with app.app_context():
    engine = provisioning._engine()
    control_plane.ensure_table(engine)
    db.session.remove()
    control_plane.add_console_user(engine, OWNER, 'Console Owner', PW, role='owner')
    control_plane.add_console_user(engine, HELPER, 'Console Helper', PW, role='helper')
    db.session.remove()

    c = app.test_client()
    good = {'sha': HEAD, 'reason': 'Ship the security fixes', 'confirm': HEAD[:7], 'password': PW}

    print('\n1. The page shows the difference')
    c.post('/console/login', data={'email': HELPER, 'password': PW})
    r = c.get('/console/release')
    body = r.get_data(as_text=True)
    check(r.status_code == 200, 'a helper can open it')
    check('akye-v2026.10.23' in body and 'aaaaaaa' in body, 'it names the release and the commit')
    check('Add the thing' in body and 'app.py' in body, 'it lists commits and files')
    check('Database migration' in body and '0035_x.py' in body,
          'a migration is called out for a closer look')
    check('Only the console owner can release' in body, 'a helper sees no button')

    print('\n2. Only the owner may press it')
    r = c.post('/console/release/go', data=good, follow_redirects=True)
    check(not state['dispatched'], 'a helper starts nothing')
    check('Only the console owner' in r.get_data(as_text=True), 'and is told why')
    c.get('/console/logout')

    c.post('/console/login', data={'email': OWNER, 'password': PW})
    body = c.get('/console/release').get_data(as_text=True)
    check('to every company' in body and 'name="confirm"' in body, 'the owner sees the form')

    print('\n3. Each guard refuses on its own')
    for label, data in (
            ('a wrong password', dict(good, password='nope')),
            ('a wrong confirmation', dict(good, confirm='zzzzzzz')),
            ('no reason', dict(good, reason='')),
            ('a stale commit', dict(good, sha='d' * 40))):
        c.post('/console/release/go', data=data, follow_redirects=True)
        check(not state['dispatched'], f'{label} starts nothing')

    print('\n4. Red checks, nothing to ship, or a release already running stop it')
    for label, change in (('a failing check', {'checks': 'failure'}),
                          ('no commits ahead', {'ahead': 0}),
                          ('a release in progress', {'running': True})):
        saved = {k: state[k] for k in change}
        state.update(change)
        body = c.get('/console/release').get_data(as_text=True)
        check('Not ready to release' in body and 'to every company' not in body,
              f'{label}: the page offers no button')
        c.post('/console/release/go', data=good, follow_redirects=True)
        check(not state['dispatched'], f'{label}: and a direct post starts nothing')
        state.update(saved)

    print('\n5. All good: it asks GitHub for exactly the reviewed commit')
    r = c.post('/console/release/go', data=good, follow_redirects=True)
    check(state['dispatched'] == [{'ref': 'main', 'inputs': {'expected_sha': HEAD}}],
          'one dispatch, of main, for the commit on screen')
    check('Release started' in r.get_data(as_text=True), 'and the owner is told')
    log = [x for x in control_plane.console_log_all(engine) if x.get('actor') == OWNER]
    check(any('started release' in (x.get('action') or '') for x in log)
          and any('Ship the security fixes' in (x.get('detail') or '') for x in log),
          'it is in the console log with the reason')

    print('\n5b. Rollback goes to the release before the one companies are on')
    state['dispatched'].clear()
    body = c.get('/console/release').get_data(as_text=True)
    check('Roll back to akye-v2026.10.06' in body, 'the page names the previous release')
    rb = {'from': 'akye-v2026.10.23', 'to': 'akye-v2026.10.06', 'reason': 'Bookings broke',
          'confirm': 'akye-v2026.10.06', 'password': PW}
    for label, data in (('a wrong password', dict(rb, password='nope')),
                        ('a wrong confirmation', dict(rb, confirm='akye-v2026.09.09.9')),
                        ('no reason', dict(rb, reason='')),
                        ('a page that is out of date', dict(rb, to='akye-v2026.09.09.9'))):
        c.post('/console/release/rollback', data=data, follow_redirects=True)
        check(not state['dispatched'], f'{label} rolls nothing back')
    state['running'] = True
    c.post('/console/release/rollback', data=rb, follow_redirects=True)
    check(not state['dispatched'], 'nor does a release already running')
    state['running'] = False
    c.post('/console/release/rollback', data=rb, follow_redirects=True)
    check(state['dispatched'] == [{'ref': 'main', 'inputs': {'to_tag': 'akye-v2026.10.06'}}],
          'the right one: a single dispatch of exactly that release')
    log = [x for x in control_plane.console_log_all(engine) if x.get('actor') == OWNER]
    check(any('started rollback' in (x.get('action') or '') and 'Bookings broke' in (x.get('detail') or '')
              for x in log), 'with the reason in the console log')
    c.get('/console/logout')
    c.post('/console/login', data={'email': HELPER, 'password': PW})
    state['dispatched'].clear()
    c.post('/console/release/rollback', data=rb, follow_redirects=True)
    check(not state['dispatched'], 'a helper cannot roll back')
    check(release_control.start_rollback('main')[0] is False and
          release_control.start_rollback('akye-v2026.10.06; rm')[0] is False,
          'only a release name is ever dispatched')
    c.get('/console/logout')
    c.post('/console/login', data={'email': OWNER, 'password': PW})

    print('\n6. Without a token it says so instead of failing')
    os.environ['GITHUB_RELEASE_TOKEN'] = ''
    release_control._call = lambda *a, **k: (_ for _ in ()).throw(AssertionError('no call'))
    body = c.get('/console/release').get_data(as_text=True)
    check('is not set' in body, 'the page explains what is missing')

    print('\n7. The commit id is validated before it is sent anywhere')
    os.environ['GITHUB_RELEASE_TOKEN'] = 'test-token'
    check(release_control.start('not-a-sha')[0] is False, 'junk is not dispatched')

if failures:
    print(f'\n❌ {len(failures)} failed:')
    for f in failures:
        print('  -', f)
    sys.exit(1)
print('\n🎉 The console shows what would ship and starts the release for exactly that commit.')
