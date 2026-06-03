"""Testes do gerador de inventário."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.inventory.env_file import load_dotenv, overlay_env_overrides
from app.inventory.generator import InventoryGenerator
from app.inventory.models import InventoryManifest, VmSpec


@pytest.fixture
def repo_tree(tmp_path: Path) -> Path:
    manifest = {
        'defaults': {
            'kvm_host': 'localhost',
            'ansible_connection': 'local',
            'ansible_user': 'rocky',
        },
        'overlays': {
            'broetec-core': {
                'label': 'Core',
                'role': 'core',
                'vms': [{'name': 'broetec-core', 'ip': '10.20.30.40'}],
            },
            'broetec-storage': {
                'label': 'Storage',
                'role': 'storage',
                'vms': [{'name': 'broetec-storage', 'ip': '10.20.30.50'}],
            },
        },
    }
    inv = tmp_path / 'provisioning/inventory'
    inv.mkdir(parents=True)
    (inv / 'manifest.yml').write_text(
        yaml.dump(manifest),
        encoding='utf-8',
    )
    shared = inv / '_shared/group_vars'
    shared.mkdir(parents=True)
    (shared / 'all.yml').write_text('---\nbase_domain: test.local\n', encoding='utf-8')
    (shared / 'kvm_hosts.yml').write_text(
        '---\nansible_python_interpreter: "{{ ansible_playbook_python }}"\n',
        encoding='utf-8',
    )
    (tmp_path / 'env').mkdir()
    return tmp_path


def test_manifest_load(repo_tree: Path) -> None:
    manifest = InventoryManifest.load(repo_tree / 'provisioning/inventory/manifest.yml')
    assert manifest.overlay_ids() == ['broetec-core', 'broetec-storage']
    assert manifest.get_overlay('broetec-core').primary_vm.ip == '10.20.30.40'


def test_invalid_ip() -> None:
    with pytest.raises(ValueError, match='IP inválido'):
        VmSpec(name='x', ip='not-an-ip')


def test_generate_hosts_ini(repo_tree: Path) -> None:
    gen = InventoryGenerator(repo_tree)
    manifest = gen.load_manifest()
    overlay = manifest.get_overlay('broetec-core')
    text = gen.render_hosts_ini(overlay, manifest)
    assert (
        'broetec-core ansible_host=10.20.30.40 vm_ip=10.20.30.40 '
        'vm_mac=52:54:00:6d:81:73'
    ) in text
    assert '[kvm_hosts]' in text
    assert 'vm_role=core' in text
    assert 'ansible.netcommon.libssh' in text


def test_generate_writes_files(repo_tree: Path) -> None:
    gen = InventoryGenerator(repo_tree)
    paths = gen.generate(['broetec-core'])
    hosts = paths[0]
    assert hosts.name == 'hosts.ini'
    assert 'Gerado automaticamente' in hosts.read_text(encoding='utf-8')
    gv_all = hosts.parent / 'group_vars' / 'all'
    assert gv_all.is_dir()
    assert (gv_all / '00_shared.yml').is_symlink()
    assert not (gv_all / '10_dhcp_reservations.yml').exists()
    overlay_gen = gv_all / '50_overlay.generated.yml'
    assert overlay_gen.is_file()
    assert 'vm_role: core' in overlay_gen.read_text(encoding='utf-8')
    assert (gv_all / '00_shared.yml').resolve().name == 'all.yml'
    kvm_hosts = hosts.parent / 'group_vars' / 'kvm_hosts.yml'
    assert kvm_hosts.is_symlink()
    assert kvm_hosts.resolve().name == 'kvm_hosts.yml'
    assert 'ansible_playbook_python' in kvm_hosts.resolve().read_text(encoding='utf-8')


def test_render_overlay_group_vars_with_manifest_vars(repo_tree: Path) -> None:
    manifest_path = repo_tree / 'provisioning/inventory/manifest.yml'
    raw = yaml.safe_load(manifest_path.read_text(encoding='utf-8'))
    raw['overlays']['broetec-core']['vars'] = {'vm_vcpus': 8}
    manifest_path.write_text(yaml.dump(raw), encoding='utf-8')
    gen = InventoryGenerator(repo_tree)
    overlay = gen.load_manifest().get_overlay('broetec-core')
    text = gen.render_overlay_group_vars(overlay)
    assert 'vm_role: core' in text
    assert 'vm_vcpus: 8' in text


def test_env_override(repo_tree: Path) -> None:
    env_file = repo_tree / 'env/.env'
    env_file.write_text(
        'OVERLAY=broetec-core\nVM_IP=10.20.30.99\n',
        encoding='utf-8',
    )
    gen = InventoryGenerator(repo_tree, env_path=env_file)
    paths = gen.generate(['broetec-core'])
    content = paths[0].read_text(encoding='utf-8')
    assert '10.20.30.99' in content
    assert 'broetec-core' in content


def test_overlay_env_overrides_scoped() -> None:
    env = {'OVERLAY': 'broetec-storage', 'VM_IP': '10.20.30.99'}
    assert overlay_env_overrides(env, 'broetec-core') == {}
    assert overlay_env_overrides(env, 'broetec-storage')['VM_IP'] == '10.20.30.99'


def test_load_dotenv(tmp_path: Path) -> None:
    dotenv = tmp_path / '.env'
    dotenv.write_text('# comment\nFOO=bar\n', encoding='utf-8')
    assert load_dotenv(dotenv) == {'FOO': 'bar'}
    assert load_dotenv(tmp_path / 'missing') == {}
