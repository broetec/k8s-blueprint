"""Gera hosts.ini e liga group_vars partilhados por overlay."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import yaml

from app.inventory.env_file import load_dotenv, overlay_env_overrides
from app.inventory.models import InventoryManifest, OverlaySpec, VmSpec

_SHARED_GROUP_VARS = Path('_shared/group_vars')
_GROUP_VARS_DIR = Path('group_vars')
_GROUP_VARS_ALL = Path('group_vars/all')
_KVM_HOSTS_VARS = Path('group_vars/kvm_hosts.yml')
_OVERLAY_GENERATED = '50_overlay.generated.yml'


class InventoryGenerator:
    def __init__(
        self,
        repo_root: Path,
        manifest_path: Path | None = None,
        env_path: Path | None = None,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.inventory_root = self.repo_root / 'provisioning/inventory'
        self.manifest_path = manifest_path or (
            self.inventory_root / 'manifest.yml'
        )
        self.env_path = env_path or (self.repo_root / 'env/.env')

    def load_manifest(self) -> InventoryManifest:
        return InventoryManifest.load(self.manifest_path)

    def generate(
        self,
        overlay_ids: list[str] | None = None,
        *,
        dry_run: bool = False,
    ) -> list[Path]:
        manifest = self.load_manifest()
        env = load_dotenv(self.env_path)
        targets = overlay_ids or manifest.overlay_ids()
        written: list[Path] = []
        for overlay_id in targets:
            overlay = manifest.get_overlay(overlay_id)
            overlay = self._apply_env_overrides(overlay, env)
            path = self._write_overlay(overlay, manifest, dry_run=dry_run)
            written.append(path)
        return written

    def render_hosts_ini(
        self,
        overlay: OverlaySpec,
        manifest: InventoryManifest,
    ) -> str:
        d = manifest.defaults
        lines = [
            '; =============================================================================',
            '; Gerado automaticamente — NÃO EDITAR.',
            '; Fonte: provisioning/inventory/manifest.yml (+ env/.env se aplicável)',
            '; Regenerar: make inventory  |  uv run python -m app.inventory.cli generate',
            f'; Overlay: {overlay.overlay_id} — {overlay.label}',
            '; =============================================================================',
            '',
            '[kvm_hosts]',
            f'{d.kvm_host} ansible_connection={d.ansible_connection}',
            '',
            '[vms]',
            '; Hostname = nome libvirt (--name). vm_ip/ansible_host = cloud-init.',
        ]
        for vm in overlay.vms:
            mac = vm.resolved_mac()
            lines.append(
                f'{vm.name} ansible_host={vm.ip} vm_ip={vm.ip} vm_mac={mac}',
            )
        lines.extend(
            [
                '',
                '[vms:vars]',
                f'ansible_user={d.ansible_user}',
                f'vm_role={overlay.role}',
                '; libssh: evita worker dead no Cursor/AppImage. Requer make deps.',
                f'ansible_connection={d.ansible_connection_vm}',
                f'ansible_host_key_checking={str(d.ansible_host_key_checking)}',
                f'ansible_libssh_host_key_auto_add={str(d.ansible_libssh_host_key_auto_add)}',
                '',
            ],
        )
        return '\n'.join(lines)

    def render_overlay_group_vars(self, overlay: OverlaySpec) -> str:
        payload: dict[str, object] = {
            'vm_role': overlay.role,
            'overlay_id': overlay.overlay_id,
            'overlay_label': overlay.label,
        }
        payload.update(overlay.extra_vars_dict())
        header = (
            '# Gerado automaticamente — NÃO EDITAR.\n'
            '# Fonte: manifest.yml (+ env/.env se aplicável). Regenerar: make inventory\n'
            '---\n'
        )
        return header + yaml.dump(
            payload,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

    def _apply_env_overrides(
        self,
        overlay: OverlaySpec,
        env: dict[str, str],
    ) -> OverlaySpec:
        overrides = overlay_env_overrides(env, overlay.overlay_id)
        if not overrides:
            return overlay
        vms = list(overlay.vms)
        primary = vms[0]
        name = overrides.get('VM_NAME', primary.name)
        ip = overrides.get('VM_IP', primary.ip)
        vms[0] = VmSpec(name=name, ip=ip, mac=primary.mac if name == primary.name else None)
        return replace(overlay, vms=tuple(vms))

    def _write_overlay(
        self,
        overlay: OverlaySpec,
        manifest: InventoryManifest,
        *,
        dry_run: bool,
    ) -> Path:
        overlay_dir = self.inventory_root / overlay.overlay_id
        hosts_ini = overlay_dir / 'hosts.ini'
        content = self.render_hosts_ini(overlay, manifest)
        if dry_run:
            return hosts_ini
        overlay_dir.mkdir(parents=True, exist_ok=True)
        hosts_ini.write_text(content, encoding='utf-8')
        self._ensure_group_vars(overlay_dir, overlay)
        return hosts_ini

    def _ensure_group_vars(self, overlay_dir: Path, overlay: OverlaySpec) -> None:
        """group_vars/all/ em camadas: shared → overlay (manifest) → local."""
        gv_root = overlay_dir / _GROUP_VARS_DIR
        legacy_link = gv_root
        if legacy_link.is_symlink():
            legacy_link.unlink()
        elif legacy_link.is_dir() and not (legacy_link / 'all').is_dir():
            msg = (
                f'{legacy_link} existe mas não segue group_vars/all/ — '
                'migre manualmente ou remova'
            )
            raise FileExistsError(msg)

        gv_all = overlay_dir / _GROUP_VARS_ALL
        gv_all.mkdir(parents=True, exist_ok=True)

        shared_src = self.inventory_root / _SHARED_GROUP_VARS / 'all.yml'
        kvm_hosts_src = self.inventory_root / _SHARED_GROUP_VARS / 'kvm_hosts.yml'
        self._symlink_file(gv_all / '00_shared.yml', shared_src)
        self._symlink_file(overlay_dir / _KVM_HOSTS_VARS, kvm_hosts_src)
        dhcp_link = gv_all / '10_dhcp_reservations.yml'
        if dhcp_link.is_symlink() or dhcp_link.exists():
            dhcp_link.unlink()
        (gv_all / _OVERLAY_GENERATED).write_text(
            self.render_overlay_group_vars(overlay),
            encoding='utf-8',
        )

    def _symlink_file(self, link: Path, target: Path) -> None:
        rel = os.path.relpath(target.resolve(), link.parent.resolve())
        if link.is_symlink():
            if link.resolve() == target.resolve():
                return
            link.unlink()
        elif link.exists():
            msg = f'{link} existe e não é symlink para {target}'
            raise FileExistsError(msg)
        link.symlink_to(rel)


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        if (directory / 'provisioning/inventory/manifest.yml').is_file():
            return directory
    msg = 'Raiz do repositório não encontrada (provisioning/inventory/manifest.yml)'
    raise FileNotFoundError(msg)


def resolve_overlay_ids(
    manifest: InventoryManifest,
    cli_overlay: str | None,
    generate_all: bool,
    env: dict[str, str],
) -> list[str]:
    if generate_all:
        return manifest.overlay_ids()
    if cli_overlay:
        manifest.get_overlay(cli_overlay)
        return [cli_overlay]
    env_overlay = env.get('OVERLAY', '').strip()
    if env_overlay:
        manifest.get_overlay(env_overlay)
        return [env_overlay]
    default = os.environ.get('OVERLAY', '').strip() or 'broetec-core'
    manifest.get_overlay(default)
    return [default]
