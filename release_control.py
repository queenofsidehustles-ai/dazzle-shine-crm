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

WORKFLOW = 'release.yml'
ROLLBACK_WORKFLOW = 'rollback.yml'
TAG_PREFIX = 'akye-v'
SOURCE = 'main'
CHANNEL = 'akye-stable'
TIMEOUT = 20

# Paths worth a second look before they reach every company. Not a verdict --
# a reviewer's eye is pointed at them first.
WATCH = (
    ('Database migration', re.compile(r'^migrations/')),
    ('Dependencies', re.compile(
        r'(^|/)(requirements[^/]*\.txt|package(-lock)?\.json|yarn\.lock|pnpm-lock\.yaml'
        r'|pyproject\.toml|poetry\.lock|Pipfile(\.lock)?)$')),
    ('Deploy and release machinery', re.compile(
        r'^(\.github/|docker/|release\.py$|release_control\.py$)|(^|/)(Dockerfile|railway[^/]*|Procfile)$')),
    # Matched on the file's own name, so a new module with one of these words
    # in it is covered without anyone remembering to add it here.
    ('Sign-in, roles and tenancy', re.compile(
        r'(^|/)[^/]*(login|auth|rbac|secur|tenan|session|permission|password|totp|city_switch'
        r'|private_media|team|staff)[^/]*\.py$')),
    ('Money', re.compile(
        r'(^|/)[^/]*(bill|invoic|payment|payout|stripe|pricing|charge|commission|affiliate'
        r'|money|deposit|refund|fees|contractor_pay|quote)[^/]*\.py$')),
)


def repo():
    return (os.environ.get('GITHUB_REPO') or '').strip()


def token():
    return (os.environ.get('GITHUB_RELEASE_TOKEN') or '').strip()


def configured():
    return bool(token()) and bool(repo())


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


def commit_jobs(sha):
    """The jobs of every workflow run on `sha`, shaped like GitHub's check runs,
    or None if they cannot be read.

    A required check is a job's name, and the check-runs API that lists them
    needs the Checks permission, which a fine-grained personal access token
    cannot be given. The same jobs are readable with Actions: read."""
    code, wr = _call('GET', 'actions/runs', params={'head_sha': sha, 'per_page': 30})
    if code != 200 or not isinstance(wr, dict):
        return None
    out = []
    for run in wr.get('workflow_runs', [])[:12]:
        code, js = _call('GET', f'actions/runs/{run["id"]}/jobs',
                         params={'per_page': 100, 'filter': 'latest'})
        if code != 200 or not isinstance(js, dict):
            return None
        out.extend(js.get('jobs', []))
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


def _tag_key(name):
    nums = re.findall(r'\d+', name[len(TAG_PREFIX):])
    return tuple(int(n) for n in nums) + (0,) * (4 - len(nums))


def release_history(tag_rows, stable_sha):
    """(the release akye-stable is on, the one before it), by name, or (None, None).

    tag_rows is GitHub's tag list ({'name', 'commit': {'sha'}}). The release is
    found by the commit the channel is on, the way `release.py --rollback` does,
    not by taking the newest tag."""
    rows = sorted((t for t in tag_rows if (t.get('name') or '').startswith(TAG_PREFIX)),
                  key=lambda t: _tag_key(t['name']), reverse=True)
    for i, t in enumerate(rows):
        if t['commit']['sha'] == stable_sha:
            return t['name'], (rows[i + 1]['name'] if i + 1 < len(rows) else None)
    return None, None


def _workflow_runs(workflow):
    code, wr = _call('GET', f'actions/workflows/{workflow}/runs', params={'per_page': 5})
    return [{'id': r['id'], 'status': r['status'], 'conclusion': r['conclusion'],
             'url': r['html_url'], 'created': r['created_at'], 'kind': workflow,
             'sha': (r.get('head_sha') or '')[:7]}
            for r in (wr.get('workflow_runs', []) if code == 200 else [])]


def _heads():
    """(main sha, akye-stable sha), or (None, None) if either cannot be read."""
    out = []
    for branch in (SOURCE, CHANNEL):
        code, b = _call('GET', f'branches/{branch}')
        if code != 200 or not isinstance(b, dict):
            return None, None
        out.append(b['commit']['sha'])
    return tuple(out)


def overview():
    """Everything the page draws, or {'error': why}.

    Built from two commit ids fixed up front, never from branch names, so every
    part describes the same pair. If either branch moves while the page is
    assembled it is built again; a page that mixes two moments is worse than
    one that says it could not settle."""
    if not configured():
        return {'error': 'GITHUB_RELEASE_TOKEN or GITHUB_REPO (owner/name) is not set, so GitHub cannot be asked.'}
    for _attempt in range(3):
        head, stable = _heads()
        if not head:
            return {'error': f'GitHub would not give the heads of {SOURCE} and {CHANNEL}.'}
        ov = _snapshot(head, stable)
        if ov.get('error'):
            return ov
        if _heads() == (head, stable):
            return ov
    return {'error': f'{SOURCE} or {CHANNEL} kept changing while the page was built. Reload it.'}


def _snapshot(head, stable):
    code, cmp_ = _call('GET', f'compare/{stable}...{head}', params={'per_page': 100})
    if code != 200 or not isinstance(cmp_, dict):
        return {'error': f'GitHub would not compare {CHANNEL} with {SOURCE} (status {code}).'}
    commits = [{'sha': c['sha'], 'short': c['sha'][:7],
                'message': (c['commit']['message'] or '').split('\n')[0],
                'author': (c.get('author') or {}).get('login')
                          or c['commit']['author']['name'],
                'url': c.get('html_url')} for c in cmp_.get('commits', [])]
    files = cmp_.get('files') or []
    jobs = commit_jobs(head)
    checks = check_states(jobs) if jobs is not None else []
    code, rel = _call('GET', 'contents/RELEASE', params={'ref': stable},
                      accept='application/vnd.github.raw+json')
    release_name = rel.split('\n')[0].strip() if code == 200 and isinstance(rel, str) else None
    runs_now = sorted(_workflow_runs(WORKFLOW) + _workflow_runs(ROLLBACK_WORKFLOW),
                      key=lambda r: r['created'], reverse=True)[:6]
    code, tag_rows = _call('GET', 'tags', params={'per_page': 100})
    current_tag, previous_tag = release_history(tag_rows if code == 200 else [], stable)
    return {
        'error': None,
        'stable_sha': stable, 'release': release_name,
        'main_sha': head, 'ahead': cmp_.get('ahead_by', 0), 'behind': cmp_.get('behind_by', 0),
        'commits': commits, 'files': files,
        'truncated': (cmp_.get('ahead_by', 0) > len(commits)) or len(files) >= 300,
        'flags': watch_flags(files),
        'additions': sum(f.get('additions', 0) for f in files),
        'deletions': sum(f.get('deletions', 0) for f in files),
        'current_tag': current_tag, 'previous_tag': previous_tag,
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


def rollback_blockers(ov):
    """Why Rollback is off. Empty means it may start."""
    if ov.get('error'):
        return [ov['error']]
    out = []
    if not ov.get('current_tag'):
        out.append(f'{CHANNEL} is not on a tagged release, so there is no known one to go back from.')
    elif not ov.get('previous_tag'):
        out.append(f'There is no release before {ov["current_tag"]} to go back to.')
    if ov['running']:
        out.append('A release or rollback is already running.')
    return out


def start_rollback(to_tag):
    """Ask GitHub to put akye-stable back on `to_tag`. (ok, message)."""
    if not re.fullmatch(re.escape(TAG_PREFIX) + r'\d{4}\.\d{2}\.\d{2}(\.\d+)?', to_tag or ''):
        return False, 'That is not a release.'
    code, _ = _call('POST', f'actions/workflows/{ROLLBACK_WORKFLOW}/dispatches',
                    json={'ref': SOURCE, 'inputs': {'to_tag': to_tag}})
    if code == 204:
        return True, None
    if code in (401, 403, 404):
        return False, ('GitHub refused: GITHUB_RELEASE_TOKEN needs to read the repository '
                       'and have Actions: read and write.')
    return False, f'GitHub did not start the rollback (status {code}).'


def start(expected_sha, expected_stable):
    """Ask GitHub to run the release of exactly `expected_sha` onto exactly
    `expected_stable`. (ok, message)."""
    if not (re.fullmatch(r'[0-9a-f]{40}', expected_sha or '')
            and re.fullmatch(r'[0-9a-f]{40}', expected_stable or '')):
        return False, 'That is not a commit.'
    code, body = _call('POST', f'actions/workflows/{WORKFLOW}/dispatches',
                       json={'ref': SOURCE, 'inputs': {'expected_sha': expected_sha,
                                                  'expected_stable': expected_stable}})
    if code == 204:
        return True, None
    if code in (401, 403, 404):
        return False, ('GitHub refused: GITHUB_RELEASE_TOKEN needs to read the repository '
                       'and have Actions: read and write.')
    return False, f'GitHub did not start the release (status {code}).'
