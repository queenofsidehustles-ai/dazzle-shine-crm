"""What the console's Release page knows, and the one thing it may do.

The page shows the difference between `main` (where work lands) and
`akye-stable` (what every company runs), and starts the same release
`release.py --akye --go` performs by hand. It does not release anything itself.
Pressing the button asks GitHub to run the "Release Akye" workflow, which holds
the push credential, runs every suite, and moves the branch. The web server
never gets a token that can write code: GITHUB_RELEASE_TOKEN only has to read
the repository and start workflows.

Every fact comes from GitHub at the moment the page is drawn. Nothing is cached,
because a diff that was true ten minutes ago is not a reason to ship.
"""
import os
import re

import requests

DEFAULT_REPO = 'queenofsidehustles-ai/dazzle-shine-crm'
WORKFLOW = 'release.yml'
SOURCE = 'main'
CHANNEL = 'akye-stable'
TIMEOUT = 20

# Paths worth a second look before they reach every company. Not a verdict --
# a reviewer's eye is pointed at them first.
WATCH = (
    ('Database migration', re.compile(r'^migrations/versions/')),
    ('Dependencies', re.compile(r'^requirements.*\.txt$')),
    ('Deploy and release machinery', re.compile(r'^(\.github/workflows/|release\.py$|Dockerfile|docker/|railway)')),
    ('Sign-in, roles and tenancy', re.compile(r'^(security|rbac|tenancy|auth|city_switch|private_media)\.py$')),
    ('Money', re.compile(r'^(billing|affiliates|partner_payouts|payments|invoices)\.py$|^blueprints/(payments|billing)\.py$')),
)


def repo():
    return (os.environ.get('GITHUB_REPO') or DEFAULT_REPO).strip()


def token():
    return (os.environ.get('GITHUB_RELEASE_TOKEN') or '').strip()


def configured():
    return bool(token())


def _call(method, path, **kw):
    """(status, parsed json or text). Raises nothing: a page that cannot reach
    GitHub says so instead of failing to draw."""
    headers = {'Accept': 'application/vnd.github+json',
               'X-GitHub-Api-Version': '2022-11-28',
               'Authorization': f'Bearer {token()}'}
    accept = kw.pop('accept', None)
    if accept:
        headers['Accept'] = accept
    try:
        r = requests.request(method, f'https://api.github.com/repos/{repo()}/{path}',
                             headers=headers, timeout=TIMEOUT, **kw)
    except requests.RequestException as exc:
        return 0, f'{type(exc).__name__}'
    try:
        return r.status_code, r.json() if r.content and not accept else r.text
    except ValueError:
        return r.status_code, r.text


def required_checks():
    import release
    return release.LINES['akye'].required_checks


def watch_flags(files):
    """{label: [paths]} for the changed files that deserve a closer look."""
    out = {}
    for f in files:
        for label, rx in WATCH:
            if rx.search(f.get('filename') or ''):
                out.setdefault(label, []).append(f['filename'])
    return out


def check_states(runs):
    """[(name, state, url)] for each required check, newest attempt of each.

    state is 'passed', 'running', 'failed' or 'missing'."""
    newest = {}
    for r in runs:
        if r.get('name') in required_checks() and \
                r.get('id', 0) >= newest.get(r['name'], {}).get('id', -1):
            newest[r['name']] = r
    out = []
    for name in required_checks():
        r = newest.get(name)
        if r is None:
            out.append((name, 'missing', None))
        elif r.get('status') != 'completed':
            out.append((name, 'running', r.get('html_url')))
        elif r.get('conclusion') == 'success':
            out.append((name, 'passed', r.get('html_url')))
        else:
            out.append((name, 'failed', r.get('html_url')))
    return out


def overview():
    """Everything the page draws, or {'error': why}."""
    if not configured():
        return {'error': 'GITHUB_RELEASE_TOKEN is not set, so GitHub cannot be asked.'}
    code, cmp_ = _call('GET', f'compare/{CHANNEL}...{SOURCE}', params={'per_page': 100})
    if code != 200 or not isinstance(cmp_, dict):
        return {'error': f'GitHub would not compare {CHANNEL} with {SOURCE} (status {code}).'}
    commits = [{'sha': c['sha'], 'short': c['sha'][:7],
                'message': (c['commit']['message'] or '').split('\n')[0],
                'author': (c.get('author') or {}).get('login')
                          or c['commit']['author']['name'],
                'url': c.get('html_url')} for c in cmp_.get('commits', [])]
    files = cmp_.get('files') or []
    # The compare list is capped and oldest-first, so main's head comes from the branch.
    code, b = _call('GET', f'branches/{SOURCE}')
    head = b['commit']['sha'] if code == 200 and isinstance(b, dict) else None
    checks = []
    if head:
        code, runs = _call('GET', f'commits/{head}/check-runs', params={'per_page': 100})
        checks = check_states(runs.get('check_runs', [])) if code == 200 else []
    code, st = _call('GET', f'branches/{CHANNEL}')
    stable = st['commit']['sha'] if code == 200 else None
    code, rel = _call('GET', 'contents/RELEASE', params={'ref': CHANNEL},
                      accept='application/vnd.github.raw+json')
    release_name = rel.split('\n')[0].strip() if code == 200 and isinstance(rel, str) else None
    code, wr = _call('GET', f'actions/workflows/{WORKFLOW}/runs', params={'per_page': 5})
    runs_now = [{'id': r['id'], 'status': r['status'], 'conclusion': r['conclusion'],
                 'url': r['html_url'], 'created': r['created_at'],
                 'sha': (r.get('head_sha') or '')[:7]}
                for r in (wr.get('workflow_runs', []) if code == 200 else [])]
    return {
        'error': None,
        'stable_sha': stable, 'release': release_name,
        'main_sha': head, 'ahead': cmp_.get('ahead_by', 0), 'behind': cmp_.get('behind_by', 0),
        'commits': commits, 'files': files,
        'truncated': (cmp_.get('ahead_by', 0) > len(commits)) or len(files) >= 300,
        'flags': watch_flags(files),
        'additions': sum(f.get('additions', 0) for f in files),
        'deletions': sum(f.get('deletions', 0) for f in files),
        'checks': checks, 'runs': runs_now,
        'running': any(r['status'] != 'completed' for r in runs_now),
    }


def blockers(ov):
    """Why the button is off. Empty means a release may start."""
    if ov.get('error'):
        return [ov['error']]
    out = []
    if not ov['ahead']:
        out.append(f'Nothing to release: {CHANNEL} already has everything on {SOURCE}.')
    if ov['behind']:
        out.append(f'{CHANNEL} has {ov["behind"]} commit(s) that {SOURCE} lacks, so it cannot '
                   f'be fast-forwarded. Merge {CHANNEL} into {SOURCE} first.')
    for name, state, _url in ov['checks']:
        if state != 'passed':
            out.append(f'{name}: {state}')
    if not ov['checks']:
        out.append('The required checks could not be read for this commit.')
    if ov['running']:
        out.append('A release is already running.')
    return out


def start(expected_sha):
    """Ask GitHub to run the release for exactly this commit. (ok, message)."""
    if not re.fullmatch(r'[0-9a-f]{40}', expected_sha or ''):
        return False, 'That is not a commit.'
    code, body = _call('POST', f'actions/workflows/{WORKFLOW}/dispatches',
                       json={'ref': SOURCE, 'inputs': {'expected_sha': expected_sha}})
    if code == 204:
        return True, None
    if code in (401, 403, 404):
        return False, ('GitHub refused: GITHUB_RELEASE_TOKEN needs to read the repository '
                       'and have Actions: read and write.')
    return False, f'GitHub did not start the release (status {code}).'
