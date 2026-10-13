"""Inventory manifest models and validation.

Purpose
    Parse manifest.yml into typed specs (VmSpec, OverlaySpec, InventoryManifest).

Inputs
    YAML file at provisioning/inventory/manifest.yml, plus the optional
    gitignored manifest.local.yml next to it (overlays created locally by
    `k8s-blueprint overlay new`).

Outputs
    Validated dataclasses used by InventoryGenerator.

Related
    app/inventory/README.md, app/inventory/mac.py
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import yaml

from app.inventory.mac import normalize_mac, resolve_mac

_IPV4_RE = re.compile(
    r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}'
    r'(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$',
)


@dataclass(frozen=True)
class VmSpec:
    name: str
    ip: str
    mac: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            msg = 'VM name cannot be empty'
            raise ValueError(msg)
        if not _IPV4_RE.match(self.ip):
            msg = f'Invalid IP: {self.ip!r}'
            raise ValueError(msg)
        ip_address(self.ip)
        if self.mac is not None:
            object.__setattr__(self, 'mac', normalize_mac(self.mac))

    def resolved_mac(self) -> str:
        return resolve_mac(self.name, self.mac)


@dataclass(frozen=True)
class K8sSpec:
    """Kubernetes selection of an overlay (stacks from k8s/catalog.yml)."""

    stacks: tuple[str, ...]
    domain: str
    disable: tuple[str, ...] = ()
    tls_issuer: str = 'selfsigned'
    argo_source: str = 'local'

    def __post_init__(self) -> None:
        if not self.stacks:
            msg = 'k8s.stacks cannot be empty'
            raise ValueError(msg)
        if not self.domain.strip():
            msg = 'k8s.domain cannot be empty'
            raise ValueError(msg)
        if self.argo_source not in {'local', 'remote'}:
            msg = f'Invalid k8s.argo_source: {self.argo_source!r}'
            raise ValueError(msg)

    def to_manifest(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            'stacks': list(self.stacks),
            'domain': self.domain,
            'tls_issuer': self.tls_issuer,
        }
        if self.disable:
            data['disable'] = list(self.disable)
        if self.argo_source != 'local':
            data['argo_source'] = self.argo_source
        return data


@dataclass(frozen=True)
class OverlaySpec:
    overlay_id: str
    label: str
    role: str
    vms: tuple[VmSpec, ...]
    extra_vars: tuple[tuple[str, Any], ...] = ()
    k8s: K8sSpec | None = None
    local: bool = False

    @property
    def primary_vm(self) -> VmSpec:
        return self.vms[0]

    def extra_vars_dict(self) -> dict[str, Any]:
        return dict(self.extra_vars)

    def to_manifest(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            'label': self.label,
            'role': self.role,
            'vms': [
                {'name': vm.name, 'ip': vm.ip}
                | ({'mac': vm.mac} if vm.mac else {})
                for vm in self.vms
            ],
        }
        if self.k8s is not None:
            data['k8s'] = self.k8s.to_manifest()
        if self.extra_vars:
            data['vars'] = self.extra_vars_dict()
        return data


@dataclass(frozen=True)
class InventoryDefaults:
    kvm_host: str
    ansible_connection: str
    ansible_user: str
    ansible_connection_vm: str
    ansible_host_key_checking: bool
    ansible_libssh_host_key_auto_add: bool
    ansible_libssh_config_file: str | None


@dataclass
class InventoryManifest:
    defaults: InventoryDefaults
    overlays: dict[str, OverlaySpec]
    path: Path = field(repr=False)

    @classmethod
    def load(cls, path: Path) -> InventoryManifest:
        raw = yaml.safe_load(path.read_text(encoding='utf-8'))
        if not isinstance(raw, dict):
            msg = f'Invalid manifest: {path}'
            raise ValueError(msg)
        defaults = _parse_defaults(raw.get('defaults') or {})
        overlays_raw = raw.get('overlays') or {}
        if not overlays_raw:
            msg = 'Manifest has no overlays'
            raise ValueError(msg)
        overlays: dict[str, OverlaySpec] = {}
        for overlay_id, spec in overlays_raw.items():
            overlays[overlay_id] = _parse_overlay(overlay_id, spec or {})
        for overlay_id, spec in _load_local_overlays(path).items():
            if overlay_id in overlays:
                msg = (
                    f'Local overlay {overlay_id!r} collides with a versioned '
                    f'overlay in {path.name}'
                )
                raise ValueError(msg)
            overlays[overlay_id] = _parse_overlay(
                overlay_id, spec or {}, local=True
            )
        return cls(defaults=defaults, overlays=overlays, path=path)

    @property
    def local_path(self) -> Path:
        return local_manifest_path(self.path)

    def overlay_ids(self) -> list[str]:
        return sorted(self.overlays.keys())

    def local_overlays(self) -> dict[str, OverlaySpec]:
        return {k: v for k, v in self.overlays.items() if v.local}

    def save_local(self) -> Path:
        """Write the local overlays back to manifest.local.yml."""
        payload = {
            'overlays': {
                overlay_id: spec.to_manifest()
                for overlay_id, spec in sorted(self.local_overlays().items())
            },
        }
        header = (
            '# Local overlays (gitignored). Managed by `k8s-blueprint overlay`'
            ' — same schema as\n# manifest.yml > overlays.\n'
        )
        target = self.local_path
        if not payload['overlays']:
            target.unlink(missing_ok=True)
            return target
        target.write_text(
            header + yaml.safe_dump(payload, sort_keys=False),
            encoding='utf-8',
        )
        return target

    def get_overlay(self, overlay_id: str) -> OverlaySpec:
        try:
            return self.overlays[overlay_id]
        except KeyError as exc:
            msg = f'Unknown overlay: {overlay_id!r}. Available: {self.overlay_ids()}'
            raise KeyError(msg) from exc


def local_manifest_path(manifest_path: Path) -> Path:
    return manifest_path.with_name('manifest.local.yml')


def _load_local_overlays(manifest_path: Path) -> dict[str, Any]:
    path = local_manifest_path(manifest_path)
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    if not isinstance(raw, dict):
        msg = f'Invalid local manifest: {path}'
        raise ValueError(msg)
    overlays = raw.get('overlays') or {}
    if not isinstance(overlays, dict):
        msg = f'{path}: overlays must be a map'
        raise ValueError(msg)
    return overlays


def _parse_k8s(overlay_id: str, data: Any) -> K8sSpec | None:
    if not data:
        return None
    if not isinstance(data, dict):
        msg = f'Overlay {overlay_id!r}: k8s must be a map'
        raise ValueError(msg)
    try:
        return K8sSpec(
            stacks=tuple(str(s) for s in data.get('stacks') or ()),
            domain=str(data.get('domain', '')),
            disable=tuple(str(s) for s in data.get('disable') or ()),
            tls_issuer=str(data.get('tls_issuer', 'selfsigned')),
            argo_source=str(data.get('argo_source', 'local')),
        )
    except ValueError as exc:
        msg = f'Overlay {overlay_id!r}: {exc}'
        raise ValueError(msg) from exc


def _parse_defaults(data: dict[str, Any]) -> InventoryDefaults:
    return InventoryDefaults(
        kvm_host=str(data.get('kvm_host', 'localhost')),
        ansible_connection=str(data.get('ansible_connection', 'local')),
        ansible_user=str(data.get('ansible_user', 'broetec')),
        ansible_connection_vm=str(
            data.get('ansible_connection_vm', 'libssh'),
        ),
        ansible_host_key_checking=bool(data.get('ansible_host_key_checking', False)),
        ansible_libssh_host_key_auto_add=bool(
            data.get('ansible_libssh_host_key_auto_add', True),
        ),
        ansible_libssh_config_file=(
            str(data['ansible_libssh_config_file'])
            if data.get('ansible_libssh_config_file')
            else None
        ),
    )


def _parse_overlay(
    overlay_id: str,
    data: dict[str, Any],
    *,
    local: bool = False,
) -> OverlaySpec:
    vms_raw = data.get('vms') or []
    if not vms_raw:
        msg = f'Overlay {overlay_id!r} has no VMs'
        raise ValueError(msg)
    vms: list[VmSpec] = []
    for entry in vms_raw:
        if not isinstance(entry, dict):
            msg = f'Invalid VM entry in {overlay_id}'
            raise ValueError(msg)
        name = str(entry['name'])
        ip = str(entry['ip'])
        mac = entry.get('mac')
        vms.append(VmSpec(name=name, ip=ip, mac=str(mac) if mac else None))
    extra_raw = data.get('vars') or {}
    if not isinstance(extra_raw, dict):
        msg = f'Overlay {overlay_id!r}: vars must be a map'
        raise ValueError(msg)
    extra_vars = tuple(sorted(extra_raw.items(), key=lambda item: item[0]))
    return OverlaySpec(
        overlay_id=overlay_id,
        label=str(data.get('label', overlay_id)),
        role=str(data.get('role', 'generic')),
        vms=tuple(vms),
        extra_vars=extra_vars,
        k8s=_parse_k8s(overlay_id, data.get('k8s')),
        local=local,
    )
