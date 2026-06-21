"""Seal Kubernetes Secrets into Sealed Secrets without the kubeseal binary.

Purpose
    Reimplement the Sealed Secrets ``HybridEncrypt`` scheme (AES-256-GCM
    session key wrapped with RSA-OAEP/SHA-256) so the controller can decrypt
    the result, using only ``cryptography``.

Inputs
    A controller public certificate (PEM) and a Kubernetes ``Secret`` manifest.

Outputs
    A ``bitnami.com/v1alpha1`` ``SealedSecret`` manifest (as a dict).

Related
    k8s/sealed-secrets/README.md, app/secrets/cli.py
"""

from __future__ import annotations

import base64
import os
import struct
from collections.abc import Callable

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# AES-256 session key; GCM nonce is all zeros because the key is single-use
# (same invariants the upstream Go controller relies on).
_SESSION_KEY_BYTES = 32
_GCM_NONCE = b'\x00' * 12

SCOPE_STRICT = 'strict'
SCOPE_NAMESPACE_WIDE = 'namespace-wide'
SCOPE_CLUSTER_WIDE = 'cluster-wide'

_ANNOTATION_CLUSTER_WIDE = 'sealedsecrets.bitnami.com/cluster-wide'
_ANNOTATION_NAMESPACE_WIDE = 'sealedsecrets.bitnami.com/namespace-wide'
_ANNOTATION_LAST_APPLIED = 'kubectl.kubernetes.io/last-applied-configuration'

RngFn = Callable[[int], bytes]


class SealError(Exception):
    """Raised when a Secret cannot be sealed."""


def load_public_key(pem_data: bytes) -> rsa.RSAPublicKey:
    """Load the RSA public key from a controller certificate or raw key PEM."""
    key: object
    try:
        cert = x509.load_pem_x509_certificate(pem_data)
        key = cert.public_key()
    except ValueError:
        key = serialization.load_pem_public_key(pem_data)
    if not isinstance(key, rsa.RSAPublicKey):
        msg = 'Public key is not an RSA key'
        raise SealError(msg)
    return key


def encryption_label(
    namespace: str,
    name: str,
    scope: str = SCOPE_STRICT,
) -> bytes:
    """Return the RSA-OAEP label for the given sealing scope.

    Must match the controller exactly or decryption fails:
    strict -> ``namespace/name``, namespace-wide -> ``namespace``,
    cluster-wide -> empty.
    """
    if scope == SCOPE_CLUSTER_WIDE:
        return b''
    if scope == SCOPE_NAMESPACE_WIDE:
        return namespace.encode()
    return f'{namespace}/{name}'.encode()


def hybrid_encrypt(
    public_key: rsa.RSAPublicKey,
    plaintext: bytes,
    label: bytes,
    *,
    rng: RngFn = os.urandom,
) -> bytes:
    """Encrypt ``plaintext`` using the Sealed Secrets hybrid scheme.

    Layout: ``uint16(len(rsa_ct))`` big-endian, then the RSA-OAEP ciphertext,
    then the AES-256-GCM ciphertext (with its 16-byte tag appended).
    """
    session_key = rng(_SESSION_KEY_BYTES)
    rsa_ciphertext = public_key.encrypt(
        session_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=label,
        ),
    )
    aes_ciphertext = AESGCM(session_key).encrypt(
        _GCM_NONCE,
        plaintext,
        None,
    )
    prefix = struct.pack('>H', len(rsa_ciphertext))
    return prefix + rsa_ciphertext + aes_ciphertext


def hybrid_decrypt(
    private_key: rsa.RSAPrivateKey,
    blob: bytes,
    label: bytes,
) -> bytes:
    """Inverse of :func:`hybrid_encrypt` (used for verification/tests)."""
    (rsa_len,) = struct.unpack('>H', blob[:2])
    rsa_ciphertext = blob[2 : 2 + rsa_len]
    aes_ciphertext = blob[2 + rsa_len :]
    session_key = private_key.decrypt(
        rsa_ciphertext,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=label,
        ),
    )
    return AESGCM(session_key).decrypt(_GCM_NONCE, aes_ciphertext, None)


def scope_from_annotations(annotations: dict[str, str]) -> str:
    """Derive the sealing scope from the Secret annotations (strict default)."""
    if annotations.get(_ANNOTATION_CLUSTER_WIDE) == 'true':
        return SCOPE_CLUSTER_WIDE
    if annotations.get(_ANNOTATION_NAMESPACE_WIDE) == 'true':
        return SCOPE_NAMESPACE_WIDE
    return SCOPE_STRICT


def _plaintext_items(secret: dict) -> dict[str, bytes]:
    """Collect plaintext bytes from ``data`` (base64) and ``stringData``."""
    items: dict[str, bytes] = {}
    for key, value in (secret.get('data') or {}).items():
        try:
            items[key] = base64.b64decode(value, validate=True)
        except (ValueError, TypeError) as exc:
            msg = f'data[{key!r}] is not valid base64'
            raise SealError(msg) from exc
    for key, value in (secret.get('stringData') or {}).items():
        items[key] = value.encode() if isinstance(value, str) else bytes(value)
    return items


def seal_secret(
    secret: dict,
    public_key: rsa.RSAPublicKey,
    *,
    rng: RngFn = os.urandom,
) -> dict:
    """Build a ``SealedSecret`` dict from a Kubernetes ``Secret`` dict."""
    if (secret.get('kind') or 'Secret') != 'Secret':
        msg = f'Expected kind Secret, got {secret.get("kind")!r}'
        raise SealError(msg)

    metadata = secret.get('metadata') or {}
    name = metadata.get('name')
    namespace = metadata.get('namespace')
    if not name:
        msg = 'Secret metadata.name is required'
        raise SealError(msg)
    if not namespace:
        msg = 'Secret metadata.namespace is required (strict scope)'
        raise SealError(msg)

    annotations = {
        key: value
        for key, value in (metadata.get('annotations') or {}).items()
        if key != _ANNOTATION_LAST_APPLIED
    }
    scope = scope_from_annotations(annotations)
    label = encryption_label(namespace, name, scope)

    items = _plaintext_items(secret)
    if not items:
        msg = 'Secret has no data/stringData to seal'
        raise SealError(msg)

    encrypted_data = {
        key: base64.b64encode(
            hybrid_encrypt(public_key, plaintext, label, rng=rng)
        ).decode()
        for key, plaintext in items.items()
    }

    template_metadata: dict = {'name': name, 'namespace': namespace}
    if annotations:
        template_metadata['annotations'] = annotations
    if metadata.get('labels'):
        template_metadata['labels'] = metadata['labels']

    template: dict = {'metadata': template_metadata}
    if secret.get('type'):
        template['type'] = secret['type']

    sealed_metadata: dict = {'name': name, 'namespace': namespace}
    if scope == SCOPE_CLUSTER_WIDE:
        sealed_metadata['annotations'] = {_ANNOTATION_CLUSTER_WIDE: 'true'}
    elif scope == SCOPE_NAMESPACE_WIDE:
        sealed_metadata['annotations'] = {_ANNOTATION_NAMESPACE_WIDE: 'true'}

    return {
        'apiVersion': 'bitnami.com/v1alpha1',
        'kind': 'SealedSecret',
        'metadata': sealed_metadata,
        'spec': {
            'encryptedData': encrypted_data,
            'template': template,
        },
    }
