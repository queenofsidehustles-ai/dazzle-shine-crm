"""Find every solo job whose cleaner is a name that no longer points at one person.

A solo job records its cleaner as a NAME (`Booking.assigned_cleaner` is a
String), while crew jobs are keyed by `BookingCrew.staff_id`. Payroll reconciles
the two by matching the name, case-insensitively, taking the first row back
(`contractor_pay.match_staff`). So the name is the only handle the money has:

  * a name matching NO staff row pays nobody — the work is invisible on the
    only screen that could pay for it;
  * a name matching MORE THAN ONE pays whichever row comes back first, which
    can be the wrong person for someone else's work.

This is the audit that has to run before `booking.assigned_staff_id` can exist,
because a backfill can only resolve the names that match exactly one person.
The rows this reports are the ones no migration can decide — they need a human
who knows who actually cleaned the house.

Read-only. It reports; it does not touch a row. Crew jobs are counted
separately and are not money-at-risk: their pay comes from the crew rows, so a
stale lead NAME on one is cosmetic.

Usage:
    python audit_assigned_cleaner.py                  # every active org
    python audit_assigned_cleaner.py --slug foo       # one tenant only
    python audit_assigned_cleaner.py --all-statuses   # include suspended/closed
    python audit_assigned_cleaner.py --verbose        # list every affected row
"""
import argparse
import sys

from sqlalchemy import text

import control_plane
import provisioning
import tenancy


# One row per booking that names a cleaner, with everything needed to classify
# it: how many staff rows that name matches, whether the job has crew (in which
# case pay does not depend on the name), and whether anybody has been paid.
_ROWS = """
    SELECT b.id, b.assigned_cleaner, b.status, b.preferred_date, b.price,
           b.name AS customer_name,
           (SELECT count(*) FROM staff s
             WHERE lower(trim(s.name)) = lower(trim(b.assigned_cleaner))) AS matches,
           (SELECT count(*) FROM booking_crew bc
             WHERE bc.booking_id = b.id) AS crew_rows,
           (SELECT count(*) FROM contractor_payment cp
             WHERE cp.booking_id = b.id AND cp.status = 'paid') AS paid_rows
    FROM booking b
    WHERE coalesce(trim(b.assigned_cleaner), '') <> ''
    ORDER BY b.id
"""

# The ambiguity my duplicate-name guard stops being created from now on. It says
# nothing about the pairs already in the database.
_DUPES = """
    SELECT lower(trim(name)) AS key, count(*) AS n,
           string_agg(id || ':' || name, ', ' ORDER BY id) AS who
    FROM staff
    WHERE coalesce(trim(name), '') <> ''
    GROUP BY lower(trim(name))
    HAVING count(*) > 1
    ORDER BY count(*) DESC
"""


def _scan(engine, schema):
    with engine.connect() as conn:
        conn.execute(text(f'SET search_path TO "{schema}", public'))
        rows = [dict(r) for r in conn.execute(text(_ROWS)).mappings().all()]
        dupes = [dict(r) for r in conn.execute(text(_DUPES)).mappings().all()]
    return rows, dupes


def _classify(rows):
    """Split the rows by what a backfill could do with them."""
    out = {'resolvable': [], 'orphan': [], 'ambiguous': [], 'crew_cosmetic': []}
    for r in rows:
        if r['crew_rows']:
            # Pay comes from the crew rows; the name is a label here.
            if r['matches'] != 1:
                out['crew_cosmetic'].append(r)
            continue
        if r['matches'] == 1:
            out['resolvable'].append(r)
        elif r['matches'] == 0:
            out['orphan'].append(r)
        else:
            out['ambiguous'].append(r)
    return out


def _unpaid_completed(rows):
    """Of these, the ones that are finished and that nobody has been paid for —
    money somebody is owed and cannot currently be routed to them."""
    return [r for r in rows
            if (r['status'] or '') == 'completed' and not r['paid_rows']]


def _money(rows):
    return sum(float(r['price'] or 0) for r in rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--slug', help='audit one tenant only, by slug')
    parser.add_argument('--all-statuses', action='store_true',
                        help='include suspended/closed orgs, not just active ones')
    parser.add_argument('--verbose', action='store_true',
                        help='list every affected booking, not just the counts')
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

    audited = 0
    totals = {'resolvable': 0, 'orphan': 0, 'ambiguous': 0, 'crew_cosmetic': 0}
    blocked = 0          # rows a backfill cannot decide
    at_risk = 0          # of those, finished and unpaid
    at_risk_money = 0.0

    for org in orgs:
        slug = org.get('slug')
        schema = org.get('schema_name') or tenancy.schema_for(slug)
        try:
            rows, dupes = _scan(engine, schema)
        except Exception as exc:
            # A schema missing one of these tables (very old tenant, or
            # mid-migration) is a skip, not a crash. This audits what exists.
            print(f'  {slug}: could not audit ({type(exc).__name__}: {exc})')
            continue
        audited += 1
        c = _classify(rows)
        for k in totals:
            totals[k] += len(c[k])

        undecidable = c['orphan'] + c['ambiguous']
        blocked += len(undecidable)
        owed = _unpaid_completed(undecidable)
        at_risk += len(owed)
        at_risk_money += _money(owed)

        if not undecidable and not dupes:
            continue

        print(f'\n  {org.get("name") or slug} ({slug}):')
        print(f'    {len(c["resolvable"])} solo job(s) a backfill can resolve outright')
        if c['orphan']:
            print(f'    {len(c["orphan"])} name(s) matching NO team member')
        if c['ambiguous']:
            print(f'    {len(c["ambiguous"])} name(s) matching MORE THAN ONE team member')
        if c['crew_cosmetic']:
            print(f'    {len(c["crew_cosmetic"])} crew job(s) with a stale lead name '
                  f'(cosmetic — pay comes from the crew rows)')
        if owed:
            print(f'    ⚠️  {len(owed)} of these are completed and unpaid, '
                  f'${_money(owed):,.2f} of customer price')
        for d in dupes:
            print(f'    ⚠️  {d["n"]} team members share the name '
                  f'"{d["key"]}" → {d["who"]} — pay for either can land on the other')

        if args.verbose:
            for label, rs in (('no match', c['orphan']),
                              ('ambiguous', c['ambiguous'])):
                for r in rs:
                    flag = ' ← completed, unpaid' if (
                        (r['status'] or '') == 'completed' and not r['paid_rows']) else ''
                    print(f'      booking #{r["id"]} ({label}): '
                          f'assigned_cleaner={r["assigned_cleaner"]!r}, '
                          f'customer={r["customer_name"]!r}, {r["preferred_date"]}, '
                          f'status={r["status"]}, price={r["price"]}{flag}')

    print(f'\n  Audited {audited} tenant schema(s).')
    print(f'    {totals["resolvable"]} solo job(s) a backfill resolves outright')
    print(f'    {totals["orphan"]} with a name matching nobody')
    print(f'    {totals["ambiguous"]} with a name matching several people')
    print(f'    {totals["crew_cosmetic"]} crew job(s) with a stale lead name (cosmetic)')
    print(f'\n  {blocked} row(s) no migration can decide.')
    if at_risk:
        print(f'  {at_risk} of them are completed and unpaid — ${at_risk_money:,.2f} of '
              f'customer price whose cleaner payroll cannot currently find.')
    if blocked:
        print('  Nothing was changed. Each needs somebody who knows who cleaned the '
              'house: a misspelt name, a cleaner who left before Staff rows existed, '
              'or two people who share one.')
    else:
        print('  Every named solo job resolves to exactly one team member, so a '
              'backfill can be complete rather than partial.')
    # Non-zero while anything still needs a human, so the backfill can be gated
    # on a clean run rather than on somebody remembering to read the output.
    return 1 if blocked else 0


if __name__ == '__main__':
    sys.exit(main())
