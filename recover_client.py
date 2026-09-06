#!/usr/bin/env python3
"""Bring one deleted customer back, out of a backup, without touching anybody else.

Deleting a client deletes their bookings, and with the bookings goes every job
checklist — the before-and-after photos, the arrival and finish times, the
signature — and every rating. That is the evidence a card network asks for when
a charge is disputed, and it is deleted quietly by a button labelled "Delete
Client".

The obvious recovery is to restore last night's backup, and it is the wrong one:
it would take the whole database back to that night and throw away every booking,
payment and message since. This does the opposite — it reads one customer out of
a backup and writes only their rows, leaving everything else exactly as it is.

    python3 recover_client.py BACKUP.json.gz.enc --find "Susan Mills"
    python3 recover_client.py BACKUP.json.gz.enc --find "Susan Mills" --restore

Without --restore it prints what it would do and changes nothing. Run it that
way first; it is the same search either way.

The passphrase is asked for at the prompt, never taken as an argument — an
argument is visible to anyone running `ps` and is saved in shell history. The
decrypted copy is written to a private temporary directory and shredded on the
way out, however the program exits.
"""
import argparse
import getpass
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile

# The tables that belong to a customer, parents before children, so a row is
# never written before the row it points at.
CHILDREN = (
    ('booking', 'client_id'),
    ('job_checklist', 'booking_id'),
    ('booking_rating', 'booking_id'),
    ('booking_crew', 'booking_id'),
)


def decrypt(path, passphrase):
    """openssl, matching exactly what the backup workflow used to encrypt."""
    out = os.path.join(tempfile.mkdtemp(prefix='recover-', dir=None), 'backup.json.gz')
    os.chmod(os.path.dirname(out), 0o700)
    # -pass stdin, not -pass pass:… — a passphrase on the command line is
    # visible to anyone who can run `ps` while this is going.
    proc = subprocess.run(
        ['openssl', 'enc', '-d', '-aes-256-cbc', '-pbkdf2', '-pass', 'stdin',
         '-in', path, '-out', out],
        input=(passphrase + '\n').encode(), capture_output=True)
    if proc.returncode != 0:
        shutil.rmtree(os.path.dirname(out), ignore_errors=True)
        err = proc.stderr.decode(errors='replace').strip()
        raise SystemExit(f'Could not decrypt that file.\n{err}\n\n'
                         'The usual cause is the wrong passphrase — it must be the '
                         'BACKUP_PASSPHRASE secret exactly, with no trailing space.')
    return out


def read_rows(path):
    """Every row in the dump, as (table, dict)."""
    with gzip.open(path, 'rt', encoding='utf-8') as fh:
        header = json.loads(fh.readline())
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            # Dates, decimals and blobs are tagged in the dump and have to be
            # turned back into real objects before a database will take them.
            # backup.py already knows how — reusing it means the restore cannot
            # decode a backup differently from the tool that wrote it.
            import backup
            yield rec['__table__'], backup._revive_row(rec['row'])
    return header


def collect(dump_path, needle):
    """The customer and everything hanging off them."""
    needle = needle.lower().strip()
    rows = {}
    for table, row in read_rows(dump_path):
        rows.setdefault(table, []).append(row)

    clients = [c for c in rows.get('client', [])
               if needle in (c.get('name') or '').lower()
               or needle in (c.get('email') or '').lower()]
    if not clients:
        return None, rows

    client = clients[0]
    found = {'client': client, 'extra_matches': clients[1:]}
    bookings = [b for b in rows.get('booking', [])
                if b.get('client_id') == client.get('id')]
    # A booking can carry the customer's name and no client_id at all — the
    # older ones predate clients existing. Those are theirs too and are exactly
    # the vintage a July job would be.
    for b in rows.get('booking', []):
        if b in bookings:
            continue
        if needle in (b.get('name') or '').lower() or (
                client.get('email') and
                (b.get('email') or '').lower() == (client.get('email') or '').lower()):
            bookings.append(b)
    found['booking'] = bookings
    ids = {b['id'] for b in bookings}
    for table, fk in CHILDREN[1:]:
        found[table] = [r for r in rows.get(table, []) if r.get(fk) in ids]
    return found, rows


def describe(found):
    c = found['client']
    print(f"\n  Customer   {c.get('name')}  <{c.get('email') or 'no email'}>  "
          f"{c.get('phone') or 'no phone'}")
    print(f"  Address    {c.get('address') or '—'}, {c.get('city') or ''} "
          f"{c.get('zip_code') or ''}".rstrip())
    print(f"\n  {len(found['booking'])} booking(s):")
    for b in found['booking']:
        paid = b.get('paid_at') or '—'
        print(f"    #{b['id']:<5} {b.get('preferred_date') or '?':<12} "
              f"{(b.get('service_type') or '?'):<10} ${b.get('price') or 0:<8} "
              f"paid {paid}")
        if b.get('stripe_payment_intent'):
            print(f"           Stripe payment intent: {b['stripe_payment_intent']}")
        if b.get('terms_accepted_at'):
            print(f"           Terms accepted {b['terms_accepted_at']} "
                  f"from {b.get('terms_accepted_ip') or 'unknown IP'}")
    for table in ('job_checklist', 'booking_rating', 'booking_crew'):
        n = len(found.get(table, []))
        if n:
            print(f"  {n} {table.replace('_', ' ')} row(s)")
    for cl in found.get('job_checklist', []):
        for kind in ('before_photos', 'after_photos'):
            try:
                urls = json.loads(cl.get(kind) or '[]')
            except Exception:
                urls = []
            if urls:
                print(f"    {kind.replace('_', ' ')}: {len(urls)}")
                for u in urls:
                    print(f"      {u}")
        if cl.get('client_signature'):
            print("    a client signature is on file")


def restore(found, database_url):
    """Insert the rows that are missing, remapping ids that are now taken.

    Never updates or deletes anything. A row whose id is free keeps it, so
    references from elsewhere still line up; one whose id has since been reused
    by a different record gets a new id and its children are pointed at it."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    os.environ['DATABASE_URL'] = database_url
    from sqlalchemy import create_engine, MetaData, select
    engine = create_engine(database_url)
    md = MetaData()
    md.reflect(bind=engine)

    def cols(table):
        return {c.name for c in md.tables[table].columns}

    def coerce(table, row):
        """Make the values fit the columns they are going into.

        backup.py tags dates so they survive the round trip, and _revive_row
        turns them back. This is the belt to that braces: a dump written by an
        older build, or hand-edited, can carry a plain ISO string where a
        timestamp column is, and the driver refuses it outright. This runs once,
        on real data, against a deadline — it should bend rather than stop."""
        import datetime as _dt
        out = {}
        for c in md.tables[table].columns:
            if c.name not in row:
                continue
            v = row[c.name]
            kind = c.type.__class__.__name__.lower()
            if isinstance(v, str) and 'date' in kind:
                for parse in (_dt.datetime.fromisoformat, _dt.date.fromisoformat):
                    try:
                        v = parse(v)
                        break
                    except ValueError:
                        continue
            out[c.name] = v
        return out

    def free_id(conn, table, want):
        t = md.tables[table]
        if want is not None:
            hit = conn.execute(select(t.c.id).where(t.c.id == want)).first()
            if not hit:
                return want
        nxt = conn.execute(select(t.c.id).order_by(t.c.id.desc())).first()
        return (nxt[0] if nxt else 0) + 1

    written = {}
    with engine.begin() as conn:
        c = coerce('client', found['client'])
        new_client_id = free_id(conn, 'client', c.get('id'))
        c['id'] = new_client_id
        conn.execute(md.tables['client'].insert().values(**c))
        written['client'] = 1
        print(f"  restored client as id {new_client_id}")

        booking_map = {}
        for b in found['booking']:
            row = coerce('booking', b)
            old = row.get('id')
            row['id'] = free_id(conn, 'booking', old)
            row['client_id'] = new_client_id
            conn.execute(md.tables['booking'].insert().values(**row))
            booking_map[old] = row['id']
            print(f"    booking #{old} restored as #{row['id']}")
        written['booking'] = len(booking_map)

        for table, fk in CHILDREN[1:]:
            if table not in md.tables:
                continue
            n = 0
            for r in found.get(table, []):
                row = coerce(table, r)
                if row.get(fk) not in booking_map:
                    continue
                row[fk] = booking_map[row[fk]]
                row['id'] = free_id(conn, table, row.get('id'))
                conn.execute(md.tables[table].insert().values(**row))
                n += 1
            if n:
                written[table] = n
                print(f"    {n} {table.replace('_', ' ')} row(s) restored")
    return written


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('backup', help='the .json.gz.enc file downloaded from the backup run')
    ap.add_argument('--find', required=True, help='customer name or email')
    ap.add_argument('--restore', action='store_true',
                    help='actually write the rows back (default: show only)')
    ap.add_argument('--database-url', default=os.environ.get('DATABASE_URL', ''),
                    help='where to write; defaults to $DATABASE_URL')
    ap.add_argument('--passphrase-file',
                    help='read the passphrase from this file instead of asking. '
                         'The whole file is tried, then each line — so a note '
                         'with the passphrase somewhere inside it works.')
    args = ap.parse_args()

    if not os.path.exists(args.backup):
        raise SystemExit(f'No such file: {args.backup}')

    plain = None
    if args.passphrase_file and os.path.exists(args.passphrase_file):
        # A note file rather than a bare secret: the passphrase is one line in
        # amongst instructions. Try the obvious readings rather than making
        # somebody find the right line and retype it under time pressure.
        raw = open(args.passphrase_file, encoding='utf-8', errors='replace').read()
        for cand in [raw.strip()] + [l.strip() for l in raw.splitlines() if l.strip()]:
            try:
                plain = decrypt(args.backup, cand)
                print(f'Passphrase read from {os.path.basename(args.passphrase_file)}.')
                break
            except SystemExit:
                continue
        if plain is None:
            print(f'Nothing in {os.path.basename(args.passphrase_file)} opened the '
                  f'backup — asking instead.')
    if plain is None:
        plain = decrypt(args.backup,
                        getpass.getpass('BACKUP_PASSPHRASE (not shown as you type): '))
    tmpdir = os.path.dirname(plain)
    try:
        found, _all = collect(plain, args.find)
        if not found:
            raise SystemExit(f'\nNo customer matching “{args.find}” in this backup. '
                             'Try a surname on its own, or an email address.')
        describe(found)
        if found['extra_matches']:
            print(f"\n  ⚠️  {len(found['extra_matches'])} other customer(s) also match "
                  f"“{args.find}”. Only the first was used — narrow the search if "
                  f"that is the wrong one.")
        if not args.restore:
            print('\n  Nothing was changed. Add --restore to write these rows back.')
            return
        if not args.database_url:
            raise SystemExit('\nSet DATABASE_URL (the Postgres URL from Railway) '
                             'or pass --database-url.')
        print('\n  Writing…')
        restore(found, args.database_url)
        print('\n  ✅ Done. Open the booking and use "Chargeback evidence" on it.')
    finally:
        # The decrypted copy holds every customer in the business.
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    main()
