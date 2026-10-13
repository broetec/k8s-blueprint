"""Testes dos segredos de laboratório (placeholders -> *-secret.yaml)."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import yaml

from app.secrets.lab import (
    STATUS_GENERATED,
    STATUS_MANUAL,
    STATUS_PRESENT,
    LabSecretStore,
    init_overlay,
    render,
    store_path,
)

OVERLAY = 'meu-lab'


def _example(root: Path, relative: str, body: str) -> Path:
    path = root / 'k8s' / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding='utf-8')
    return path


def test_same_name_gives_same_value(tmp_path: Path) -> None:
    store = LabSecretStore(tmp_path / 'lab-secrets.yml')
    text = render(
        'a: <lab:s3-key:20>\nb: <lab:s3-key:20>\nc: <lab:other>', store
    )
    data = yaml.safe_load(text)
    assert data['a'] == data['b']
    assert len(data['a']) == 20  # noqa: PLR2004
    assert len(data['c']) == 32  # noqa: PLR2004
    assert data['a'] != data['c']


def test_htpasswd_placeholder_hashes_the_named_value(tmp_path: Path) -> None:
    store = LabSecretStore(tmp_path / 'lab-secrets.yml')
    text = render('admin:<lab-htpasswd:filer-password>', store)
    password = store.get('filer-password')
    digest = hashlib.sha1(password.encode()).digest()  # noqa: S324
    assert text == 'admin:{SHA}' + base64.b64encode(digest).decode()


def test_init_generates_keeps_and_reports(tmp_path: Path) -> None:
    base = f'storage/app/overlays/{OVERLAY}'
    _example(
        tmp_path,
        f'{base}/a-secret.yaml.example',
        'stringData:\n  key: <lab:shared>\n',
    )
    _example(
        tmp_path,
        f'{base}/secrets/b-secret.yaml.example',
        'stringData:\n  key: <lab:shared>\n',
    )
    _example(
        tmp_path,
        f'{base}/token-secret.yaml.example',
        'stringData:\n  token: PUT_YOUR_TOKEN\n',
    )
    _example(
        tmp_path,
        f'{base}/kept-secret.yaml.example',
        'stringData:\n  key: <lab:kept>\n',
    )
    kept = _example(tmp_path, f'{base}/kept-secret.yaml', 'stringData: {}\n')
    _example(
        tmp_path,
        'storage/app/overlays/outro/x-secret.yaml.example',
        'stringData:\n  key: <lab:x>\n',
    )

    results = {r.target.name: r.status for r in init_overlay(tmp_path, OVERLAY)}

    assert results == {
        'a-secret.yaml': STATUS_GENERATED,
        'b-secret.yaml': STATUS_GENERATED,
        'token-secret.yaml': STATUS_MANUAL,
        'kept-secret.yaml': STATUS_PRESENT,
    }
    first = yaml.safe_load(
        (tmp_path / 'k8s' / base / 'a-secret.yaml').read_text()
    )
    second = yaml.safe_load(
        (tmp_path / 'k8s' / base / 'secrets/b-secret.yaml').read_text()
    )
    assert first == second
    assert kept.read_text() == 'stringData: {}\n'
    assert not (tmp_path / 'k8s' / base / 'token-secret.yaml').exists()
    store = store_path(tmp_path, OVERLAY)
    assert yaml.safe_load(store.read_text()) == {
        'shared': first['stringData']['key']
    }
    assert store.stat().st_mode & 0o777 == 0o600  # noqa: PLR2004

    again = {r.target.name: r.status for r in init_overlay(tmp_path, OVERLAY)}
    assert again['a-secret.yaml'] == STATUS_PRESENT
    assert (
        yaml.safe_load((tmp_path / 'k8s' / base / 'a-secret.yaml').read_text())
        == first
    )
