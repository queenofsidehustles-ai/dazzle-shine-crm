"""Public-link and host-routing tenant isolation falsification.

Authenticated sessions are now tenant-bound, but Akye also exposes legitimate
public token links (claim links and work-order checklists). Those tokens must
remain scoped to the host-selected tenant schema, and malformed multi-label
subdomains must never alias a real tenant.
"""
import os

import pytest
from sqlalchemy import create_engine, text

DB_NAME = 'dsm_tenant_public_token_test'


def _postgres_admin_url():
    for candidate in (
        os.environ.get('TEST_POSTGRES_URL'),
        f'postgresql://{os.environ.get("USER", "postgres")}@localhost/postgres',
    ):
        if not candidate:
            continue
        try:
            engine = create_engine(candidate)
            with engine.connect() as conn:
                conn.execute(text('SELECT 1'))
            engine.dispose()
            return candidate
        except Exception:
            continue
    return None


@pytest.fixture(scope='module')
def token_app():
    admin_url = _postgres_admin_url()
    if not admin_url:
        pytest.skip('public-token isolation requires PostgreSQL')

    original = dict(os.environ)
    admin = create_engine(admin_url, isolation_level='AUTOCOMMIT')
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE {DB_NAME}'))

    test_url = f'{admin_url.rsplit("/", 1)[0]}/{DB_NAME}'
    os.environ['DATABASE_URL'] = test_url
    os.environ['SECRET_KEY'] = 'tenant-public-token-secret'
    os.environ['BASE_DOMAIN'] = 'akye.test'
    os.environ['SIGNUPS_OPEN'] = '0'
    os.environ.pop('ADMIN_USER', None)
    os.environ.pop('ADMIN_PASS', None)

    import notifications
    notifications.send_sms = lambda *a, **k: (True, 'stub')
    notifications.send_email = lambda *a, **k: (True, 'stub')

    import provisioning
    for slug, name in (('alpha', 'Alpha Cleaning'), ('bravo', 'Bravo Cleaning')):
        provisioning.provision(slug, name, quiet=True)

    from app import create_app
    app = create_app()
    app.config.update(TESTING=True)

    import tenancy
    from extensions import db
    from models import Booking, JobChecklist, Staff

    with app.app_context():
        with tenancy.use_tenant('alpha'):
            booking = Booking(
                service_type='standard', name='ALPHA TOKEN JOB', price=111.0,
                claim_token='alpha-claim-token', open_for_claim=True,
                preferred_date='2026-09-20', preferred_time='09:00',
            )
            staff = Staff(name='ALPHA TOKEN STAFF', agreement_token='alpha-staff-token',
                          is_active=True)
            db.session.add_all([booking, staff])
            db.session.flush()
            db.session.add(JobChecklist(
                booking_id=booking.id, template_name='Alpha checklist', items='[]',
                token='alpha-checklist-token'))
            db.session.commit()
            db.session.remove()

        with tenancy.use_tenant('bravo'):
            booking = Booking(
                service_type='standard', name='BRAVO TOKEN JOB', price=222.0,
                claim_token='bravo-claim-token', open_for_claim=True,
                preferred_date='2026-09-21', preferred_time='10:00',
            )
            staff = Staff(name='BRAVO TOKEN STAFF', agreement_token='bravo-staff-token',
                          is_active=True)
            db.session.add_all([booking, staff])
            db.session.flush()
            db.session.add(JobChecklist(
                booking_id=booking.id, template_name='Bravo checklist', items='[]',
                token='bravo-checklist-token'))
            db.session.commit()
            db.session.remove()

    try:
        yield app
    finally:
        try:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        except Exception:
            pass
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)'))
        admin.dispose()
        os.environ.clear()
        os.environ.update(original)


def test_claim_tokens_cannot_be_replayed_on_other_tenant_host(token_app):
    app = token_app
    client = app.test_client()

    # A valid token pair must resolve on the owning tenant host.  The public
    # claim page intentionally does not expose the booking/customer name, so
    # status is the stable oracle here rather than incidental template text.
    own = client.get(
        '/claim/alpha-claim-token/alpha-staff-token',
        base_url='https://alpha.akye.test')
    assert own.status_code == 200

    # The exact same capability replayed against another tenant must disappear.
    replay = client.get(
        '/claim/alpha-claim-token/alpha-staff-token',
        base_url='https://bravo.akye.test')
    assert replay.status_code == 404

    # Mixing a booking token from one tenant with a staff token from another
    # must also fail rather than composing a cross-tenant capability.
    mixed = client.get(
        '/claim/alpha-claim-token/bravo-staff-token',
        base_url='https://alpha.akye.test')
    assert mixed.status_code == 404


def test_workorder_checklist_token_is_host_scoped(token_app):
    app = token_app
    client = app.test_client()

    own = client.get(
        '/workorders/checklist/alpha-checklist-token',
        base_url='https://alpha.akye.test')
    assert own.status_code == 200

    replay = client.get(
        '/workorders/checklist/alpha-checklist-token',
        base_url='https://bravo.akye.test')
    assert replay.status_code == 404

    reverse = client.get(
        '/workorders/checklist/bravo-checklist-token',
        base_url='https://alpha.akye.test')
    assert reverse.status_code == 404


def test_multi_label_subdomain_does_not_alias_a_real_tenant(token_app):
    import tenancy

    assert tenancy.slug_from_host('alpha.akye.test', 'akye.test') == 'alpha'
    # Only exactly one tenant label is valid. A crafted deeper hostname such as
    # alpha.attacker.akye.test must not silently resolve to Alpha.
    assert tenancy.slug_from_host('alpha.attacker.akye.test', 'akye.test') is None
    assert tenancy.slug_from_host('bravo.alpha.akye.test', 'akye.test') is None
