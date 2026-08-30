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
