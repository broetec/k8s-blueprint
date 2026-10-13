"""Expected DNS records of the lab overlays and a resolver check.

Purpose
    List the A record each overlay needs (wildcard for the apps domain) and
    tell which ones do not resolve to the VM yet.

Notes
    Domains under sslip.io resolve by construction and need no record. The
    node FQDN needs none either: it is only resolved inside the VM
    (/etc/hosts); Ansible and `make ssh` use the IP.

Related
    app/scaffold/overlays.py, k8s/README.md
"""

from __future__ import annotations

import socket
from dataclasses import dataclass

from app.inventory.models import InventoryManifest
from app.scaffold.catalog import Catalog
from app.scaffold.overlays import SSLIP_SUFFIX

_PROBE_LABEL = 'dns-check'
STATUS_OK = 'ok'
STATUS_MISSING = 'missing'
STATUS_WRONG = 'wrong'
STATUS_AUTO = 'auto'


@dataclass(frozen=True)
class DnsRecord:
    overlay_id: str
    name: str
    ip: str
    purpose: str
    automatic: bool = False

    @property
    def probe(self) -> str:
        """Concrete hostname used to test the record."""
        if self.name.startswith('*.'):
            return f'{_PROBE_LABEL}.{self.name[2:]}'
        return self.name


@dataclass(frozen=True)
class DnsCheck:
    record: DnsRecord
    status: str
    resolved: tuple[str, ...] = ()


def expected_records(
    manifest: InventoryManifest,
    catalog: Catalog,
    overlay_ids: list[str] | None = None,
) -> list[DnsRecord]:
    records: list[DnsRecord] = []
    for overlay_id in overlay_ids or manifest.overlay_ids():
        spec = manifest.get_overlay(overlay_id)
        if spec.k8s is None:
            continue
        vm = spec.primary_vm
        selection = catalog.select(spec.k8s.stacks, spec.k8s.disable)
        hosts = ', '.join(host for host, _ in selection.hosts()) or '-'
        automatic = spec.k8s.domain.endswith(SSLIP_SUFFIX)
        records.append(
            DnsRecord(
                overlay_id=overlay_id,
                name=f'*.{spec.k8s.domain}',
                ip=vm.ip,
                purpose=f'apps ({hosts})',
                automatic=automatic,
            )
        )
    return records


def resolve(hostname: str) -> tuple[str, ...]:
    try:
        infos = socket.getaddrinfo(hostname, None, family=socket.AF_INET)
    except OSError:
        return ()
    return tuple(sorted({info[4][0] for info in infos}))


def check_records(records: list[DnsRecord]) -> list[DnsCheck]:
    checks: list[DnsCheck] = []
    for record in records:
        resolved = resolve(record.probe)
        if record.ip in resolved:
            status = STATUS_AUTO if record.automatic else STATUS_OK
        elif resolved:
            status = STATUS_WRONG
        else:
            status = STATUS_MISSING
        checks.append(DnsCheck(record=record, status=status, resolved=resolved))
    return checks
