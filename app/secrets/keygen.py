"""Generate a Sealed Secrets controller keypair locally (BYOK bootstrap).

Purpose
    Produce the RSA private key and self-signed X.509 certificate that the
    Sealed Secrets controller adopts at boot, so secrets can be sealed
    offline before the cluster exists and stay decryptable across rebuilds.

Inputs
    A target key size (bits) and certificate validity (days), plus the
    Secret name/namespace used to wrap the keypair for the controller.

Outputs
    An ``rsa.RSAPrivateKey`` + ``x509.Certificate``, their PEM encodings, and
    a ``kubernetes.io/tls`` Secret dict labelled ``active`` for adoption.

Related
    app/secrets/sealer.py, app/secrets/cli.py, k8s/sealed-secrets/README.md
"""

from __future__ import annotations

import base64
import datetime as dt

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

# Upstream sealed-secrets names the controller key CN ``sealed-secret`` and
# adopts any TLS Secret carrying this label set to ``active``.
_CERT_COMMON_NAME = 'sealed-secret'
_ACTIVE_KEY_LABEL = 'sealedsecrets.bitnami.com/sealed-secrets-key'
_ACTIVE_KEY_VALUE = 'active'

# Small clock skew so the certificate is valid even with minor drift.
_NOT_BEFORE_SKEW = dt.timedelta(minutes=5)

# RSA keys below this are not considered safe for the controller key.
_MIN_KEY_BITS = 2048


class KeygenError(Exception):
    """Raised when a controller keypair cannot be generated."""


def generate_keypair(
    bits: int = 4096,
    *,
    days: int = 3650,
) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    """Generate an RSA private key and a matching self-signed certificate."""
    if bits < _MIN_KEY_BITS:
        msg = f'Key size must be at least {_MIN_KEY_BITS} bits, got {bits}'
        raise KeygenError(msg)

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=bits,
    )
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, _CERT_COMMON_NAME)
    ])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509
        .CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _NOT_BEFORE_SKEW)
        .not_valid_after(now + dt.timedelta(days=days))
        .sign(private_key, hashes.SHA256())
    )
    return private_key, cert


def private_key_pem(key: rsa.RSAPrivateKey) -> bytes:
    """Serialize the private key to unencrypted PKCS8 PEM."""
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def certificate_pem(cert: x509.Certificate) -> bytes:
    """Serialize the certificate to PEM."""
    return cert.public_bytes(serialization.Encoding.PEM)


def build_controller_key_secret(
    name: str,
    namespace: str,
    cert_pem: bytes,
    key_pem: bytes,
) -> dict:
    """Build the ``kubernetes.io/tls`` Secret the controller adopts at boot."""
    return {
        'apiVersion': 'v1',
        'kind': 'Secret',
        'type': 'kubernetes.io/tls',
        'metadata': {
            'name': name,
            'namespace': namespace,
            'labels': {_ACTIVE_KEY_LABEL: _ACTIVE_KEY_VALUE},
        },
        'data': {
            'tls.crt': base64.b64encode(cert_pem).decode(),
            'tls.key': base64.b64encode(key_pem).decode(),
        },
    }
