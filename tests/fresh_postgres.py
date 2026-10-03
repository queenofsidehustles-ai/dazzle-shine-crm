"""A fresh, empty PostgreSQL database for one test file.

Hosted Akye (BASE_DOMAIN set) keeps its company list in PostgreSQL schemas,
which SQLite cannot hold -- a suite that points a multi-company app at a
SQLite file tests the "control plane not migrated" error page and nothing
else. Suites that exercise company or product-site hosts use this instead.

Uses TEST_POSTGRES_URL (as CI sets it) or a local default. With no server at
all it says so and exits 0, the same convention as test_signup.py, so a
laptop without Postgres is told what it skipped rather than failing.
"""
import os
import sys


def url(name):
    base = (os.environ.get('TEST_POSTGRES_URL')
            or 'postgresql://app_user:localtest@127.0.0.1:5432/postgres')
    base = base.replace('postgresql+psycopg2://', 'postgresql://')
    try:
        from sqlalchemy import create_engine, text
        admin = create_engine(base, isolation_level='AUTOCOMMIT')
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS {name} WITH (FORCE)'))
            c.execute(text(f'CREATE DATABASE {name}'))
        admin.dispose()
    except Exception as e:
        print('\n' + '=' * 70)
        print(f'  ⚠️  SKIPPED: this suite needs PostgreSQL and found none ({type(e).__name__}).')
        print('     Set TEST_POSTGRES_URL to a server this user can create databases on.')
        print('=' * 70 + '\n')
        sys.exit(0)
    return f'{base.rsplit("/", 1)[0]}/{name}'


def owner_client(app, slug, base_domain):
    """A test client signed in as the owner of company `slug`, bound the way a
    real login binds a session: to that company, and to the owner's current
    password. Creates the owner on first use."""
    import tenancy
    from auth import _auth_fingerprint
    from extensions import db
    from models import User
    username = f'owner@{slug}.test'
    with app.app_context(), tenancy.use_tenant(slug):
        owner = User.query.filter_by(username=username).first()
        if owner is None:
            owner = User(name='Owner', username=username, role='owner', active=True)
            owner.set_password('a-perfectly-fine-password')
            db.session.add(owner)
            db.session.commit()
        uid, fp = owner.id, _auth_fingerprint(owner.password_hash)
        db.session.remove()
    client = app.test_client()
    with client.session_transaction(base_url=f'http://{slug}.{base_domain}') as sess:
        sess.update(logged_in=True, role='owner', user_id=uid, user_name='Owner',
                    auth_fingerprint=fp, tenant_slug=slug)
    return client


def set_company_plan(slug, plan, status='active'):
    """On hosted Akye a company's plan is on its control-plane row
    (billing.install), not in its own settings."""
    import control_plane
    import entitlements
    import provisioning
    from sqlalchemy import update
    with provisioning._engine().begin() as conn:
        conn.execute(update(control_plane.organizations)
                     .where(control_plane.organizations.c.slug == slug)
                     .values(plan=plan, subscription_status=status))
    entitlements._clear_cache()
