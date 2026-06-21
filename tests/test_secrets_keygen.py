"""Testes da geração de chave do controlador (BYOK) e roundtrip de selagem."""

from __future__ import annotations

import base64

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.secrets.cli import main
from app.secrets.keygen import (
    KeygenError,
    build_controller_key_secret,
    certificate_pem,
    generate_keypair,
    private_key_pem,
)
from app.secrets.sealer import (
    encryption_label,
    hybrid_decrypt,
    load_public_key,
    seal_secret,
)

_KEY_FILENAME = 'sealed-secrets-key.pem'
_CERT_FILENAME = 'sealed-secrets-pub.pem'
_SECRET_FILENAME = 'sealed-secrets-key-secret.yaml'
_TEST_BITS = 2048
_KEY_FILE_MODE = 0o600


def test_generate_keypair_size_and_self_signed() -> None:
    private_key, cert = generate_keypair(_TEST_BITS)

    assert isinstance(private_key, rsa.RSAPrivateKey)
    assert private_key.key_size == _TEST_BITS

    cert_public = cert.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key_public = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    assert cert_public == key_public


def test_generate_keypair_rejects_small_keys() -> None:
    with pytest.raises(KeygenError, match='at least'):
        generate_keypair(1024)


def test_build_controller_key_secret_structure() -> None:
    private_key, cert = generate_keypair(_TEST_BITS)
    cert_pem = certificate_pem(cert)
    key_pem = private_key_pem(private_key)

    secret = build_controller_key_secret(
        'sealed-secrets-key-bootstrap',
        'sealed-secrets',
        cert_pem,
        key_pem,
    )

    assert secret['apiVersion'] == 'v1'
    assert secret['kind'] == 'Secret'
    assert secret['type'] == 'kubernetes.io/tls'
    assert secret['metadata']['labels'] == {
        'sealedsecrets.bitnami.com/sealed-secrets-key': 'active'
    }
    assert base64.b64decode(secret['data']['tls.crt']) == cert_pem
    assert base64.b64decode(secret['data']['tls.key']) == key_pem


def test_genkey_seal_roundtrip(tmp_path) -> None:
    out_dir = tmp_path / 'dev'
    assert (
        main(['genkey', '--out-dir', str(out_dir), '--bits', str(_TEST_BITS)])
        == 0
    )

    cert_pem = (out_dir / _CERT_FILENAME).read_bytes()
    key_pem = (out_dir / _KEY_FILENAME).read_bytes()
    private_key = serialization.load_pem_private_key(key_pem, password=None)

    public_key = load_public_key(cert_pem)
    secret = {
        'kind': 'Secret',
        'metadata': {'name': 'argocd-admin', 'namespace': 'argocd'},
        'type': 'Opaque',
        'stringData': {'password': 'p4ss', 'username': 'admin'},
    }
    sealed = seal_secret(secret, public_key)

    label = encryption_label('argocd', 'argocd-admin')
    encrypted = sealed['spec']['encryptedData']
    pw_blob = base64.b64decode(encrypted['password'])
    user_blob = base64.b64decode(encrypted['username'])
    assert hybrid_decrypt(private_key, pw_blob, label) == b'p4ss'
    assert hybrid_decrypt(private_key, user_blob, label) == b'admin'


def test_genkey_writes_secret_manifest(tmp_path) -> None:
    out_dir = tmp_path / 'dev'
    assert (
        main(['genkey', '--out-dir', str(out_dir), '--bits', str(_TEST_BITS)])
        == 0
    )

    manifest = yaml.safe_load((out_dir / _SECRET_FILENAME).read_text())
    assert manifest['type'] == 'kubernetes.io/tls'
    assert manifest['metadata']['namespace'] == 'sealed-secrets'
    assert manifest['metadata']['name'] == 'sealed-secrets-key-bootstrap'


def test_genkey_key_file_mode(tmp_path) -> None:
    out_dir = tmp_path / 'dev'
    assert (
        main(['genkey', '--out-dir', str(out_dir), '--bits', str(_TEST_BITS)])
        == 0
    )

    mode = (out_dir / _KEY_FILENAME).stat().st_mode & 0o777
    assert mode == _KEY_FILE_MODE


def test_genkey_idempotent_without_force(tmp_path) -> None:
    out_dir = tmp_path / 'dev'
    key_path = out_dir / _KEY_FILENAME

    assert (
        main(['genkey', '--out-dir', str(out_dir), '--bits', str(_TEST_BITS)])
        == 0
    )
    first = key_path.read_bytes()

    assert (
        main(['genkey', '--out-dir', str(out_dir), '--bits', str(_TEST_BITS)])
        == 0
    )
    assert key_path.read_bytes() == first


def test_genkey_force_regenerates(tmp_path) -> None:
    out_dir = tmp_path / 'dev'
    key_path = out_dir / _KEY_FILENAME

    assert (
        main(['genkey', '--out-dir', str(out_dir), '--bits', str(_TEST_BITS)])
        == 0
    )
    first = key_path.read_bytes()

    rc = main([
        'genkey',
        '--out-dir',
        str(out_dir),
        '--bits',
        '2048',
        '--force',
    ])
    assert rc == 0
    assert key_path.read_bytes() != first
