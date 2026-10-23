"""Tell the console that a background job ran.

Backups and the central scheduler run on GitHub's machines, not ours, so the
product cannot see them finish. Each calls this when it is done and says how it
went; the console's Health page then shows when each last succeeded, and flags
the ones that have gone quiet.

    python3 platform_report.py backup:akye --ok true --items 1200000 --detail "12 companies"
    python3 platform_report.py backup:akye --ok false --detail "restore check failed"

Needs the same two things the scheduler needs:

    BASE_DOMAIN        akyehq.com, to find the product's own address
    REMINDER_API_KEY   the key /api/platform-run checks

## It must never be the reason a job fails

A backup that worked and then could not say so is still a backup. So `report`
returns (ok, detail) and never raises, and the command line exits 0 whatever
happens: a missing key or an unreachable product is printed as a warning, not
turned into a red build.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

TIMEOUT = 20


def _host():
    base = (os.environ.get('BASE_DOMAIN') or '').strip().lower()
    explicit = (os.environ.get('PRODUCT_HOST') or '').strip().lower().strip('/')
    if explicit:
        return explicit
    if not base:
        return ''
    return base if base.startswith('www.') else f'www.{base}'


def report(kind, ok=True, items=None, detail=None):
    """Send one run to the product. Returns (sent, message); never raises."""
    host = _host()
    key = (os.environ.get('REMINDER_API_KEY') or '').strip()
    if not host or not key:
        return False, 'BASE_DOMAIN or REMINDER_API_KEY is not set, so nothing was reported'
    body = json.dumps({'kind': kind, 'ok': bool(ok), 'items': items,
                       'detail': (detail or '')[:400]}).encode()
    req = urllib.request.Request(
        f'https://{host}/api/platform-run', data=body, method='POST',
        headers={'Content-Type': 'application/json', 'X-Api-Key': key})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return True, f'reported {kind} ({r.status})'
    except urllib.error.HTTPError as e:
        hint = ' (REMINDER_API_KEY does not match the one the app expects)' if e.code == 403 else ''
        return False, f'HTTP {e.code}{hint}'
    except Exception as e:  # noqa: BLE001
        return False, f'{type(e).__name__}: {e}'


def main(argv=None):
    p = argparse.ArgumentParser(description='Report a background job to the console.')
    p.add_argument('kind', help='for example backup:akye or scheduler:daily')
    p.add_argument('--ok', default='true', help='true or false')
    p.add_argument('--items', type=int, default=None)
    p.add_argument('--detail', default='')
    args = p.parse_args(argv)
    sent, message = report(args.kind, args.ok.strip().lower() in ('1', 'true', 'yes', 'ok'),
                           args.items, args.detail)
    print(('✅ ' if sent else '⚠️  ') + message, file=sys.stdout)
    return 0


if __name__ == '__main__':
    sys.exit(main())
