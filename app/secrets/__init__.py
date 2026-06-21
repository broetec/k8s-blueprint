"""Selagem de Secrets no formato Sealed Secrets (sem o binário kubeseal)."""

from app.secrets.keygen import (
    KeygenError,
    build_controller_key_secret,
    certificate_pem,
    generate_keypair,
    private_key_pem,
)
from app.secrets.sealer import (
    SealError,
    encryption_label,
    hybrid_encrypt,
    load_public_key,
    seal_secret,
)

__all__ = [
    'KeygenError',
    'SealError',
    'build_controller_key_secret',
    'certificate_pem',
    'encryption_label',
    'generate_keypair',
    'hybrid_encrypt',
    'load_public_key',
    'private_key_pem',
    'seal_secret',
]
