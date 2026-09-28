"""TEN-04: PostgreSQL tenant search_path must fail closed.

If a pooled connection cannot be repointed to the current tenant, checkout must
abort. Continuing would risk serving the previous tenant's schema.
"""
import pytest

import tenancy


class RecordingCursor:
    def __init__(self, error=None):
        self.error = error
        self.executed = []
        self.closed = False

    def execute(self, sql):
        self.executed.append(sql)
        if self.error:
            raise self.error

    def close(self):
        self.closed = True


class FakePsycopgConnection:
    __module__ = 'psycopg2.extensions'

    def __init__(self, cursor=None, cursor_error=None):
        self._cursor = cursor
        self._cursor_error = cursor_error

    def cursor(self):
        if self._cursor_error:
            raise self._cursor_error
        return self._cursor


class FakeSqliteConnection:
    __module__ = 'sqlite3'

    def cursor(self):
        raise AssertionError('non-PostgreSQL checkout must not attempt SET search_path')


def test_postgres_checkout_applies_current_tenant_search_path():
    cursor = RecordingCursor()
    conn = FakePsycopgConnection(cursor=cursor)

    with tenancy.use_tenant('alpha'):
        tenancy._set_search_path_on_checkout(conn)

    assert cursor.executed == ['SET search_path TO "tenant_alpha", public']
    assert cursor.closed is True


def test_postgres_checkout_execute_failure_propagates():
    cursor = RecordingCursor(error=RuntimeError('SET search_path denied'))
    conn = FakePsycopgConnection(cursor=cursor)

    with tenancy.use_tenant('alpha'):
        with pytest.raises(RuntimeError, match='SET search_path denied'):
            tenancy._set_search_path_on_checkout(conn)

    assert cursor.closed is True


def test_postgres_checkout_cursor_failure_propagates():
    conn = FakePsycopgConnection(cursor_error=RuntimeError('cursor unavailable'))

    with tenancy.use_tenant('bravo'):
        with pytest.raises(RuntimeError, match='cursor unavailable'):
            tenancy._set_search_path_on_checkout(conn)


def test_non_postgres_checkout_is_ignored():
    tenancy._set_search_path_on_checkout(FakeSqliteConnection())
