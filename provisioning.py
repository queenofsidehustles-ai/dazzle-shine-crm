"""Give a new company its own private copy of the database.

    python3 provisioning.py create acme "Acme Cleaning" --email owner@acme.com

Creates the schema, builds all thirty-seven tables inside it, runs every
migration against it, seeds the starter content a new business needs, and
records the company in the control plane.

## Why the schema is built by migrations and not create_all()

create_all() builds tables from today's models, which is the right shape but
leaves the schema with no record of which migration it corresponds to. The next
migration would then either be skipped -- leaving that company behind forever --
or run against a schema that already has its changes. Building from migrations
means a company created today and a company created last year end up in the same
place by the same route, and both can be moved forward by the same command.

## The order matters

The schema is created first and the company is recorded last. A crash in the
middle leaves an orphan schema, which is untidy and harmless. Recording first
would leave a company that exists, resolves, and has no tables -- which is a
customer looking at a stack trace on their first morning.
"""
import argparse
import os
import sys

from sqlalchemy import text

import control_plane
import tenancy


def _engine():
    from sqlalchemy import create_engine
    import backup
    return create_engine(backup.normalise(os.environ.get('DATABASE_URL', '')))


def schema_exists(engine, schema):
    with engine.connect() as conn:
        return bool(conn.execute(text(
            'SELECT 1 FROM information_schema.schemata WHERE schema_name = :s'
        ), {'s': schema}).first())


def create_schema(engine, schema):
    # The name comes from valid_slug() and nowhere else, so it cannot carry
    # anything but lower-case letters, digits and underscores. Quoted anyway.
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))


def drop_schema(engine, schema, cascade=True):
    """Only ever for a provisioning that failed part-way, or a test."""
    if schema == tenancy.PUBLIC or not schema.startswith(tenancy.SCHEMA_PREFIX):
        raise ValueError(f'refusing to drop {schema!r}')
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" '
                          f'{"CASCADE" if cascade else "RESTRICT"}'))


def migrate_schema(engine, schema):
    """Run every migration inside one company's schema."""
    from alembic import command
    from alembic.config import Config
    cfg = Config(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'alembic.ini'))
    cfg.set_main_option('script_location',
                        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     'migrations'))
    # Alembic reads the connection from env.py; point it at this schema, and
    # give it its own version table inside the schema so each company records
    # its own position rather than sharing one.
    cfg.attributes['tenant_schema'] = schema
    with tenancy.use_tenant(schema):
        command.upgrade(cfg, 'head')


def seed(app, schema):
    """The starter content a brand-new business needs to be usable."""
    with app.app_context():
        with tenancy.use_tenant(schema):
            import app as app_module
            for fn in ('_seed_checklists', '_seed_scripts', '_seed_sales_scripts',
                       '_seed_sops', '_seed_email_templates', '_seed_pricing_defaults',
                       '_seed_message_templates'):
                try:
                    getattr(app_module, fn)()
                except Exception as e:
                    print(f'   ⚠️  {fn}: {type(e).__name__}: {e}')


def migrate_all(quiet=False):
    """Bring every existing company's schema up to the latest migration.

    Companies are provisioned once and then never touched again by the boot
    sequence, which migrates the default schema only. So the first release
    carrying a new migration would leave every existing customer on the old
    schema — the table simply absent — and the first page that reads it errors
    for them and nobody else. It would look like one customer's data being
    corrupt rather than a deploy that only half happened.

    Runs one schema at a time and keeps going if one fails. A single company
    with a wedged schema is a problem for that company; stopping would make it
    everybody's.

    Returns (moved, failed) for the log.
    """
    if not (os.environ.get('BASE_DOMAIN') or '').strip():
        return [], []                       # single business: nothing to do

    engine = _engine()
    try:
        orgs = control_plane.all_orgs(engine)
    except Exception as e:
        # On the very first boot the control plane has not been created yet,
        # and on SQLite it does not exist at all. Neither is worth shouting
        # about; anything else is.
        if 'no such table' not in str(e) and 'does not exist' not in str(e):
            print(f'  ⚠️  could not read the company list: {e}')
        return [], []

    moved, failed = [], []
    for org in orgs:
        slug = org.get('slug')
        schema = tenancy.schema_for(slug) if slug else None
        if not schema or not schema_exists(engine, schema):
            continue
        before = _schema_version(engine, schema)
        try:
            migrate_schema(engine, schema)
        except Exception as e:
            failed.append((slug, str(e)[:200]))
            print(f'  ❌ {slug}: {e}')
            continue
        after = _schema_version(engine, schema)
        if before != after:
            moved.append((slug, before, after))
            if not quiet:
                print(f'  ✅ {slug}: {before} → {after}')

    if not quiet and not moved and not failed and orgs:
        print(f'  ✅ {len(orgs)} companies already up to date')
    return moved, failed


def _schema_version(engine, schema):
    """Which migration one company's schema is on, or None if it has no record."""
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            conn.execute(text(f'SET search_path TO "{schema}"'))
            return conn.execute(
                text('SELECT version_num FROM alembic_version LIMIT 1')).scalar()
    except Exception:
        return None


def provision(slug, name, owner_email=None, quiet=False):
    """Everything, in the order that leaves the least mess if it stops."""
    engine = _engine()
    if engine.dialect.name != 'postgresql':
        raise RuntimeError(
            'Companies need PostgreSQL schemas. SQLite has no such thing, so '
            'this cannot be run against a local development database.')

    if not tenancy.valid_slug(slug):
        raise ValueError(f'{slug!r} is not a usable address.')

    control_plane.ensure_table(engine)
    if control_plane.find(engine, slug):
        raise ValueError(f'{slug!r} already exists.')

    schema = tenancy.schema_for(slug)
    say = (lambda m: None) if quiet else print

    say(f'  creating schema {schema}')
    create_schema(engine, schema)

    say('  building tables from the migrations')
    migrate_schema(engine, schema)

    say('  recording the company')
    control_plane.create(engine, slug, name, owner_email)
    control_plane.mark_provisioned(engine, slug)

    say(f'  ✅ {name} is at {slug}.<your domain>')
    return control_plane.find(engine, slug)


def main():
    p = argparse.ArgumentParser(description='Set a company up with its own data.')
    sub = p.add_subparsers(dest='action', required=True)

    c = sub.add_parser('create', help='provision a new company')
    c.add_argument('slug')
    c.add_argument('name')
    c.add_argument('--email')

    sub.add_parser('list', help='every company on this deployment')

    lg = sub.add_parser('leads', help='everybody who asked for early access')
    lg.add_argument('--csv', action='store_true', help='output as CSV to paste into a sheet')

    tm = sub.add_parser('testmail',
                        help="prove the product can actually send an email")
    tm.add_argument('to', help='where to send it — your own inbox')

    n = sub.add_parser('nudges', help='send the trial emails that are due today')
    n.add_argument('--dry-run', action='store_true',
                   help='send nothing; print exactly what a real run would do')

    d = sub.add_parser('destroy', help='remove a company and ALL of its data')
    d.add_argument('slug')
    d.add_argument('--yes', action='store_true')

    args = p.parse_args()
    engine = _engine()

    if args.action == 'create':
        print()
        provision(args.slug, args.name, args.email)
        print()
    elif args.action == 'list':
        control_plane.ensure_table(engine)
        rows = control_plane.all_orgs(engine)
        if not rows:
            print('\n  No companies yet — this is a single-business instance.\n')
            return 0
        print(f'\n  {"address":<20} {"name":<28} {"status":<10} created')
        print('  ' + '-' * 72)
        for r in rows:
            created = r['created_at'].strftime('%d %b %Y') if r['created_at'] else ''
            print(f'  {r["slug"]:<20} {r["name"][:27]:<28} {r["status"]:<10} {created}')
        print()
    elif args.action == 'leads':
        rows = control_plane.all_leads(engine)
        if not rows:
            print('\n  Nobody has asked for early access yet.\n')
            return 0
        if args.csv:
            import csv, sys as _sys
            w = csv.writer(_sys.stdout)
            w.writerow(['when', 'name', 'company', 'email', 'phone',
                        'cleaners', 'note', 'source'])
            for r in rows:
                w.writerow([
                    r['created_at'].strftime('%Y-%m-%d %H:%M') if r['created_at'] else '',
                    r['name'] or '', r['company'] or '', r['email'] or '',
                    r['phone'] or '', r['cleaners'] or '',
                    (r['note'] or '').replace('\n', ' '), r['source'] or ''])
            return 0
        print(f'\n  {len(rows)} early-access request'
              f'{"s" if len(rows) != 1 else ""}, newest first\n')
        for r in rows:
            when = r['created_at'].strftime('%d %b, %H:%M') if r['created_at'] else ''
            print(f'  {r["name"] or "(no name)"}'
                  f'{" — " + r["company"] if r["company"] else ""}   [{when}]')
            print(f'     {r["email"] or ""}'
                  f'{"   " + r["phone"] if r["phone"] else ""}'
                  f'{"   " + r["cleaners"] + " cleaners" if r["cleaners"] else ""}')
            if r['note']:
                print(f'     “{r["note"]}”')
            print()
        print('  Add --csv to paste this into a spreadsheet.\n')
    elif args.action == 'testmail':
        # The same lesson as the backups: a thing nobody has tested is not a
        # working thing, it is an assumption with a config value attached. The
        # two emails this proves out — trial reminders and crash alerts — both
        # fail invisibly, because nobody notices an email that never came.
        import notifications
        import product
        st = product.mail_status()
        print()
        if not st['applies']:
            print('  This deployment is not the hosted product (no BASE_DOMAIN),')
            print('  so there is no product mail to test.\n')
            return 0
        print(f'  Sending as:  {product.name()} <{st["from"]}>')
        print(f'  Support:     {st["to"] or "— not set —"}')
        print(f'  Key:         {"set" if st["key"] else "— MISSING —"}')
        if st['problem']:
            print(f'\n  ⚠️  {st["problem"]}\n')
            return 1
        ok, detail = notifications.send_email(
            args.to, 'Test', f'{product.name()} test email',
            f'''<p>If you are reading this, the product can send email.</p>
            <p>This is the same path as the trial reminders and the alert that
            tells you a customer's CRM has broken. Both of those fail
            invisibly, which is why this command exists.</p>
            <p style="color:#777;font-size:13px">Sent from {st["from"]},
            replies go to {st["to"]}.</p>''',
            from_name=product.name(), from_email=st['from'],
            reply_to=st['to'], api_key=product.resend_api_key())
        print()
        if ok:
            print(f'  ✅ Accepted by the provider: {detail}')
            print(f'\n  Now go and look in {args.to}. "Accepted" means it was')
            print('  taken, not that it arrived — it can still bounce or land')
            print('  in spam, and that is the half this cannot tell you.\n')
            return 0
        print(f'  ❌ Not sent: {detail}\n')
        return 1
    elif args.action == 'nudges':
        import trial_nudges
        try:
            control_plane.ensure_table(engine)
        except Exception:
            # No control plane means this is one cleaning company and not the
            # hosted product. There are no trials to nudge, and saying so is
            # better than a page of SQLAlchemy.
            print('\n  This deployment has no control plane — it is a single '
                  'business,\n  not the hosted product. Nothing to nudge.\n')
            return 0
        counts = trial_nudges.run(engine, dry_run=args.dry_run)
        plan = counts.get('plan') or []
        head = 'Would send' if args.dry_run else 'Sent'
        print(f'\n  {counts["considered"]} compan'
              f'{"y" if counts["considered"] == 1 else "ies"} checked.')
        if not plan:
            print('  Nothing due today.\n')
            return 0
        print(f'\n  {head} {len(plan)}:\n')
        for slug, kind, email in plan:
            print(f'    {kind:<10} {slug:<20} {email}')
        if counts.get('skipped_no_email'):
            print(f'\n  {counts["skipped_no_email"]} skipped — no owner email '
                  f'on the account.')
        if counts.get('failed'):
            print(f'  {counts["failed"]} failed and will be retried tomorrow.')
        if args.dry_run:
            print('\n  Nothing was sent. Drop --dry-run to send it.')
        print()
    elif args.action == 'destroy':
        org = control_plane.find(engine, args.slug)
        if not org:
            print(f'  No company called {args.slug!r}.')
            return 1
        print(f'\n  This DELETES every booking, cleaner, customer and payment '
              f'record belonging to {org["name"]}.')
        print('  It cannot be undone from here. Take a backup first.\n')
        if not args.yes:
            if input(f'  Type {args.slug} to confirm: ').strip() != args.slug:
                print('  Nothing was changed.\n')
                return 1
        drop_schema(engine, org['schema_name'])
        with engine.begin() as conn:
            conn.execute(text('DELETE FROM public.organizations WHERE slug = :s'),
                         {'s': args.slug})
        print(f'  {org["name"]} removed.\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
