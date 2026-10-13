"""Testes da criação/remoção de overlays locais e do render."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from app.inventory.models import InventoryManifest
from app.scaffold.overlays import (
    NewOverlay,
    OverlayError,
    OverlayManager,
    sslip_domain,
)
from app.scaffold.validate import RESULT_ERROR, validate

MANIFEST = Path('provisioning/inventory/manifest.yml')


def _new(manager: OverlayManager, **kwargs: object) -> NewOverlay:
    defaults: dict[str, object] = {
        'overlay_id': 'meu-lab',
        'ip': manager.suggest_ip(),
        'stacks': ('core',),
    }
    return NewOverlay(**(defaults | kwargs))


def test_suggest_ip_skips_used_and_dhcp(lab_repo: Path) -> None:
    manager = OverlayManager(lab_repo)
    assert manager.suggest_ip() == '10.20.30.70'
    manager.create(_new(manager))
    assert manager.suggest_ip() == '10.20.30.71'


def test_create_writes_only_local_files(lab_repo: Path) -> None:
    manager = OverlayManager(lab_repo)
    created = manager.create(_new(manager, vcpus=2, memory_mb=4096))

    assert created.spec.local
    assert created.spec.k8s.domain == sslip_domain('10.20.30.70')
    assert created.spec.k8s.tls_issuer == 'selfsigned'

    local = yaml.safe_load(
        (lab_repo / 'provisioning/inventory/manifest.local.yml').read_text()
    )
    assert list(local['overlays']) == ['meu-lab']
    versioned = yaml.safe_load((lab_repo / MANIFEST).read_text())
    assert 'meu-lab' not in versioned['overlays']

    inventory = lab_repo / 'provisioning/inventory/meu-lab'
    assert (inventory / 'hosts.ini').is_file()
    generated = yaml.safe_load(
        (inventory / 'group_vars/all/50_overlay.generated.yml').read_text()
    )
    assert generated['overlay_id'] == 'meu-lab'
    assert generated['k8s_stacks'] == ['core']
    assert generated['apps_domain'] == '10-20-30-70.sslip.io'
    sizing = yaml.safe_load(
        (inventory / 'group_vars/all/90_local.yml').read_text()
    )
    assert sizing == {
        'vm_vcpus': 2,
        'vm_memory_mb': 4096,
        'vm_disk_size_gb': 60,
    }

    assert all('/overlays/meu-lab/' in str(path) for path in created.files)
    gateway = lab_repo / (
        'k8s/core/cluster-config/cilium/overlays/meu-lab/gateway-public.yaml'
    )
    text = gateway.read_text()
    assert '10.20.30.70' in text
    assert '*.10-20-30-70.sslip.io' in text
    assert '[[' not in text


def test_reloaded_manifest_merges_local_overlays(lab_repo: Path) -> None:
    manager = OverlayManager(lab_repo)
    manager.create(_new(manager))
    manifest = InventoryManifest.load(lab_repo / MANIFEST)
    assert manifest.get_overlay('meu-lab').local
    assert not manifest.get_overlay('broetec-core').local


def test_disabled_component_is_not_rendered(lab_repo: Path) -> None:
    manager = OverlayManager(lab_repo)
    created = manager.create(
        _new(manager, disable=('core/external-secrets-operator',))
    )
    paths = [str(path) for path in created.files]
    assert not any('external-secrets-operator' in path for path in paths)
    kustomization = (
        lab_repo / 'k8s/core/applications/overlays/meu-lab/kustomization.yaml'
    ).read_text()
    assert '$patch: delete' in kustomization


@pytest.mark.parametrize(
    ('kwargs', 'message'),
    [
        ({'overlay_id': 'Meu_Lab'}, 'Invalid overlay id'),
        ({'overlay_id': 'broetec-x'}, 'reserved prefix'),
        ({'overlay_id': 'broetec-core'}, 'reserved prefix'),
        ({'ip': '10.20.30.40'}, 'already used'),
        ({'ip': '192.168.1.10'}, 'outside the lab network'),
        ({'ip': '10.20.30.150'}, 'DHCP range'),
        ({'vm_name': 'broetec-core'}, 'VM name'),
        ({'tls_issuer': 'nope'}, 'Invalid TLS issuer'),
        ({'stacks': ('nope',)}, 'Unknown stack'),
        ({'disable': ('core/argocd',)}, 'required'),
    ],
)
def test_invalid_requests_are_rejected(
    lab_repo: Path, kwargs: dict[str, object], message: str
) -> None:
    manager = OverlayManager(lab_repo)
    with pytest.raises(OverlayError, match=message):
        manager.create(_new(manager, **kwargs))
    assert not (lab_repo / 'provisioning/inventory/manifest.local.yml').exists()


def test_remove_deletes_everything_local(lab_repo: Path) -> None:
    manager = OverlayManager(lab_repo)
    manager.create(_new(manager))
    (lab_repo / 'env/meu-lab').mkdir()

    removed = manager.remove('meu-lab', purge_env=True)

    assert Path('env/meu-lab') in removed
    assert not list((lab_repo / 'k8s').glob('**/overlays/meu-lab'))
    assert not (lab_repo / 'provisioning/inventory/meu-lab').exists()
    assert not (lab_repo / 'provisioning/inventory/manifest.local.yml').exists()
    assert 'meu-lab' not in manager.manifest().overlays


def test_remove_refuses_versioned_and_running(lab_repo: Path) -> None:
    manager = OverlayManager(lab_repo)
    with pytest.raises(OverlayError, match='versioned'):
        manager.remove('broetec-core')
    manager.create(_new(manager))
    (lab_repo / 'lab/disks/meu-lab.qcow2').write_bytes(b'')
    with pytest.raises(OverlayError, match='VM disk still exists'):
        manager.remove('meu-lab')
    assert manager.remove('meu-lab', force=True)


@pytest.mark.skipif(
    not (shutil.which('kustomize') or shutil.which('kubectl')),
    reason='kustomize/kubectl not installed',
)
def test_generated_overlay_builds_with_kustomize(lab_repo: Path) -> None:
    manager = OverlayManager(lab_repo)
    manager.create(_new(manager))
    results = validate(lab_repo, 'meu-lab')
    assert results
    assert [r for r in results if r.status == RESULT_ERROR] == []

    apps = subprocess.run(
        ['kustomize', 'build', 'k8s/core/applications/overlays/meu-lab']
        if shutil.which('kustomize')
        else ['kubectl', 'kustomize', 'k8s/core/applications/overlays/meu-lab'],
        cwd=lab_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert 'PLACEHOLDER' not in apps
    assert 'k8s/core/argocd/overlays/meu-lab' in apps


@pytest.mark.skipif(
    not (shutil.which('kustomize') or shutil.which('kubectl')),
    reason='kustomize/kubectl not installed',
)
@pytest.mark.parametrize('with_harbor', [True, False])
def test_storage_overlay_renders_and_builds(
    lab_repo: Path, with_harbor: bool
) -> None:
    manager = OverlayManager(lab_repo)
    if 'storage' not in manager.catalog.stacks:
        pytest.skip('storage stack not in catalog')
    disable = () if with_harbor else ('storage/harbor',)
    created = manager.create(
        _new(manager, stacks=('core', 'storage'), disable=disable)
    )

    assert created.size.memory_mb >= 16384  # noqa: PLR2004
    paths = [str(path) for path in created.files]
    assert any('/storage/seaweedfs/' in path for path in paths)
    assert with_harbor == any('/storage/harbor/' in path for path in paths)
    assert with_harbor == any(
        'postgres/clusters/harbor' in path for path in paths
    )
    for path in created.files:
        text = (lab_repo / path).read_text()
        assert '[[' not in text, path
        assert '[%' not in text, path

    watch = (
        lab_repo
        / 'k8s/storage/postgres/operator/overlays/meu-lab/deployment.yaml'
    ).read_text()
    assert ('harbor-db' in watch) == with_harbor

    results = validate(lab_repo, 'meu-lab')
    assert [r for r in results if r.status == RESULT_ERROR] == []
    core_apps = (
        lab_repo / 'k8s/core/applications/overlays/meu-lab/kustomization.yaml'
    ).read_text()
    assert 'storage/applications/root' in core_apps
