"""Testes da selagem Sealed Secrets (roundtrip com chave privada)."""

from __future__ import annotations

import base64
import datetime as dt

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.secrets.sealer import (
    SCOPE_CLUSTER_WIDE,
    SCOPE_NAMESPACE_WIDE,
    SealError,
    encryption_label,
    hybrid_decrypt,
    hybrid_encrypt,
    load_public_key,
    seal_secret,
)


@pytest.fixture
def keypair() -> tuple[rsa.RSAPrivateKey, bytes]:
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, 'sealed-secrets')
    ])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509
        .CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=3650))
        .sign(private_key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    return private_key, cert_pem


def test_hybrid_encrypt_roundtrip(keypair) -> None:
    private_key, cert_pem = keypair
    public_key = load_public_key(cert_pem)
    label = b'ns/name'
    plaintext = b'super-secret-value'

    blob = hybrid_encrypt(public_key, plaintext, label)

    assert hybrid_decrypt(private_key, blob, label) == plaintext


def test_load_public_key_from_raw_public_pem(keypair) -> None:
    private_key, _ = keypair
    pub_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    assert isinstance(load_public_key(pub_pem), rsa.RSAPublicKey)


def test_seal_secret_roundtrip_strict(keypair) -> None:
    private_key, cert_pem = keypair
    public_key = load_public_key(cert_pem)
    secret = {
        'apiVersion': 'v1',
        'kind': 'Secret',
        'metadata': {'name': 'argocd-admin', 'namespace': 'argocd'},
        'type': 'Opaque',
        'data': {'password': base64.b64encode(b'p4ss').decode()},
        'stringData': {'username': 'admin'},
    }

    sealed = seal_secret(secret, public_key)

    assert sealed['kind'] == 'SealedSecret'
    assert sealed['apiVersion'] == 'bitnami.com/v1alpha1'
    assert sealed['metadata'] == {'name': 'argocd-admin', 'namespace': 'argocd'}
    assert sealed['spec']['template']['type'] == 'Opaque'

    label = encryption_label('argocd', 'argocd-admin')
    encrypted = sealed['spec']['encryptedData']
    pw_blob = base64.b64decode(encrypted['password'])
    user_blob = base64.b64decode(encrypted['username'])
    assert hybrid_decrypt(private_key, pw_blob, label) == b'p4ss'
    assert hybrid_decrypt(private_key, user_blob, label) == b'admin'


def test_seal_secret_preserves_annotations_and_labels(keypair) -> None:
    _, cert_pem = keypair
    public_key = load_public_key(cert_pem)
    secret = {
        'kind': 'Secret',
        'metadata': {
            'name': 's',
            'namespace': 'ns',
            'labels': {'app': 'demo'},
            'annotations': {
                'sealedsecrets.bitnami.com/patch': 'true',
                'kubectl.kubernetes.io/last-applied-configuration': '{}',
            },
        },
        'stringData': {'k': 'v'},
    }

    sealed = seal_secret(secret, public_key)
    template_meta = sealed['spec']['template']['metadata']

    assert template_meta['labels'] == {'app': 'demo'}
    assert template_meta['annotations'] == {
        'sealedsecrets.bitnami.com/patch': 'true'
    }
    assert 'annotations' not in sealed['metadata']


def test_seal_secret_cluster_wide_scope(keypair) -> None:
    private_key, cert_pem = keypair
    public_key = load_public_key(cert_pem)
    secret = {
        'kind': 'Secret',
        'metadata': {
            'name': 's',
            'namespace': 'ns',
            'annotations': {'sealedsecrets.bitnami.com/cluster-wide': 'true'},
        },
        'stringData': {'k': 'v'},
    }

    sealed = seal_secret(secret, public_key)

    assert sealed['metadata']['annotations'] == {
        'sealedsecrets.bitnami.com/cluster-wide': 'true'
    }
    blob = base64.b64decode(sealed['spec']['encryptedData']['k'])
    label = encryption_label('ns', 's', SCOPE_CLUSTER_WIDE)
    assert label == b''
    assert hybrid_decrypt(private_key, blob, label) == b'v'


def test_namespace_wide_label() -> None:
    assert encryption_label('ns', 's', SCOPE_NAMESPACE_WIDE) == b'ns'


def test_seal_secret_requires_namespace(keypair) -> None:
    _, cert_pem = keypair
    public_key = load_public_key(cert_pem)
    secret = {
        'kind': 'Secret',
        'metadata': {'name': 's'},
        'stringData': {'k': 'v'},
    }
    with pytest.raises(SealError, match='namespace'):
        seal_secret(secret, public_key)


def test_seal_secret_requires_data(keypair) -> None:
    _, cert_pem = keypair
    public_key = load_public_key(cert_pem)
    secret = {
        'kind': 'Secret',
        'metadata': {'name': 's', 'namespace': 'ns'},
    }
    with pytest.raises(SealError, match='no data'):
        seal_secret(secret, public_key)
