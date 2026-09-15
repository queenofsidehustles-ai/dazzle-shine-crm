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
    """Bring every existing company's schema up to the latest migration."""
    if not (os.environ.get('BASE_DOMAIN') or '').strip():
        return [], []
    engine = _engine()
    try:
        orgs = control_plane.all_orgs(engine)
    except Exception as e:
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
    try:
        with engine.connect() as conn:
            conn.execute(text(f'SET search_path TO "{schema}"'))
            return conn.execute(text('SELECT version_num FROM alembic_version LIMIT 1')).scalar()
    except Exception:
        return None


def provision(slug, name, owner_email=None, quiet=False):
    """Everything, in the order that leaves the least mess if it stops."""
    engine = _engine()
    if engine.dialect.name != 'postgresql':
        raise RuntimeError('Companies need PostgreSQL schemas. SQLite has no such thing, so this cannot be run against a local development database.')
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
    c.add_argument('slug'); c.add_argument('name'); c.add_argument('--email')
    sub.add_parser('list', help='every company on this deployment')
    lg = sub.add_parser('leads', help='everybody who asked for early access')
    lg.add_argument('--csv', action='store_true', help='output as CSV to paste into a sheet')
    tm = sub.add_parser('testmail', help="prove the product can actually send an email")
    tm.add_argument('to', help='where to send it — your own inbox')
    n = sub.add_parser('nudges', help='send the trial emails that are due today')
    n.add_argument('--dry-run', action='store_true', help='send nothing; print exactly what a real run would do')
    d = sub.add_parser('destroy', help='close a company and start its 30-day retention period')
    d.add_argument('slug'); d.add_argument('--yes', action='store_true')
    pg = sub.add_parser('purge', help='permanently purge a closed company after retention expires')
    pg.add_argument('slug'); pg.add_argument('--yes', action='store_true')
    args = p.parse_args()
    engine = _engine()

    if args.action == 'create':
        print(); provision(args.slug, args.name, args.email); print()
    elif args.action == 'list':
        control_plane.ensure_table(engine); rows = control_plane.all_orgs(engine)
        if not rows:
            print('\n  No companies yet — this is a single-business instance.\n'); return 0
        print(f'\n  {"address":<20} {"name":<28} {"status":<10} created'); print('  ' + '-' * 72)
        for r in rows:
            created = r['created_at'].strftime('%d %b %Y') if r['created_at'] else ''
            print(f'  {r["slug"]:<20} {r["name"][:27]:<28} {r["status"]:<10} {created}')
        print()
    elif args.action == 'leads':
        rows = control_plane.all_leads(engine)
        if not rows:
            print('\n  Nobody has asked for early access yet.\n'); return 0
        if args.csv:
            import csv, sys as _sys
            w = csv.writer(_sys.stdout); w.writerow(['when','name','company','email','phone','cleaners','note','source'])
            for r in rows:
                w.writerow([r['created_at'].strftime('%Y-%m-%d %H:%M') if r['created_at'] else '', r['name'] or '', r['company'] or '', r['email'] or '', r['phone'] or '', r['cleaners'] or '', (r['note'] or '').replace('\n',' '), r['source'] or ''])
            return 0
        print(f'\n  {len(rows)} early-access request{"s" if len(rows) != 1 else ""}, newest first\n')
        for r in rows:
            when = r['created_at'].strftime('%d %b, %H:%M') if r['created_at'] else ''
            print(f'  {r["name"] or "(no name)"}{" — " + r["company"] if r["company"] else ""}   [{when}]')
            print(f'     {r["email"] or ""}{"   " + r["phone"] if r["phone"] else ""}{"   " + r["cleaners"] + " cleaners" if r["cleaners"] else ""}')
            if r['note']: print(f'     “{r["note"]}”')
            print()
        print('  Add --csv to paste this into a spreadsheet.\n')
    elif args.action == 'testmail':
        import notifications, product
        st = product.mail_status(); print()
        if not st['applies']:
            print('  This deployment is not the hosted product (no BASE_DOMAIN),\n  so there is no product mail to test.\n'); return 0
        print(f'  Sending as:  {product.name()} <{st["from"]}>'); print(f'  Support:     {st["to"] or "— not set —"}'); print(f'  Key:         {"set" if st["key"] else "— MISSING —"}')
        if st['problem']:
            print(f'\n  ⚠️  {st["problem"]}\n'); return 1
        ok, detail = notifications.send_email(args.to, 'Test', f'{product.name()} test email', '<p>If you are reading this, the product can send email.</p>', from_name=product.name(), from_email=st['from'], reply_to=st['to'], api_key=product.resend_api_key())
        print()
        if ok:
            print(f'  ✅ Accepted by the provider: {detail}\n'); return 0
        print(f'  ❌ Not sent: {detail}\n'); return 1
    elif args.action == 'nudges':
        import trial_nudges
        try: control_plane.ensure_table(engine)
        except Exception:
            print('\n  This deployment has no control plane — it is a single business, not the hosted product. Nothing to nudge.\n'); return 0
        counts = trial_nudges.run(engine, dry_run=args.dry_run); plan = counts.get('plan') or []; head = 'Would send' if args.dry_run else 'Sent'
        print(f'\n  {counts["considered"]} compan{"y" if counts["considered"] == 1 else "ies"} checked.')
        if not plan: print('  Nothing due today.\n'); return 0
        print(f'\n  {head} {len(plan)}:\n')
        for slug, kind, email in plan: print(f'    {kind:<10} {slug:<20} {email}')
        if counts.get('skipped_no_email'): print(f'\n  {counts["skipped_no_email"]} skipped — no owner email on the account.')
        if counts.get('failed'): print(f'  {counts["failed"]} failed and will be retried tomorrow.')
        if args.dry_run: print('\n  Nothing was sent. Drop --dry-run to send it.')
        print()
    elif args.action == 'destroy':
        import tenant_data_lifecycle as lifecycle
        org = control_plane.find(engine, args.slug)
        if not org:
            print(f'  No company called {args.slug!r}.'); return 1
        print(f'\n  This closes {org["name"]} immediately and starts the 30-day retention period.')
        print('  Customer access is revoked now; tenant data remains recoverable during retention.\n')
        if not args.yes and input(f'  Type {args.slug} to confirm closure: ').strip() != args.slug:
            print('  Nothing was changed.\n'); return 1
        lifecycle.close_tenant(engine, args.slug)
        print(f'  {org["name"]} closed. Data is retained for 30 days.\n')
    elif args.action == 'purge':
        import tenant_data_lifecycle as lifecycle
        org = control_plane.find(engine, args.slug)
        if not org:
            print(f'  No company called {args.slug!r}.'); return 1
        if not lifecycle.purge_eligible(engine, args.slug):
            print('  Purge refused: this company has not completed the 30-day retention period.\n'); return 1
        print(f'\n  This permanently purges retained tenant data for {org["name"]}.')
        print('  This operation is irreversible.\n')
        if not args.yes and input(f'  Type {args.slug} to confirm permanent purge: ').strip() != args.slug:
            print('  Nothing was changed.\n'); return 1
        lifecycle.purge_tenant(engine, args.slug)
        print(f'  {org["name"]} purged after retention eligibility was verified.\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
