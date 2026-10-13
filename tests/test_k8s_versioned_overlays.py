"""Garantias sobre os overlays versionados (broetec-*) e os pins do role 04."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.inventory.models import InventoryManifest
from app.scaffold.dns import expected_records
from app.scaffold.overlays import OverlayManager
from app.scaffold.render import OverlayRenderer

MANIFEST = Path('provisioning/inventory/manifest.yml')
ROLE_DEFAULTS = Path('provisioning/roles/04_deploy_k8s/defaults/main.yml')
APPS_BASE = Path('k8s/core/applications/base')


def _versioned(repo_root: Path) -> list[str]:
    manifest = InventoryManifest.load(repo_root / MANIFEST)
    return [
        overlay_id
        for overlay_id, spec in sorted(manifest.overlays.items())
        if spec.k8s is not None and not spec.local
    ]


def test_versioned_overlays_match_templates(repo_root: Path) -> None:
    """Os overlays broetec-* são saída do gerador: nada de edição manual."""
    manifest = InventoryManifest.load(repo_root / MANIFEST)
    renderer = OverlayRenderer(repo_root)
    overlays = _versioned(repo_root)
    assert overlays
    for overlay_id in overlays:
        drift = renderer.drift(manifest.get_overlay(overlay_id))
        assert drift == [], (
            f'{overlay_id}: rode `uv run k8s-blueprint overlay render '
            f'{overlay_id}` ({drift[0]})'
        )


def _chart_version(repo_root: Path, application: str) -> str:
    data = yaml.safe_load((repo_root / APPS_BASE / application).read_text())
    return str(data['spec']['sources'][0]['targetRevision'])


def test_role_chart_pins_match_applications(repo_root: Path) -> None:
    """O bootstrap Helm e a Application que o adota usam a mesma versão."""
    defaults = yaml.safe_load((repo_root / ROLE_DEFAULTS).read_text())
    assert defaults['argocd_chart_version'] == _chart_version(
        repo_root, 'argocd.yaml'
    )
    assert 'v' + defaults['deploy_k8s_local_path_chart_version'] == (
        _chart_version(repo_root, 'local-path-provisioner.yaml')
    )


def test_applications_read_this_repository(repo_root: Path) -> None:
    """Fontes Git das Applications base apontam para o repo do catálogo."""
    catalog = OverlayManager(repo_root).catalog
    for path in sorted((repo_root / 'k8s').glob('*/applications/base/*.yaml')):
        data = yaml.safe_load(path.read_text())
        if data.get('kind') != 'Application':
            continue
        spec = data['spec']
        sources = spec.get('sources') or [spec['source']]
        git = [s for s in sources if 'chart' not in s and 'helm' not in s]
        assert git, path
        for source in git:
            assert source['repoURL'] == catalog.repo_url, path


@pytest.mark.parametrize(
    ('name', 'ip'),
    [
        ('*.core.local.broetec.com.br', '10.20.30.40'),
        ('*.storage.local.broetec.com.br', '10.20.30.50'),
        ('*.monitor.local.broetec.com.br', '10.20.30.60'),
    ],
)
def test_expected_dns_records(repo_root: Path, name: str, ip: str) -> None:
    manager = OverlayManager(repo_root)
    records = {
        record.name: record.ip
        for record in expected_records(
            manager.manifest(),
            manager.catalog,
            _versioned(repo_root),
        )
    }
    assert records[name] == ip
    assert len(records) == 3  # noqa: PLR2004 — um curinga por overlay
