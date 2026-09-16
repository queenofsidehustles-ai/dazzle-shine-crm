"""Shared pytest fixtures for launch-readiness tests.

Role-matrix tests exercise authorization policy independently from the
credential/session-revalidation boundary.  Session invalidation has its own
mandatory test module and must continue to exercise the real implementation.
"""

import pytest


@pytest.fixture(autouse=True)
def isolate_rbac_matrix_from_account_revalidation(monkeypatch, request):
    """Keep RBAC matrix tests focused on permissions, not credential freshness.

    The role-matrix test apps intentionally have no tenant User database. Since
    authenticated production requests now revalidate tenant-local account state
    on every request, those synthetic apps would otherwise be redirected to
    login before RBAC is reached.  Patch only the two RBAC-focused modules;
    session-invalidation tests remain unpatched and therefore continue to prove
    immediate revocation after account/role/password changes.
    """
    if request.module.__name__ in {
        "test_role_fail_closed",
        "test_operational_role_matrix",
    }:
        import auth
        monkeypatch.setattr(auth, "session_matches_current_user", lambda: True)
