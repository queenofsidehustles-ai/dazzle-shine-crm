"""TEN-07: sensitive contractor documents must remain tenant-scoped.

The encrypted-document feature already proves encryption, owner-only reads and
safe upload types in a single tenant. This test proves the same routes do not
cross a schema boundary when a token or numeric document id from another tenant
is replayed against the wrong host.
"""
import io
import os

import pytest
from sqlalchemy import create_engine, text


DB_NAME = 'dsm_tenant_secure_docs_test'
A = 'docsa'
B = 'docsb'


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
            engine.dispose()
            return candidate
        except Exception:
            continue
    return None


@pytest.fixture(scope='module')
def boundary():
    admin_url = _postgres_admin_url()
    if not admin_url:
        pytest.skip('TEN-07 secure-document isolation requires PostgreSQL')

    original_env = dict(os.environ)
    admin = create_engine(admin_url, isolation_level='AUTOCOMMIT')
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE {DB_NAME}'))

    test_url = f'{admin_url.rsplit("/", 1)[0]}/{DB_NAME}'
    os.environ['DATABASE_URL'] = test_url
    os.environ['SECRET_KEY'] = 'tenant-secure-docs-secret-at-least-32-characters'
    os.environ['BASE_DOMAIN'] = 'akye.test'
    os.environ['SIGNUPS_OPEN'] = '0'
    os.environ['FLASK_ENV'] = 'development'
    os.environ.pop('ADMIN_USER', None)
    os.environ.pop('ADMIN_PASS', None)

    import notifications
    notifications.send_sms = lambda *a, **k: (True, 'stub')
    notifications.send_email = lambda *a, **k: (True, 'stub')

    import provisioning
    import tenancy
    from app import create_app
    from extensions import db
    from models import Staff

    provisioning.provision(A, 'Docs A Cleaning', quiet=True)
    provisioning.provision(B, 'Docs B Cleaning', quiet=True)

    app = create_app()
    app.config.update(TESTING=True)

    with app.app_context():
        with tenancy.use_tenant(A):
            db.session.add(Staff(id=8101, name='A Cleaner', email='a@example.test',
                                 agreement_token='token-a', is_active=True))
            db.session.commit()
            db.session.remove()
        with tenancy.use_tenant(B):
            db.session.add(Staff(id=8201, name='B Cleaner', email='b@example.test',
                                 agreement_token='token-b', is_active=True))
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
        os.environ.update(original_env)


def _owner(app, slug):
    client = app.test_client()
    base = f'https://{slug}.akye.test'
    with client.session_transaction(base_url=base) as sess:
        sess['logged_in'] = True
        sess['role'] = 'owner'
        sess['user_id'] = 1
        sess['user_name'] = 'Document Boundary Tester'
        sess['tenant_slug'] = slug
    return client, base


def test_foreign_upload_token_is_not_valid_on_other_tenant_host(boundary):
    client = boundary.test_client()
    payload = b'\x89PNG\r\n\x1a\nFOREIGN-DOCUMENT-CANARY'

    wrong = client.post(
        '/contractors/documents/token-b/id',
        base_url='https://docsa.akye.test',
        data={'document': (io.BytesIO(payload), 'foreign.png', 'image/png')},
        content_type='multipart/form-data',
    )
    assert wrong.status_code == 404

    import tenancy
    from extensions import db
    from models import ContractorDocument
    with boundary.app_context():
        with tenancy.use_tenant(A):
            assert ContractorDocument.query.count() == 0
        with tenancy.use_tenant(B):
            assert ContractorDocument.query.count() == 0
        db.session.remove()


def test_document_id_from_tenant_b_cannot_be_read_on_tenant_a(boundary):
    public = boundary.test_client()
    payload = b'\x89PNG\r\n\x1a\nB-TENANT-SECRET-DOCUMENT'
    response = public.post(
        '/contractors/documents/token-b/id',
        base_url='https://docsb.akye.test',
        data={'document': (io.BytesIO(payload), 'b-id.png', 'image/png')},
        content_type='multipart/form-data',
    )
    assert response.status_code in (200, 301, 302)

    import tenancy
    from extensions import db
    from models import ContractorDocument
    with boundary.app_context():
        with tenancy.use_tenant(B):
            doc = ContractorDocument.query.one()
            foreign_id = doc.id
        db.session.remove()

    owner_a, base_a = _owner(boundary, A)
    replay = owner_a.get(f'/contractors/documents/{foreign_id}/view', base_url=base_a)
    assert replay.status_code == 404
    assert payload not in replay.data

    owner_b, base_b = _owner(boundary, B)
    own = owner_b.get(f'/contractors/documents/{foreign_id}/view', base_url=base_b)
    assert own.status_code == 200
    assert own.data == payload
    assert 'no-store' in (own.headers.get('Cache-Control') or '')
