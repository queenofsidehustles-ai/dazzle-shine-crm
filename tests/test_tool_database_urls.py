"""Operator tools reach Postgres with the URL Railway hands out.

Railway's DATABASE_URL is a bare postgresql://. SQLAlchemy 2.1 reads that as
the psycopg 3 driver, which is not installed (requirements.txt has
psycopg2-binary), so a tool passing it straight to create_engine() stops with
"No module named 'psycopg'" before doing anything -- adopt_tenant.py and the
disaster-recovery tool did. They rewrite it the way the app does
(backup.normalise).
"""
import inspect
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import adopt_tenant
import recover_client


def test_adopt_tenant_uses_the_installed_driver():
    for url in ('postgresql://u:p@db.example:5432/app', 'postgres://u:p@db.example:5432/app'):
        engine = adopt_tenant._engine(url, 'TEST_URL')
        assert engine.dialect.driver == 'psycopg2', url


def test_recover_client_normalises_before_connecting():
    assert 'create_engine(backup.normalise(database_url))' in inspect.getsource(recover_client.restore)
