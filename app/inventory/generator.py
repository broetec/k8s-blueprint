"""Generate hosts.ini and wire shared group_vars per overlay.

Purpose
    Render Ansible inventory from manifest.yml (+ env/.env overrides).

Inputs
    provisioning/inventory/manifest.yml, optional env/.env.

Outputs
    Per overlay: hosts.ini, 50_overlay.generated.yml, symlinks to _shared/.

Related
    app/inventory/README.md, make inventory, provisioning/inventory/README.md
"""

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

    def _resolve_vm_connection(
        self,
        manifest: InventoryManifest,
        env: dict[str, str],
    ) -> str:
        override = env.get('ANSIBLE_VM_CONNECTION', '').strip().lower()
        if override == 'ssh':
            return 'ssh'
        if override == 'libssh':
            return 'ansible.netcommon.libssh'
        return manifest.defaults.ansible_connection_vm

    def render_hosts_ini(
        self,
        overlay: OverlaySpec,
        manifest: InventoryManifest,
        env: dict[str, str] | None = None,
    ) -> str:
        d = manifest.defaults
        env = env or {}
        vm_connection = self._resolve_vm_connection(manifest, env)
        lines = [
            '; =============================================================================',
            '; Auto-generated — DO NOT EDIT.',
            '; Source: provisioning/inventory/manifest.yml (+ env/.env when applicable)',
            '; Regenerate: make inventory  |  uv run python -m app.inventory.cli generate',
            f'; Overlay: {overlay.overlay_id} — {overlay.label}',
            '; =============================================================================',
            '',
            '[kvm_hosts]',
            f'{d.kvm_host} ansible_connection={d.ansible_connection}',
            '',
            '[vms]',
            '; Hostname = libvirt domain name (--name). vm_ip/ansible_host = cloud-init.',
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
                '; libssh: avoids worker dead in Cursor/AppImage. Requires make deps.',
                f'ansible_connection={vm_connection}',
                f'ansible_host_key_checking={str(d.ansible_host_key_checking)}',
            ],
        )
        if vm_connection == 'ansible.netcommon.libssh':
            lines.append(
                f'ansible_libssh_host_key_auto_add={str(d.ansible_libssh_host_key_auto_add)}',
            )
            if d.ansible_libssh_config_file:
                config_path = (
                    self.repo_root / d.ansible_libssh_config_file
                ).resolve()
                lines.append(f'ansible_libssh_config_file={config_path}')
        lines.append('')
        return '\n'.join(lines)

    def render_overlay_group_vars(self, overlay: OverlaySpec) -> str:
        payload: dict[str, object] = {
            'vm_role': overlay.role,
            'overlay_id': overlay.overlay_id,
            'overlay_label': overlay.label,
        }
        payload.update(overlay.extra_vars_dict())
        header = (
            '# Auto-generated — DO NOT EDIT.\n'
            '# Source: manifest.yml (+ env/.env when applicable). Regenerate: make inventory\n'
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
        env = load_dotenv(self.env_path)
        content = self.render_hosts_ini(overlay, manifest, env)
        if dry_run:
            return hosts_ini
        overlay_dir.mkdir(parents=True, exist_ok=True)
        hosts_ini.write_text(content, encoding='utf-8')
        self._ensure_group_vars(overlay_dir, overlay)
        return hosts_ini

    def _ensure_group_vars(self, overlay_dir: Path, overlay: OverlaySpec) -> None:
        """Layered group_vars/all/: shared symlink → generated overlay → local 90_local.yml."""
        gv_root = overlay_dir / _GROUP_VARS_DIR
        legacy_link = gv_root
        if legacy_link.is_symlink():
            legacy_link.unlink()
        elif legacy_link.is_dir() and not (legacy_link / 'all').is_dir():
            msg = (
                f'{legacy_link} exists but is not group_vars/all/ layout — '
                'migrate manually or remove'
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
            msg = f'{link} exists and is not a symlink to {target}'
            raise FileExistsError(msg)
        link.symlink_to(rel)


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        if (directory / 'provisioning/inventory/manifest.yml').is_file():
            return directory
    msg = 'Repository root not found (provisioning/inventory/manifest.yml)'
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
