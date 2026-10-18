#!/usr/bin/env python3
"""Evidence for the quotation release gate, one command per gate.

    python3 certify.py schema               # G1: every company's tables, guards, version
    python3 certify.py evidence             # G1/G5: hashes, links and the audit chain
    python3 certify.py compare MANIFEST     # G5/G6: the database against a backup manifest
    python3 certify.py journey --company S  # G2: issue -> accept -> amend, on a demo company

On production, through Railway, so the database password never leaves it:

    railway run python3 certify.py schema --out g1-schema.json

schema, evidence and compare are read-only: they open their transaction READ
ONLY, so the database refuses any write they could make. They print a summary
and, with --out, write the full result as JSON -- ids, hashes and counts, no
customer names or addresses. The exit code is 0 for a pass, 1 for a problem.

journey is the one that writes, and only to a company marked is_demo (refused
anywhere else): it creates, sends, accepts and amends a certification
proposal through the app's own routes, exactly as an owner and a customer
would, then checks every record it made. The demo company never sends
anything (demo_guard), so the send goes to a recording stub here and the
evidence says so; the real mail provider is G4's to prove. It refuses to run
unless the database is on this code's migration head, so it cannot be the
thing that migrates production. See docs/certification/RUNBOOK.md.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def _engine():
    import backup
    return backup._read_engine()


def _emit(result, out, ok_line):
    problems = [p for section in result.get('sections', []) for p in section.get('problems', [])]
    problems += result.get('problems', [])
    result['passed'] = not problems
    result['checked_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    if out:
        with open(out, 'w') as fh:
            json.dump(result, fh, indent=2, default=str)
    for p in problems:
        print(f'  ❌ {p}')
    for section in result.get('sections', []):
        for e in section.get('exceptions', []):
            print(f'  ⚠️  {e}')
    print(f'\n{"✅ " + ok_line if not problems else f"❌ {len(problems)} problem(s)"}'
          + (f' — full result in {out}' if out else ''))
    return 0 if not problems else 1


def _schemas(conn, only=None):
    """Every company schema, or those named. A name that matches none is a
    problem, not an empty pass: a typo must not certify nothing."""
    import evidence_check
    import tenancy
    inv = evidence_check.inventory(conn)
    schemas = inv['schemas']
    if only:
        wanted = {name if name.startswith(tenancy.SCHEMA_PREFIX) else tenancy.SCHEMA_PREFIX + name
                  for name in only}
        inv['problems'] += [f'no company schema {w}' for w in sorted(wanted - set(schemas))]
        schemas = [s for s in schemas if s in wanted]
    return inv, schemas


def cmd_schema(args):
    import evidence_check
    engine = _engine()
    with engine.connect() as conn, conn.begin():
        evidence_check.read_only(conn)
        inv, schemas = _schemas(conn, args.company)
        sections = [evidence_check.schema_report(conn, s) for s in schemas]
    for s in sections:
        mark = '✅' if not s['problems'] else '❌'
        print(f'  {mark} {s["schema"]:<36} {s["version"]}')
    login = sections[0]['login'] if sections else {}
    if login.get('owns_evidence_tables') or login.get('superuser'):
        print(f'  ℹ️  connected as {login.get("user")}, which can switch the guards off '
              '(owner/superuser); the audit chain and the backup manifest are what show such a change.')
    return _emit({'command': 'schema', 'inventory': inv, 'sections': sections,
                  'problems': inv['problems']}, args.out,
                 f'{len(sections)} company schema(s) on {evidence_check.head_revision()}, every guard on')


def cmd_evidence(args):
    import evidence_check
    engine = _engine()
    sections = []
    with engine.connect() as conn, conn.begin():
        evidence_check.read_only(conn)
        inv, schemas = _schemas(conn, args.company)
        problems = inv['problems'] if args.company else []
        for s in schemas:
            rec = evidence_check.reconcile(conn, s)
            chain = evidence_check.audit_chain(conn, s)
            rec['problems'] += chain['problems']
            rec['audit_chain'] = {'length': chain['length'], 'head': chain['head']}
            sections.append(rec)
            mark = '✅' if not rec['problems'] else '❌'
            c = rec['counts']
            print(f'  {mark} {s:<36} {c.get("accepted_quotes", 0)} accepted, '
                  f'{c.get("agreements", 0)} agreements, {chain["length"]} audit entries')
    return _emit({'command': 'evidence', 'sections': sections, 'problems': problems}, args.out,
                 'every hash, link and audit chain checks out')


def cmd_compare(args):
    import evidence_check
    with open(args.manifest) as fh:
        manifest = json.load(fh)
    written = manifest.get('evidence') or {}
    if not written:
        print('  ❌ that manifest has no evidence digest (taken before certify existed?)')
        return 1
    engine = _engine()
    sections = []
    with engine.connect() as conn, conn.begin():
        evidence_check.read_only(conn)
        _, schemas = _schemas(conn)
        schemas = ['public'] + schemas
        for schema, then in sorted(written.items()):
            if schema not in schemas:
                sections.append({'schema': schema, 'problems': [f'{schema} is gone']})
                continue
            sections.append(evidence_check.compare(conn, schema, then))
    return _emit({'command': 'compare', 'manifest': os.path.basename(args.manifest),
                  'taken_at': manifest.get('taken_at'), 'sections': sections}, args.out,
                 f'everything written down at {manifest.get("taken_at")} is still there, unchanged')


# ---------------------------------------------------------------------------

def cmd_journey(args):
    import journey
    return _emit(journey.run(args.company), args.out,
                 'issue → accept → amend: every record made and every check passed')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('schema', 'evidence'):
        sp = sub.add_parser(name)
        sp.add_argument('--company', action='append', help='only this company (slug); repeatable')
        sp.add_argument('--out')
    sp = sub.add_parser('compare')
    sp.add_argument('manifest')
    sp.add_argument('--out')
    sp = sub.add_parser('journey')
    sp.add_argument('--company', required=True, help='a company marked is_demo')
    sp.add_argument('--out')
    args = ap.parse_args(argv)
    return {'schema': cmd_schema, 'evidence': cmd_evidence, 'compare': cmd_compare,
            'journey': cmd_journey}[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())
