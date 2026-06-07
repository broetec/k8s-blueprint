"""Minimal .env file reader (KEY=VALUE lines)."""

from __future__ import annotations

from pathlib import Path


def load_dotenv(path: Path | None) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            continue
        key, _, value = line.partition('=')
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def overlay_env_overrides(
    env: dict[str, str],
    overlay_id: str,
) -> dict[str, str]:
    """Apply VM_NAME/VM_IP overrides when OVERLAY in .env matches overlay_id."""
    env_overlay = env.get('OVERLAY', '').strip()
    if env_overlay and env_overlay != overlay_id:
        return {}
    overrides: dict[str, str] = {}
    if env.get('VM_NAME', '').strip():
        overrides['VM_NAME'] = env['VM_NAME'].strip()
    if env.get('VM_IP', '').strip():
        overrides['VM_IP'] = env['VM_IP'].strip()
    return overrides
