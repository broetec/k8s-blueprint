"""Testes do catálogo de stacks/componentes."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.scaffold.catalog import Catalog


@pytest.fixture(scope='module')
def catalog(repo_root: Path) -> Catalog:
    return Catalog.load(repo_root)


def test_core_is_always_selected(catalog: Catalog) -> None:
    selection = catalog.select([])
    assert selection.stack_names == ['core']
    assert 'core/argocd' in selection.component_refs


def test_optional_component_can_be_disabled(catalog: Catalog) -> None:
    selection = catalog.select(['core'], ['core/external-secrets-operator'])
    assert 'core/external-secrets-operator' not in selection.component_refs


def test_required_component_cannot_be_disabled(catalog: Catalog) -> None:
    with pytest.raises(ValueError, match='required'):
        catalog.select(['core'], ['core/argocd'])


def test_unknown_stack_is_rejected(catalog: Catalog) -> None:
    with pytest.raises(KeyError, match='Unknown stack'):
        catalog.select(['nope'])


def test_storage_requires_external_secrets(catalog: Catalog) -> None:
    if 'storage' not in catalog.stacks:
        pytest.skip('storage stack not in catalog')
    with pytest.raises(ValueError, match='requires'):
        catalog.select(['core', 'storage'], ['core/external-secrets-operator'])
    selection = catalog.select(['storage'])
    assert selection.stack_names == ['core', 'storage']
    assert selection.vm_size().memory_mb >= catalog.stack('core').vm.memory_mb


def test_every_component_dir_has_a_template(
    catalog: Catalog, repo_root: Path
) -> None:
    for stack in catalog.stacks.values():
        dirs = [*stack.dirs, *(d for c in stack.components for d in c.dirs)]
        for directory in dirs:
            template = (
                repo_root
                / 'k8s'
                / stack.name
                / directory
                / 'overlays/_template'
            )
            assert template.is_dir(), template
