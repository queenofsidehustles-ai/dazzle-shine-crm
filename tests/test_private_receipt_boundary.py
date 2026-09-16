"""TEN-07: expense receipts stay behind the authenticated Akye media boundary."""
import io
import os
from pathlib import Path

import pytest
from flask import Flask


@pytest.fixture()
def receipt_app(monkeypatch):
    # Exercise the stable single-business shape here; hosted tenant binding is
    # separately falsified by the PostgreSQL tenant and private-media suites.
    monkeypatch.delenv('BASE_DOMAIN', raising=False)
    monkeypatch.setenv('SECRET_KEY', 'private-receipt-test-secret-123456789')

    from extensions import db
    from blueprints.money import money_bp

    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY='private-receipt-test-secret-123456789',
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    app.register_blueprint(money_bp)

    with app.app_context():
        db.create_all()

    try:
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()


def _owner(client):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['role'] = 'owner'
        # This fixture deliberately exercises the stable single-business
        # deployment shape. Its owner is the deployment credential and has no
        # tenant-local User row; using a fabricated user_id would now be
        # correctly rejected by per-request session revalidation.
        sess['user_id'] = None
        sess['user_name'] = 'Receipt Boundary Tester'


def _valid_category():
    from blueprints.money import VALID_CATEGORIES
    assert VALID_CATEGORIES
    return sorted(VALID_CATEGORIES)[0]


def test_receipt_upload_is_server_side_and_scoped_to_expense(receipt_app, monkeypatch):
    import private_media
    from extensions import db
    from models import Expense

    calls = []

    def fake_upload(file_storage, *, tenant_slug, kind, scope_id):
        calls.append((file_storage.filename, tenant_slug, kind, scope_id))
        return 'akye-media:v1:server-issued-test-ref'

    monkeypatch.setattr(private_media, 'upload_image', fake_upload)

    client = receipt_app.test_client()
    _owner(client)
    response = client.post(
        '/money/expenses/add',
        data={
            'category': _valid_category(),
            'date': '2026-09-14',
            'amount': '19.25',
            'method': 'card',
            'receipt_file': (io.BytesIO(b'not-real-image-content'), 'receipt.jpg'),
        },
        content_type='multipart/form-data',
        follow_redirects=False,
    )
    assert response.status_code in (301, 302, 303, 307, 308)

    with receipt_app.app_context():
        expense = Expense.query.one()
        assert expense.receipt_url == 'akye-media:v1:server-issued-test-ref'
        expense_id = expense.id
        db.session.remove()

    assert calls == [('receipt.jpg', 'single-business', 'expense-receipt', expense_id)]


def test_client_supplied_receipt_url_is_rejected(receipt_app):
    client = receipt_app.test_client()
    _owner(client)
    response = client.post(
        '/money/expenses/add',
        data={
            'category': _valid_category(),
            'date': '2026-09-14',
            'amount': '19.25',
            'receipt_url': 'https://res.cloudinary.com/example/image/upload/public-receipt.jpg',
        },
    )
    assert response.status_code == 400


def test_private_receipt_route_uses_authoritative_db_ref_and_no_store(receipt_app, monkeypatch):
    import private_media
    from extensions import db
    from models import Expense

    ref = 'akye-media:v1:server-issued-test-ref'
    with receipt_app.app_context():
        expense = Expense(date='2026-09-14', category=_valid_category(), amount=7.50,
                          receipt_url=ref)
        db.session.add(expense)
        db.session.commit()
        expense_id = expense.id

    monkeypatch.setattr(private_media, 'is_private_ref', lambda value: value == ref)
    calls = []

    def fake_fetch(value, *, tenant_slug, kind, scope_id):
        calls.append((value, tenant_slug, kind, scope_id))
        return b'private-receipt-bytes', 'image/jpeg'

    monkeypatch.setattr(private_media, 'fetch_image', fake_fetch)

    client = receipt_app.test_client()
    _owner(client)
    response = client.get(f'/money/expenses/{expense_id}/receipt')
    assert response.status_code == 200
    assert response.data == b'private-receipt-bytes'
    assert response.headers['Cache-Control'] == 'private, no-store, max-age=0'
    assert response.headers['Pragma'] == 'no-cache'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert calls == [(ref, 'single-business', 'expense-receipt', expense_id)]


def test_legacy_public_provider_url_is_not_served(receipt_app, monkeypatch):
    import private_media
    from extensions import db
    from models import Expense

    with receipt_app.app_context():
        expense = Expense(
            date='2026-09-14', category=_valid_category(), amount=8.00,
            receipt_url='https://res.cloudinary.com/example/image/upload/public-receipt.jpg',
        )
        db.session.add(expense)
        db.session.commit()
        expense_id = expense.id

    monkeypatch.setattr(private_media, 'is_private_ref', lambda value: False)
    monkeypatch.setattr(private_media, 'fetch_image',
                        lambda *a, **k: pytest.fail('legacy public URL must not be fetched'))

    client = receipt_app.test_client()
    _owner(client)
    assert client.get(f'/money/expenses/{expense_id}/receipt').status_code == 404


def test_expense_template_has_no_browser_direct_cloudinary_upload():
    source = Path('templates/admin/expenses.html').read_text(encoding='utf-8')
    assert 'api.cloudinary.com' not in source
    assert 'CLOUDINARY_UPLOAD_PRESET' not in source
    assert 'upload_preset' not in source
    assert 'name="receipt_url"' not in source
    assert 'name="receipt_file"' in source
    assert "url_for('money.expense_receipt'" in source
