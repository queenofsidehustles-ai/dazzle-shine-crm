#!/usr/bin/env python3
"""Move one already-running business's data into its own tenant schema.

For a business that has been operating on the single-company codebase (its
own Postgres, one flat set of tables) and is moving onto the multi-company
product, where every business lives in its own Postgres schema inside one
database. The schema itself is not this script's job — run
`provisioning.py create <slug> "<name>"` against the target database first,
the ordinary way any new company gets a schema, built by the same migrations
as everyone else's. This script only carries the rows across, once that
schema exists and is still empty.

    SOURCE_DATABASE_URL=postgresql://...old-single-tenant-db... \\
    DATABASE_URL=postgresql://...new-multi-tenant-db... \\
    python3 adopt_tenant.py dazzleandshine

Prints what it would copy and changes nothing until you add --apply. Safe to
run the dry run as many times as you like.

## Why row-by-row over the network instead of one SQL statement

The old business and the new tenant almost never share a Postgres server —
they are two different managed databases, sometimes two different
providers — so there is no single connection a plain `INSERT ... SELECT`
could run over. dblink/postgres_fdw could bridge them, but that needs an
extension enabled on a managed database we may not control. Reading rows out
of the source and writing them into the target, table by table, works
regardless of what either provider allows.

## Why only the columns both schemas share

The target schema was built by the *current* migrations, which have moved on
since the source schema was last touched — new tables, occasionally a new
column on an old table. Copying every source column blind would fail the
moment a table gained a column the source never had. Copying only the
intersection, by name, is exactly right for a purely additive schema (a
column the target dropped that the source still has would silently lose
data, so that case is refused, not guessed past — see --allow-dropped-columns).

## Why it stops at a table that already has rows

Re-running an interrupted copy should not double-insert into a table that
finished. A tenant schema is otherwise empty until this script runs, so any
row in a target table is either evidence of a previous partial run or evidence
that something else already wrote here — a --dry-run always reports it,
--apply skips that table rather than guess which case it is.
"""
import argparse
import os
import sys

from sqlalchemy import create_engine, text


def _engine(url, label):
    if not url:
        raise SystemExit(f'{label} is not set.')
    return create_engine(url.replace('postgres://', 'postgresql://', 1))


def _tables(conn, schema):
    rows = conn.execute(text("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = :s AND table_type = 'BASE TABLE'
    """), {'s': schema}).fetchall()
    return {r[0] for r in rows}


def _columns(conn, schema, table):
    rows = conn.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = :s AND table_name = :t
        ORDER BY ordinal_position
    """), {'s': schema, 't': table}).fetchall()
    return [r[0] for r in rows]


def _fk_edges(conn, schema):
    """(child_table, parent_table) for every foreign key inside one schema."""
    rows = conn.execute(text("""
        SELECT tc.table_name, ccu.table_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = :s
    """), {'s': schema}).fetchall()
    return [(r[0], r[1]) for r in rows if r[0] != r[1]]


def _topological_order(tables, edges):
    """Parents before children. Ties broken alphabetically, for stable output."""
    remaining = set(tables)
    blocked_on = {t: set() for t in tables}
    for child, parent in edges:
        if child in blocked_on and parent in remaining:
            blocked_on[child].add(parent)

    ordered = []
    while remaining:
        ready = sorted(t for t in remaining if not (blocked_on[t] & remaining))
        if not ready:
            # A cycle: break it deterministically rather than hang.
            ready = [sorted(remaining)[0]]
        for t in ready:
            ordered.append(t)
            remaining.discard(t)
    return ordered


def _row_count(conn, schema, table):
    return conn.execute(text(f'SELECT count(*) FROM "{schema}"."{table}"')).scalar()


def plan(src_conn, dst_conn, dst_schema, allow_dropped_columns):
    src_tables = _tables(src_conn, 'public') - {'alembic_version'}
    dst_tables = _tables(dst_conn, dst_schema) - {'alembic_version'}
    shared = sorted(src_tables & dst_tables)
    only_source = sorted(src_tables - dst_tables)
    edges = _fk_edges(src_conn, 'public')
    order = [t for t in _topological_order(shared, edges) if t in shared]

    if only_source and not allow_dropped_columns:
        names = ', '.join(only_source)
        raise SystemExit(
            f'The source has tables the target schema does not: {names}\n'
            'Those rows would be silently lost. Confirm that is expected and '
            'pass --allow-dropped-columns to proceed, or reconcile the schema '
            'first.')

    steps = []
    for table in order:
        src_cols = _columns(src_conn, 'public', table)
        dst_cols = set(_columns(dst_conn, dst_schema, table))
        common = [c for c in src_cols if c in dst_cols]
        dropped = [c for c in src_cols if c not in dst_cols]
        if dropped and not allow_dropped_columns:
            names = ', '.join(dropped)
            raise SystemExit(
                f'{table}: the target is missing column(s) the source has: '
                f'{names}\nThat data would be silently lost. Pass '
                '--allow-dropped-columns to proceed anyway (those columns will '
                'be skipped), or reconcile the schema first.')
        steps.append((table, common, dropped))
    return steps


def run(source_url, target_url, slug, apply_, batch_size, allow_dropped_columns):
    src_engine = _engine(source_url, 'SOURCE_DATABASE_URL')
    dst_engine = _engine(target_url, 'DATABASE_URL')
    dst_schema = f'tenant_{slug}'

    with src_engine.connect() as src_conn, dst_engine.connect() as dst_conn:
        existing = dst_conn.execute(text(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"
        ), {'s': dst_schema}).first()
        if not existing:
            raise SystemExit(
                f'{dst_schema!r} does not exist yet. Provision it first:\n'
                f'  python3 provisioning.py create {slug} "<business name>"')

        steps = plan(src_conn, dst_conn, dst_schema, allow_dropped_columns)

        print(f'\n  {"table":<26}{"rows":>8}   columns carried over')
        print('  ' + '-' * 70)
        total_rows = 0
        for table, common, dropped in steps:
            n = _row_count(src_conn, 'public', table)
            total_rows += n
            note = f'  (dropping: {", ".join(dropped)})' if dropped else ''
            print(f'  {table:<26}{n:>8}   {len(common)} of {len(common) + len(dropped)}{note}')
        print(f'\n  {total_rows} rows total, into {dst_schema}\n')

        if not apply_:
            print('  Dry run only — nothing was written. Add --apply to copy it for real.\n')
            return

        for table, common, _dropped in steps:
            already = _row_count(dst_conn, dst_schema, table)
            if already:
                print(f'  ⚠️  {dst_schema}.{table} already has {already} row(s) — '
                      'skipping (looks like a previous run already copied it).')
                continue

            col_list = ', '.join(f'"{c}"' for c in common)
            select_sql = text(f'SELECT {col_list} FROM "public"."{table}"')
            placeholders = ', '.join(f':{c}' for c in common)
            insert_sql = text(
                f'INSERT INTO "{dst_schema}"."{table}" ({col_list}) '
                f'VALUES ({placeholders})')

            rows = src_conn.execute(select_sql).mappings().all()
            with dst_engine.begin() as tx:
                for i in range(0, len(rows), batch_size):
                    batch = rows[i:i + batch_size]
                    if batch:
                        tx.execute(insert_sql, [dict(r) for r in batch])
            print(f'  ✅ {table}: {len(rows)} row(s)')

        print('\n  Resetting sequences so the next new row does not collide '
              'with an imported id...')
        with dst_engine.begin() as tx:
            for table, common, _dropped in steps:
                if 'id' not in common:
                    continue
                tx.execute(text(f"""
                    SELECT setval(
                        pg_get_serial_sequence('"{dst_schema}"."{table}"', 'id'),
                        COALESCE((SELECT max(id) FROM "{dst_schema}"."{table}"), 1),
                        (SELECT max(id) IS NOT NULL FROM "{dst_schema}"."{table}")
                    ) WHERE pg_get_serial_sequence('"{dst_schema}"."{table}"', 'id') IS NOT NULL
                """))
        print(f'\n  ✅ {slug} adopted. {total_rows} rows now live in {dst_schema}.\n')


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('slug', help='the tenant address this business is moving to, '
                                 'e.g. dazzleandshine')
    p.add_argument('--apply', action='store_true',
                    help='actually copy the rows (default is a dry run)')
    p.add_argument('--allow-dropped-columns', action='store_true',
                    help='proceed even if the target schema is missing a source '
                         'table or column (that data will be left behind)')
    p.add_argument('--batch-size', type=int, default=500)
    args = p.parse_args()

    source_url = os.environ.get('SOURCE_DATABASE_URL', '')
    target_url = os.environ.get('DATABASE_URL', '')
    run(source_url, target_url, args.slug, args.apply, args.batch_size,
        args.allow_dropped_columns)


if __name__ == '__main__':
    sys.exit(main() or 0)
