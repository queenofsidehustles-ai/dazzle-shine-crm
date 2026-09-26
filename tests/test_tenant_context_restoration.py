"""TEN-04: tenant context must restore across exceptions and failed switches."""
import pytest

import tenancy


def test_context_restores_after_body_exception():
    assert tenancy.current_schema() == tenancy.PUBLIC

    with pytest.raises(RuntimeError, match='boom'):
        with tenancy.use_tenant('alpha'):
            assert tenancy.current_schema() == 'tenant_alpha'
            raise RuntimeError('boom')

    assert tenancy.current_schema() == tenancy.PUBLIC


def test_nested_tenant_context_restores_outer_then_public():
    assert tenancy.current_schema() == tenancy.PUBLIC

    with tenancy.use_tenant('alpha'):
        assert tenancy.current_schema() == 'tenant_alpha'

        with pytest.raises(ValueError, match='nested'):
            with tenancy.use_tenant('bravo'):
                assert tenancy.current_schema() == 'tenant_bravo'
                raise ValueError('nested')

        assert tenancy.current_schema() == 'tenant_alpha'

    assert tenancy.current_schema() == tenancy.PUBLIC


def test_failed_enter_does_not_contaminate_context(monkeypatch):
    """If search_path setup fails in __enter__, __exit__ will never run."""
    assert tenancy.current_schema() == tenancy.PUBLIC

    def fail_switch():
        raise RuntimeError('search_path switch failed')

    monkeypatch.setattr(tenancy, '_apply_to_open_connections', fail_switch)

    with pytest.raises(RuntimeError, match='search_path switch failed'):
        with tenancy.use_tenant('alpha'):
            pytest.fail('body must not execute when tenant setup fails')

    assert tenancy.current_schema() == tenancy.PUBLIC
