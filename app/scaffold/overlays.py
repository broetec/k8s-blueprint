"""Create, render and remove overlays (inventory + k8s manifests).

Purpose
    One entry point for the CLI and the terminal UI: turn a NewOverlay request
    into a local overlay (manifest.local.yml, inventory, 90_local.yml and
    k8s/**/overlays/<id>), and undo it.

Inputs
    provisioning/inventory/manifest.yml (+ manifest.local.yml), k8s/catalog.yml.

Outputs
    Gitignored files only: versioned overlays are never created or removed
    here (they can be re-rendered with OverlayManager.render).

Related
    app/scaffold/render.py, app/inventory/generator.py, app/cli.py
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path

import yaml

from app.inventory.generator import InventoryGenerator
from app.inventory.models import (
    InventoryManifest,
    K8sSpec,
    OverlaySpec,
    VmSpec,
)
from app.scaffold.catalog import Catalog, Selection, VmSize
from app.scaffold.render import OverlayRenderer

_ID_RE = re.compile(r'^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$')
_RESERVED_PREFIXES = ('broetec-', '_')
_SHARED_VARS = Path('provisioning/inventory/_shared/group_vars/all.yml')
_LOCAL_VARS = Path('group_vars/all/90_local.yml')
# Static IPs are suggested outside the libvirt DHCP range, away from the
# versioned overlays (.40/.50/.60) and the golden builder (.250).
_SUGGEST_FIRST_HOST = 70
_SUGGEST_LAST_HOST = 249
SSLIP_SUFFIX = 'sslip.io'
TLS_ISSUERS = ('selfsigned', 'letsencrypt-prod', 'letsencrypt-staging')


class OverlayError(ValueError):
    """Invalid overlay request."""


@dataclass(frozen=True)
class NewOverlay:
    overlay_id: str
    ip: str
    stacks: tuple[str, ...]
    disable: tuple[str, ...] = ()
    label: str = ''
    role: str = ''
    vm_name: str = ''
    domain: str = ''
    tls_issuer: str = 'selfsigned'
    vcpus: int | None = None
    memory_mb: int | None = None
    disk_size_gb: int | None = None


@dataclass(frozen=True)
class CreatedOverlay:
    spec: OverlaySpec
    size: VmSize
    files: tuple[Path, ...]


def sslip_domain(ip: str) -> str:
    """Wildcard domain that resolves to `ip` without any DNS record."""
    return f'{ip.replace(".", "-")}.{SSLIP_SUFFIX}'


class OverlayManager:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.generator = InventoryGenerator(self.repo_root)
        self.catalog = Catalog.load(self.repo_root)
        self.renderer = OverlayRenderer(self.repo_root, self.catalog)

    # -- read ---------------------------------------------------------------

    def manifest(self) -> InventoryManifest:
        return self.generator.load_manifest()

    def shared_vars(self) -> dict:
        path = self.repo_root / _SHARED_VARS
        return yaml.safe_load(path.read_text(encoding='utf-8')) or {}

    def network(self) -> IPv4Network:
        cidr = (self.shared_vars().get('kvm_network') or {}).get(
            'subnet_cidr', '10.20.30.0/24'
        )
        return IPv4Network(cidr)

    def bases(self) -> dict[str, OverlaySpec]:
        """Overlays that can be used as a base (they declare k8s)."""
        return {
            overlay_id: spec
            for overlay_id, spec in self.manifest().overlays.items()
            if spec.k8s is not None
        }

    def used_ips(self) -> set[str]:
        return {
            vm.ip
            for spec in self.manifest().overlays.values()
            for vm in spec.vms
        }

    def suggest_ip(self) -> str:
        network = self.network()
        used = self.used_ips()
        dhcp = self._dhcp_range()
        base = int(network.network_address)
        for host in range(_SUGGEST_FIRST_HOST, _SUGGEST_LAST_HOST + 1):
            candidate = IPv4Address(base + host)
            if candidate not in network or str(candidate) in used:
                continue
            if dhcp and dhcp[0] <= candidate <= dhcp[1]:
                continue
            return str(candidate)
        msg = f'No free static IP left in {network}'
        raise OverlayError(msg)

    def selection(
        self,
        stacks: tuple[str, ...] | list[str],
        disable: tuple[str, ...] | list[str] = (),
    ) -> Selection:
        try:
            return self.catalog.select(stacks, disable)
        except (KeyError, ValueError) as exc:
            raise OverlayError(str(exc).strip('"\'')) from exc

    # -- write --------------------------------------------------------------

    def build_spec(self, new: NewOverlay) -> tuple[OverlaySpec, VmSize]:
        """Validate a request and turn it into an OverlaySpec + VM size."""
        manifest = self.manifest()
        overlay_id = new.overlay_id.strip()
        if not _ID_RE.match(overlay_id):
            msg = (
                f'Invalid overlay id {overlay_id!r}: use lowercase letters, '
                'digits and "-" (max 40 chars)'
            )
            raise OverlayError(msg)
        if overlay_id.startswith(_RESERVED_PREFIXES):
            msg = (
                f'Overlay id {overlay_id!r} uses a reserved prefix '
                f'({", ".join(_RESERVED_PREFIXES)}), kept for versioned '
                'overlays'
            )
            raise OverlayError(msg)
        if overlay_id in manifest.overlays:
            msg = f'Overlay {overlay_id!r} already exists'
            raise OverlayError(msg)
        vm_name = (new.vm_name or overlay_id).strip()
        names = {vm.name for s in manifest.overlays.values() for vm in s.vms}
        if vm_name in names:
            msg = f'VM name {vm_name!r} is already used by another overlay'
            raise OverlayError(msg)
        self._check_ip(new.ip)
        if new.tls_issuer not in TLS_ISSUERS:
            msg = f'Invalid TLS issuer {new.tls_issuer!r}: {TLS_ISSUERS}'
            raise OverlayError(msg)
        selection = self.selection(new.stacks, new.disable)
        suggested = selection.vm_size()
        size = VmSize(
            vcpus=new.vcpus or suggested.vcpus,
            memory_mb=new.memory_mb or suggested.memory_mb,
            disk_size_gb=new.disk_size_gb or suggested.disk_size_gb,
        )
        try:
            spec = OverlaySpec(
                overlay_id=overlay_id,
                label=new.label or f'Local overlay {overlay_id}',
                role=new.role or overlay_id,
                vms=(VmSpec(name=vm_name, ip=new.ip),),
                k8s=K8sSpec(
                    stacks=tuple(selection.stack_names),
                    domain=new.domain.strip() or sslip_domain(new.ip),
                    disable=tuple(new.disable),
                    tls_issuer=new.tls_issuer,
                ),
                local=True,
            )
        except ValueError as exc:
            raise OverlayError(str(exc)) from exc
        return spec, size

    def create(self, new: NewOverlay) -> CreatedOverlay:
        spec, size = self.build_spec(new)
        leftovers = self.renderer.overlay_dirs(spec.overlay_id)
        if leftovers:
            msg = (
                f'k8s files for {spec.overlay_id!r} already exist '
                f'(e.g. {leftovers[0]}); remove them first'
            )
            raise OverlayError(msg)
        manifest = self.manifest()
        manifest.overlays[spec.overlay_id] = spec
        manifest.save_local()
        self.generator.generate([spec.overlay_id])
        self._write_local_vars(spec, size)
        files = self.renderer.write(spec)
        return CreatedOverlay(spec=spec, size=size, files=tuple(files))

    def render(self, overlay_id: str, *, force: bool = True) -> list[Path]:
        """(Re)render the k8s files of an existing overlay from templates."""
        spec = self.manifest().get_overlay(overlay_id)
        if spec.k8s is None:
            msg = f'Overlay {overlay_id!r} has no k8s section'
            raise OverlayError(msg)
        return self.renderer.write(spec, force=force)

    def remove(
        self,
        overlay_id: str,
        *,
        purge_env: bool = False,
        force: bool = False,
    ) -> list[Path]:
        """Delete a local overlay; returns the removed paths."""
        manifest = self.manifest()
        spec = manifest.get_overlay(overlay_id)
        if not spec.local:
            msg = f'Overlay {overlay_id!r} is versioned and cannot be removed'
            raise OverlayError(msg)
        disks = self.disks(spec)
        if disks and not force:
            msg = (
                f'VM disk still exists ({disks[0]}): run '
                f'`make destroy OVERLAY={overlay_id}` first or use force'
            )
            raise OverlayError(msg)
        targets = [
            *self.renderer.overlay_dirs(overlay_id),
            Path('provisioning/inventory') / overlay_id,
        ]
        if purge_env:
            targets.append(Path('env') / overlay_id)
        removed: list[Path] = []
        for relative in targets:
            path = self.repo_root / relative
            if path.is_dir():
                shutil.rmtree(path)
                removed.append(relative)
        del manifest.overlays[overlay_id]
        manifest.save_local()
        return removed

    def disks(self, spec: OverlaySpec) -> list[Path]:
        root = Path('lab/disks')
        return [
            root / f'{vm.name}.qcow2'
            for vm in spec.vms
            if (self.repo_root / root / f'{vm.name}.qcow2').exists()
        ]

    # -- helpers ------------------------------------------------------------

    def _dhcp_range(self) -> tuple[IPv4Address, IPv4Address] | None:
        network = self.shared_vars().get('kvm_network') or {}
        start, end = network.get('dhcp_start'), network.get('dhcp_end')
        if not start or not end:
            return None
        return IPv4Address(start), IPv4Address(end)

    def _check_ip(self, ip: str) -> None:
        try:
            address = IPv4Address(ip)
        except ValueError as exc:
            msg = f'Invalid IP: {ip!r}'
            raise OverlayError(msg) from exc
        network = self.network()
        if address not in network or address in {
            network.network_address,
            network.broadcast_address,
        }:
            msg = f'IP {ip} is outside the lab network {network}'
            raise OverlayError(msg)
        if ip in self.used_ips():
            msg = f'IP {ip} is already used by another overlay'
            raise OverlayError(msg)
        dhcp = self._dhcp_range()
        if dhcp and dhcp[0] <= address <= dhcp[1]:
            msg = f'IP {ip} is inside the DHCP range {dhcp[0]}-{dhcp[1]}'
            raise OverlayError(msg)

    def _write_local_vars(self, spec: OverlaySpec, size: VmSize) -> Path:
        path = (
            self.repo_root
            / 'provisioning/inventory'
            / spec.overlay_id
            / _LOCAL_VARS
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '---\n'
            f'# Local overrides for overlay {spec.overlay_id} — created by\n'
            '# `k8s-blueprint overlay new`; edit freely (never regenerated).\n'
            f'vm_vcpus: {size.vcpus}\n'
            f'vm_memory_mb: {size.memory_mb}\n'
            f'vm_disk_size_gb: {size.disk_size_gb}\n',
            encoding='utf-8',
        )
        return path
