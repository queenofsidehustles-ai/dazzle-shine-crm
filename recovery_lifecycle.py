"""Fail-closed lifecycle reconciliation for restored Akye databases.

Recovery may restore retained data for a tenant that is already closed or was
previously purged.  Detect that condition before external traffic is considered
ready; irreversible deletion remains an explicit lifecycle operator action.
"""


def restored_tenants_requiring_containment(engine, *, now=None):
    """Return restored closed tenants that must withhold traffic readiness."""
    from tenant_data_lifecycle import restored_closed_tenants_requiring_repurge

    return restored_closed_tenants_requiring_repurge(engine, now=now)


def assert_restore_ready(engine, *, now=None):
    """Fail closed when lifecycle reconciliation finds resurrected tenant data."""
    tenants = restored_tenants_requiring_containment(engine, now=now)
    if tenants:
        slugs = ', '.join(sorted(t['slug'] for t in tenants))
        raise RuntimeError(
            'restore requires lifecycle containment before traffic readiness: '
            + slugs
        )
    return True
