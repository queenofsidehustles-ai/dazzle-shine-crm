import tenant_data_lifecycle as lifecycle
import tenant_lifecycle_cli as cli


def _registered_org(slug):
    return {"slug": slug, "name": slug}


def test_purge_cli_preflight_contract_exists():
    """The operator purge command must never point at a missing lifecycle API."""
    assert callable(lifecycle.purge_eligible)
    assert callable(lifecycle.purge_tenant)


def test_purge_cli_checks_eligibility_before_destructive_call(monkeypatch, capsys):
    calls = []
    engine = object()

    monkeypatch.setattr(cli.provisioning, '_engine', lambda: engine)
    monkeypatch.setattr(cli.control_plane, 'find', lambda actual_engine, slug: _registered_org(slug))
    monkeypatch.setattr(lifecycle, 'purge_eligible', lambda actual_engine, slug: False)
    monkeypatch.setattr(
        lifecycle,
        'purge_tenant',
        lambda actual_engine, slug: calls.append((actual_engine, slug)) or (_ for _ in ()).throw(
            AssertionError('destructive purge must not run for ineligible tenant')
        ),
    )

    rc = cli.main(['purge', 'retained-tenant'])

    assert rc == 1
    assert calls == []
    output = capsys.readouterr().out.lower()
    assert 'purge refused' in output
    assert 'retention requirement' in output


def test_purge_cli_requires_explicit_confirmation(monkeypatch):
    calls = []
    engine = object()

    monkeypatch.setattr(cli.provisioning, '_engine', lambda: engine)
    monkeypatch.setattr(cli.control_plane, 'find', lambda actual_engine, slug: _registered_org(slug))
    monkeypatch.setattr(lifecycle, 'purge_eligible', lambda actual_engine, slug: True)
    monkeypatch.setattr(lifecycle, 'purge_tenant', lambda actual_engine, slug: calls.append((actual_engine, slug)))
    monkeypatch.setattr('builtins.input', lambda prompt='': 'NO')

    rc = cli.main(['purge', 'eligible-tenant'])

    assert rc == 1
    assert calls == []
