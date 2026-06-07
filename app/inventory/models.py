"""Modelos do manifesto de inventário."""

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
            msg = 'Nome da VM não pode ser vazio'
            raise ValueError(msg)
        if not _IPV4_RE.match(self.ip):
            msg = f'IP inválido: {self.ip!r}'
            raise ValueError(msg)
        ip_address(self.ip)
        if self.mac is not None:
            object.__setattr__(self, 'mac', normalize_mac(self.mac))

    def resolved_mac(self) -> str:
        return resolve_mac(self.name, self.mac)


@dataclass(frozen=True)
class OverlaySpec:
    overlay_id: str
    label: str
    role: str
    vms: tuple[VmSpec, ...]
    extra_vars: tuple[tuple[str, Any], ...] = ()

    @property
    def primary_vm(self) -> VmSpec:
        return self.vms[0]

    def extra_vars_dict(self) -> dict[str, Any]:
        return dict(self.extra_vars)


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
            msg = f'Manifesto inválido: {path}'
            raise ValueError(msg)
        defaults = _parse_defaults(raw.get('defaults') or {})
        overlays_raw = raw.get('overlays') or {}
        if not overlays_raw:
            msg = 'Manifesto sem overlays'
            raise ValueError(msg)
        overlays: dict[str, OverlaySpec] = {}
        for overlay_id, spec in overlays_raw.items():
            overlays[overlay_id] = _parse_overlay(overlay_id, spec or {})
        return cls(defaults=defaults, overlays=overlays, path=path)

    def overlay_ids(self) -> list[str]:
        return sorted(self.overlays.keys())

    def get_overlay(self, overlay_id: str) -> OverlaySpec:
        try:
            return self.overlays[overlay_id]
        except KeyError as exc:
            msg = f'Overlay desconhecido: {overlay_id!r}. Disponíveis: {self.overlay_ids()}'
            raise KeyError(msg) from exc


def _parse_defaults(data: dict[str, Any]) -> InventoryDefaults:
    return InventoryDefaults(
        kvm_host=str(data.get('kvm_host', 'localhost')),
        ansible_connection=str(data.get('ansible_connection', 'local')),
        ansible_user=str(data.get('ansible_user', 'rocky')),
        ansible_connection_vm=str(
            data.get('ansible_connection_vm', 'ansible.netcommon.libssh'),
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


def _parse_overlay(overlay_id: str, data: dict[str, Any]) -> OverlaySpec:
    vms_raw = data.get('vms') or []
    if not vms_raw:
        msg = f'Overlay {overlay_id!r} sem VMs'
        raise ValueError(msg)
    vms: list[VmSpec] = []
    for entry in vms_raw:
        if not isinstance(entry, dict):
            msg = f'VM inválida em {overlay_id}'
            raise ValueError(msg)
        name = str(entry['name'])
        ip = str(entry['ip'])
        mac = entry.get('mac')
        vms.append(VmSpec(name=name, ip=ip, mac=str(mac) if mac else None))
    extra_raw = data.get('vars') or {}
    if not isinstance(extra_raw, dict):
        msg = f'Overlay {overlay_id!r}: vars deve ser um mapa'
        raise ValueError(msg)
    extra_vars = tuple(sorted(extra_raw.items(), key=lambda item: item[0]))
    return OverlaySpec(
        overlay_id=overlay_id,
        label=str(data.get('label', overlay_id)),
        role=str(data.get('role', 'generic')),
        vms=tuple(vms),
        extra_vars=extra_vars,
    )
