"""Find TimeEntry rows clocked against a job the worker was never assigned to.

IDOR-01 (docs/launch-readiness/decision-evidence-register.md) fixed
clock_in()/clock_out() so this can no longer be created going forward: they
took booking_id from the request with no check that the worker holding the
token was actually assigned to that job. This script is the other half —
finding any row that fix came too late for, on either a real booking
assignment (assigned_cleaner) or a crew slot (BookingCrew).

Read-only. It reports; it does not touch a row. Correcting or removing a
payroll-affecting TimeEntry is a decision for whoever runs this, not
something to automate — a mismatch found here might be exactly what this
script assumes (a clock-in that should never have been possible), or it might
be a booking reassigned after the fact for an ordinary operational reason,
which this script cannot tell apart from the outside.

Usage:
    python audit_time_entry_assignment.py              # every active org
    python audit_time_entry_assignment.py --slug foo    # one tenant only
    python audit_time_entry_assignment.py --all-statuses  # include
        suspended/closed orgs too (their schemas may still hold data)
"""
import argparse
import sys

from sqlalchemy import text

import control_plane
import provisioning
import tenancy


def _mismatched_entries(engine, schema):
    """Rows in this schema where the clocked staff member was on neither the
    booking's solo assignment nor its crew. Returns a list of dict rows."""
    with engine.connect() as conn:
        conn.execute(text(f'SET search_path TO "{schema}", public'))
        rows = conn.execute(text("""
            SELECT te.id AS entry_id, te.booking_id, te.staff_id,
                   te.clock_in_at, te.clock_out_at, te.created_at,
                   s.name AS staff_name, b.assigned_cleaner, b.name AS customer_name,
                   b.preferred_date, b.status AS booking_status
            FROM time_entry te
            JOIN staff s ON s.id = te.staff_id
            JOIN booking b ON b.id = te.booking_id
            WHERE lower(trim(coalesce(b.assigned_cleaner, ''))) != lower(trim(s.name))
              AND NOT EXISTS (
                  SELECT 1 FROM booking_crew bc
                  WHERE bc.booking_id = te.booking_id AND bc.staff_id = te.staff_id
              )
            ORDER BY te.created_at
        """)).mappings().all()
    return [dict(r) for r in rows]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--slug', help='audit one tenant only, by slug')
    parser.add_argument('--all-statuses', action='store_true',
                        help='include suspended/closed orgs, not just active ones')
    args = parser.parse_args(argv)

    engine = provisioning._engine()
    control_plane.ensure_table(engine)

    if args.slug:
        org = control_plane.find(engine, args.slug)
        if not org:
            print(f'  No company called {args.slug!r}.')
            return 1
        orgs = [org]
    else:
        orgs = control_plane.all_orgs(engine)
        if not args.all_statuses:
            orgs = [o for o in orgs if (o.get('status') or 'active') == 'active']

    total_mismatches = 0
    audited = 0
    for org in orgs:
        slug = org.get('slug')
        schema = org.get('schema_name') or tenancy.schema_for(slug)
        try:
            mismatches = _mismatched_entries(engine, schema)
        except Exception as exc:
            # A schema that doesn't have time_entry/booking_crew yet (very old
            # tenant, mid-migration) is a skip, not a crash — this audits what
            # exists, it does not assume every schema is current.
            print(f'  {slug}: could not audit ({type(exc).__name__}: {exc})')
            continue
        audited += 1
        if not mismatches:
            continue
        total_mismatches += len(mismatches)
        print(f'\n  {org.get("name") or slug} ({slug}) — {len(mismatches)} mismatch(es):')
        for m in mismatches:
            print(
                f'    TimeEntry #{m["entry_id"]}: {m["staff_name"]!r} (staff_id={m["staff_id"]}) '
                f'clocked on booking #{m["booking_id"]} ({m["customer_name"]!r}, '
                f'{m["preferred_date"]}, status={m["booking_status"]}), '
                f'assigned_cleaner={m["assigned_cleaner"]!r}, '
                f'in={m["clock_in_at"]}, out={m["clock_out_at"]}, '
                f'created={m["created_at"]}'
            )

    print(f'\n  Audited {audited} tenant schema(s). {total_mismatches} mismatched TimeEntry row(s) found.')
    if total_mismatches:
        print('  Nothing was changed. Each row above needs a human read: it may be the '
              'exact clock-in this audit exists to catch, or an ordinary reassignment '
              'after the fact — this script cannot tell those apart.')
    return 1 if total_mismatches else 0


if __name__ == '__main__':
    sys.exit(main())
