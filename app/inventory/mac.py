"""MAC derivado do hostname (mesma regra que a role kvm_host no Ansible)."""

from __future__ import annotations

import hashlib
import re

_MAC_RE = re.compile(
    r'^([0-9a-f]{2}:){5}[0-9a-f]{2}$',
    re.IGNORECASE,
)


def derive_mac(hostname: str) -> str:
    """52:54:00 + primeiros 6 hex do MD5 do hostname (compatível com Ansible hash)."""
    digest = hashlib.md5(hostname.encode()).hexdigest()
    return f'52:54:00:{digest[0:2]}:{digest[2:4]}:{digest[4:6]}'


def normalize_mac(mac: str) -> str:
    value = mac.strip().lower()
    if not _MAC_RE.match(value):
        msg = f'MAC inválido: {mac!r}'
        raise ValueError(msg)
    return value


def resolve_mac(hostname: str, mac: str | None = None) -> str:
    if mac:
        return normalize_mac(mac)
    return derive_mac(hostname)
