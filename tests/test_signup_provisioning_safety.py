"""Regression tests for the tenant factory's failure boundaries.

These are deliberately narrower than tests/test_signup.py. They attack the
three launch-safety properties that are easiest to get wrong under real cohort
traffic:

* public signup is closed unless SIGNUPS_OPEN=1 is explicit;
* two simultaneous requests for the same slug cannot corrupt/delete the winner;
* a required starter-template failure leaves neither a registered tenant nor an
  orphan tenant schema.
"""
import os
import threading

import pytest
from sqlalchemy import create_engine, text


DB_NAME = 'dsm_signup_provisioning_safety_test'


def _postgres_admin_url():
    candidates = [
        os.environ.get('TEST_POSTGRES_URL'),
        f'postgresql://{os.environ.get("USER", "postgres")}@localhost/postgres',
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            engine = create_engine(candidate)
            with engine.connect() as conn:
                conn.execute(text('SELECT 1'))
            return candidate
        except Exception:
            continue
    return None


@pytest.fixture(scope='module')
def postgres_url():
    admin_url = _postgres_admin_url()
    if not admin_url:
        pytest.skip('tenant provisioning safety tests require PostgreSQL')

    admin = create_engine(admin_url, isolation_level='AUTOCOMMIT')
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {DB_NAME}'))
        conn.execute(text(f'CREATE DATABASE {DB_NAME}'))

    test_url = f'{admin_url.rsplit("/", 1)[0]}/{DB_NAME}'
    try:
        yield test_url
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)'))
        admin.dispose()


def _configure(monkeypatch, database_url, signups='1'):
    monkeypatch.setenv('DATABASE_URL', database_url)
    monkeypatch.setenv('SECRET_KEY', 'signup-safety-test-secret')
    monkeypatch.setenv('BASE_DOMAIN', 'akye.test')
    if signups is None:
        monkeypatch.delenv('SIGNUPS_OPEN', raising=False)
    else:
        monkeypatch.setenv('SIGNUPS_OPEN', signups)
    monkeypatch.delenv('ADMIN_USER', raising=False)
    monkeypatch.delenv('ADMIN_PASS', raising=False)


def _form(slug, email):
    return {
        'business': f'{slug.title()} Cleaning',
        'slug': slug,
        'name': 'Test Owner',
        'email': email,
        'password': 'a-strong-test-password',
    }


def test_signup_defaults_closed(monkeypatch):
    """BASE_DOMAIN by itself must never open public tenant creation."""
    monkeypatch.setenv('BASE_DOMAIN', 'akye.test')
    monkeypatch.delenv('SIGNUPS_OPEN', raising=False)
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setenv('SECRET_KEY', 'signup-safety-test-secret')

    from app import create_app
    app = create_app()
    response = app.test_client().get('/signup', headers={'Host': 'akye.test'})
    assert response.status_code == 404


def test_same_slug_concurrency_has_one_winner(monkeypatch, postgres_url):
    """Two requests that both observed a free slug still produce one tenant."""
    _configure(monkeypatch, postgres_url)

    import blueprints.signup as signup
    signup._tell_us = lambda *args, **kwargs: None

    # Make both requests complete the optimistic pre-check before either can
    # enter provisioning. This deterministically exercises the race that used
    # to let the losing request clean up the winning request's schema.
    original_validate = signup._validate
    barrier = threading.Barrier(2)

    def synchronized_validate(form, slug, password):
        result = original_validate(form, slug, password)
        if result is None and slug == 'raceco':
            barrier.wait(timeout=15)
        return result

    monkeypatch.setattr(signup, '_validate', synchronized_validate)

    from app import create_app
    app = create_app()
    responses = []
    failures = []

    def submit(email):
        try:
            client = app.test_client()
            response = client.post(
                '/signup', data=_form('raceco', email),
                headers={'Host': 'akye.test'})
            responses.append((response.status_code, response.data))
        except Exception as exc:
            failures.append(exc)

    threads = [
        threading.Thread(target=submit, args=('one@raceco.test',)),
        threading.Thread(target=submit, args=('two@raceco.test',)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=90)

    assert not failures
    assert all(not thread.is_alive() for thread in threads)
    assert sorted(status for status, _ in responses) == [200, 302]
    loser = next(body for status, body in responses if status == 200)
    assert b'just taken' in loser

    import control_plane
    import provisioning
    import tenancy
    engine = provisioning._engine()
    orgs = [org for org in control_plane.all_orgs(engine)
            if org['slug'] == 'raceco']
    assert len(orgs) == 1
    assert provisioning.schema_exists(engine, 'tenant_raceco')

    with app.app_context():
        with tenancy.use_tenant('raceco'):
            from models import User
            assert User.query.count() == 1


def test_required_seed_failure_leaves_no_tenant(monkeypatch, postgres_url):
    """A broken required template seed must fail closed and clean its schema."""
    _configure(monkeypatch, postgres_url)

    import blueprints.signup as signup
    signup._tell_us = lambda *args, **kwargs: None
    import app as app_module

    # Build the app before injecting the provisioning-only failure. create_app()
    # has its own legacy/bootstrap seeding path; patching before app creation
    # would test startup, not the tenant factory boundary we care about here.
    app = app_module.create_app()

    def fail_seed():
        raise RuntimeError('forced starter-template failure')

    monkeypatch.setattr(app_module, '_seed_checklists', fail_seed)

    response = app.test_client().post(
        '/signup', data=_form('seedfail', 'owner@seedfail.test'),
        headers={'Host': 'akye.test'})
    assert response.status_code == 200
    assert b'could not finish setting your account up' in response.data.lower()

    import control_plane
    import provisioning
    engine = provisioning._engine()
    assert control_plane.find(engine, 'seedfail') is None
    assert not provisioning.schema_exists(engine, 'tenant_seedfail')
