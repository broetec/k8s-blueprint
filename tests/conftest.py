"""Fixtures compartilhadas: raiz do repo e uma cópia descartável dele."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope='session')
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def lab_repo(tmp_path: Path) -> Path:
    """Cópia mínima do repo (catálogo, templates e inventário versionado)."""

    def only_templates(directory: str, names: list[str]) -> set[str]:
        if Path(directory).name != 'overlays':
            return set()
        return {name for name in names if name != '_template'}

    shutil.copytree(REPO_ROOT / 'k8s', tmp_path / 'k8s', ignore=only_templates)
    inventory = tmp_path / 'provisioning/inventory'
    inventory.mkdir(parents=True)
    shutil.copy(
        REPO_ROOT / 'provisioning/inventory/manifest.yml',
        inventory / 'manifest.yml',
    )
    shutil.copytree(
        REPO_ROOT / 'provisioning/inventory/_shared', inventory / '_shared'
    )
    (tmp_path / 'env').mkdir()
    (tmp_path / 'lab/disks').mkdir(parents=True)
    return tmp_path
