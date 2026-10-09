"""What is actually in the commercial call list, before anybody deletes any of it.

Written because "remove the ones with no email" sounds like tidying and is not.
Google Places returns a phone and a website and never an address to write to --
`Prospect.email` says so in the model: *asked for on the call; Places never has
it*. So an empty email does not mark a dead lead. It marks a business nobody has
spoken to yet, which is the entire point of a cold-calling list and the most
valuable thing in it.

This reports. By default it deletes nothing, and the thing it reports is not
one number but what each plausible rule would actually take -- and, for each,
how many of those rows carry a call history that no re-import brings back.

    python audit_prospects.py --slug dazzleandshine
    python audit_prospects.py --slug dazzleandshine --delete untouched
    python audit_prospects.py --slug dazzleandshine --delete untouched --write

The middle form still deletes nothing: it names every row it would remove so
the list can be read before it stops existing.
"""
import argparse
import sys

from sqlalchemy import text

import control_plane
import provisioning
import tenancy


# Each rule is a WHERE clause over `prospect`, with a sentence describing what
# it believes. The sentences matter as much as the SQL -- a rule nobody can
# state plainly is a rule nobody should run against live data.
RULES = {
    'no-email': (
        "coalesce(trim(email), '') = ''",
        'Every business with no email address. Reads as "dead leads" and is '
        'almost the opposite: Places never supplies an email, so this is '
        'mostly everybody you have not yet spoken to.',
    ),
    'untouched': (
        "coalesce(trim(email), '') = '' "
        "AND coalesce(attempts, 0) = 0 "
        "AND coalesce(trim(notes), '') = '' "
        "AND called_at IS NULL",
        'Imported, never called, no notes, no email. Nothing was ever learned '
        'about these, so nothing is lost by removing them -- this is the safe '
        'reading of "start again".',
    ),
    'unreachable': (
        "coalesce(trim(email), '') = '' AND coalesce(trim(phone), '') = ''",
        'No phone and no email. There is no way to contact these at all, '
        'however good the business might be.',
    ),
    'lost': (
        "stage = 'lost'",
        'Explicitly closed -- asked not to be contacted, or a real no.',
    ),
    'all': (
        '1=1',
        'Everything. A genuine fresh start, call history included.',
    ),
}


def _rows(conn, schema, where):
    conn.execute(text(f'SET search_path TO "{schema}", public'))
    return conn.execute(text(f"""
        SELECT id, business_name, phone, email, status, stage,
               coalesce(attempts, 0) AS attempts,
               called_at, next_action_date, renewal_date,
               coalesce(trim(notes), '') <> '' AS has_notes
        FROM prospect
        WHERE {where}
        ORDER BY business_name
    """)).mappings().all()


def _count(conn, schema, where):
    conn.execute(text(f'SET search_path TO "{schema}", public'))
    return conn.execute(
        text(f'SELECT count(*) FROM prospect WHERE {where}')).scalar() or 0


def _worked(conn, schema, where):
    """Of the rows this rule takes, how many carry work somebody did.

    The number that decides whether a rule is tidying or destruction. A row
    with attempts, a call date, notes, a scheduled follow-up or a renewal month
    took a phone call to produce and no re-import restores it.
    """
    conn.execute(text(f'SET search_path TO "{schema}", public'))
    return conn.execute(text(f"""
        SELECT count(*) FROM prospect
        WHERE ({where}) AND (
            coalesce(attempts, 0) > 0
            OR called_at IS NOT NULL
            OR coalesce(trim(notes), '') <> ''
            OR next_action_date IS NOT NULL
            OR renewal_date IS NOT NULL
            OR coalesce(trim(email), '') <> ''
        )
    """)).scalar() or 0


def shape(conn, schema):
    """The list as it stands, before any rule is applied."""
    conn.execute(text(f'SET search_path TO "{schema}", public'))
    row = conn.execute(text("""
        SELECT count(*) AS total,
               count(*) FILTER (WHERE coalesce(trim(email), '') <> '') AS with_email,
               count(*) FILTER (WHERE coalesce(trim(phone), '') <> '') AS with_phone,
               count(*) FILTER (WHERE coalesce(attempts, 0) > 0) AS called,
               count(*) FILTER (WHERE coalesce(trim(notes), '') <> '') AS with_notes,
               count(*) FILTER (WHERE next_action_date IS NOT NULL) AS scheduled,
               count(*) FILTER (WHERE renewal_date IS NOT NULL) AS with_renewal
        FROM prospect
    """)).mappings().first()
    stages = conn.execute(text("""
        SELECT coalesce(stage, 'new') AS stage, count(*) AS n
        FROM prospect GROUP BY 1 ORDER BY 2 DESC
    """)).mappings().all()
    return row, stages


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--slug', required=True, help='the tenant to look at')
    p.add_argument('--delete', choices=sorted(RULES), help='which rule to apply')
    p.add_argument('--write', action='store_true',
                   help='actually delete. Without it, the rows are only listed.')
    p.add_argument('--include-worked', action='store_true',
                   help='allow deleting rows that carry a call history')
    args = p.parse_args()

    engine = provisioning._engine()
    if engine.dialect.name != 'postgresql':
        sys.exit('This reads a tenant schema, which only PostgreSQL has. '
                 'Set DATABASE_URL to the Railway database.')

    org = control_plane.find(engine, args.slug)
    if not org:
        sys.exit(f'No company called {args.slug!r} on this deployment.')
    schema = org.get('schema_name') or tenancy.schema_for(args.slug)

    with engine.connect() as conn:
        row, stages = shape(conn, schema)
        print(f'\n{org.get("name") or args.slug} — {row["total"]} businesses in the call list\n')
        print(f'  with an email address   {row["with_email"]:>6}'
              '   ← spoken to; worth keeping')
        print(f'  with a phone number     {row["with_phone"]:>6}'
              '   ← callable, which is the point of the list')
        print(f'  called at least once    {row["called"]:>6}')
        print(f'  carrying call notes     {row["with_notes"]:>6}')
        print(f'  with a follow-up booked {row["scheduled"]:>6}')
        print(f'  with a renewal month    {row["with_renewal"]:>6}'
              '   ← the ones that wake themselves')
        print('\n  by stage:')
        for s in stages:
            print(f'    {s["stage"]:<12} {s["n"]:>6}')

        print('\nWhat each rule would remove:\n')
        for name, (where, why) in sorted(RULES.items()):
            n = _count(conn, schema, where)
            w = _worked(conn, schema, where)
            mark = '  ' if not w else '⚠ '
            print(f'{mark}{name:<12} {n:>6} rows'
                  + (f', {w} of them with work done on them' if w else ''))
            print(f'              {why}\n')

        if not args.delete:
            print('Nothing was changed. Re-run with --delete <rule> to see the '
                  'exact rows a rule takes.')
            return

        where, why = RULES[args.delete]
        rows = _rows(conn, schema, where)
        worked = _worked(conn, schema, where)
        print(f'--- {args.delete}: {len(rows)} rows ---')
        print(f'{why}\n')
        for r in rows:
            flags = []
            if r['attempts']:
                flags.append(f'{r["attempts"]} attempt(s)')
            if r['has_notes']:
                flags.append('notes')
            if r['next_action_date']:
                flags.append(f'due {r["next_action_date"]}')
            if r['renewal_date']:
                flags.append(f'renews {r["renewal_date"]}')
            if r['email']:
                flags.append(r['email'])
            print(f'  {r["business_name"]}'
                  + (f'  [{", ".join(flags)}]' if flags else ''))

        if worked and not args.include_worked:
            sys.exit(f'\nRefusing: {worked} of these carry a call history — '
                     'attempts, notes, a booked follow-up, a renewal month or '
                     'an email somebody asked for on a call. None of that comes '
                     'back with a re-import. Re-run with --include-worked if '
                     'that is genuinely what you want.')

        if not args.write:
            print(f'\nDry run — nothing deleted. Add --write to remove these '
                  f'{len(rows)} rows.')
            return

    with engine.begin() as conn:
        conn.execute(text(f'SET search_path TO "{schema}", public'))
        n = conn.execute(text(f'DELETE FROM prospect WHERE {where}')).rowcount
    print(f'\nDeleted {n} rows.')


if __name__ == '__main__':
    main()
