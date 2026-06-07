"""MAC derived from hostname (same rule as Ansible role 00_install_kvm)."""

from __future__ import annotations

import hashlib
import re

_MAC_RE = re.compile(
    r'^([0-9a-f]{2}:){5}[0-9a-f]{2}$',
    re.IGNORECASE,
)


def derive_mac(hostname: str) -> str:
    """52:54:00 + first 6 hex chars of MD5(hostname) — compatible with Ansible hash."""
    digest = hashlib.md5(hostname.encode()).hexdigest()
    return f'52:54:00:{digest[0:2]}:{digest[2:4]}:{digest[4:6]}'


def normalize_mac(mac: str) -> str:
    value = mac.strip().lower()
    if not _MAC_RE.match(value):
        msg = f'Invalid MAC: {mac!r}'
        raise ValueError(msg)
    return value


def resolve_mac(hostname: str, mac: str | None = None) -> str:
    if mac:
        return normalize_mac(mac)
    return derive_mac(hostname)
