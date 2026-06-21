"""Secrets CLI — seal Kubernetes Secrets into Sealed Secrets (no kubeseal)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from app.secrets.keygen import (
    KeygenError,
    build_controller_key_secret,
    certificate_pem,
    generate_keypair,
    private_key_pem,
)
from app.secrets.sealer import SealError, load_public_key, seal_secret

_KEY_FILENAME = 'sealed-secrets-key.pem'
_CERT_FILENAME = 'sealed-secrets-pub.pem'
_SECRET_FILENAME = 'sealed-secrets-key-secret.yaml'
_KEY_FILE_MODE = 0o600


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='k8s-blueprint-seal',
        description='Seal a Kubernetes Secret into a SealedSecret manifest',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    seal = sub.add_parser('seal', help='Seal a Secret manifest')
    seal.add_argument(
        '--cert',
        '-c',
        type=Path,
        required=True,
        metavar='PUB.PEM',
        help='Controller public certificate (or RSA public key) PEM',
    )
    seal.add_argument(
        '--in',
        '-i',
        dest='input',
        type=Path,
        default=None,
        metavar='SECRET.YAML',
        help='Input Secret manifest (default: stdin)',
    )
    seal.add_argument(
        '--out',
        '-o',
        dest='output',
        type=Path,
        default=None,
        metavar='SEALEDSECRET.YAML',
        help='Output SealedSecret manifest (default: stdout)',
    )

    genkey = sub.add_parser(
        'genkey',
        help='Generate a Sealed Secrets controller keypair (BYOK bootstrap)',
    )
    genkey.add_argument(
        '--out-dir',
        '-d',
        dest='out_dir',
        type=Path,
        required=True,
        metavar='DIR',
        help='Target directory for key files (e.g. env/<cluster>/)',
    )
    genkey.add_argument(
        '--namespace',
        default='sealed-secrets',
        help='Namespace for the controller TLS Secret',
    )
    genkey.add_argument(
        '--name',
        default='sealed-secrets-key-bootstrap',
        help='Name for the controller TLS Secret',
    )
    genkey.add_argument(
        '--bits',
        type=int,
        default=4096,
        help='RSA key size in bits',
    )
    genkey.add_argument(
        '--days',
        type=int,
        default=3650,
        help='Certificate validity in days',
    )
    genkey.add_argument(
        '--force',
        action='store_true',
        help='Overwrite an existing key (loses prior sealed secrets)',
    )

    return parser


def cmd_seal(args: argparse.Namespace) -> int:
    public_key = load_public_key(args.cert.read_bytes())

    if args.input is None:
        raw = sys.stdin.read()
    else:
        raw = args.input.read_text(encoding='utf-8')

    secret = yaml.safe_load(raw)
    if not isinstance(secret, dict):
        msg = 'Input is not a single YAML mapping (Secret manifest)'
        raise SealError(msg)

    sealed = seal_secret(secret, public_key)
    rendered = yaml.safe_dump(sealed, sort_keys=False, default_flow_style=False)

    if args.output is None:
        sys.stdout.write(rendered)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding='utf-8')
        print(f'Written: {args.output}')
    return 0


def cmd_genkey(args: argparse.Namespace) -> int:
    out_dir: Path = args.out_dir
    key_path = out_dir / _KEY_FILENAME

    if key_path.exists() and not args.force:
        print(f'Keeping existing key: {key_path} (use --force to overwrite)')
        return 0

    private_key, cert = generate_keypair(args.bits, days=args.days)
    key_pem = private_key_pem(private_key)
    cert_pem = certificate_pem(cert)
    secret = build_controller_key_secret(
        args.name,
        args.namespace,
        cert_pem,
        key_pem,
    )
    rendered = yaml.safe_dump(secret, sort_keys=False)

    out_dir.mkdir(parents=True, exist_ok=True)
    cert_path = out_dir / _CERT_FILENAME
    secret_path = out_dir / _SECRET_FILENAME

    key_path.write_bytes(key_pem)
    key_path.chmod(_KEY_FILE_MODE)
    cert_path.write_bytes(cert_pem)
    secret_path.write_text(rendered, encoding='utf-8')

    print(f'Written: {key_path}')
    print(f'Written: {cert_path}')
    print(f'Written: {secret_path}')
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == 'seal':
            return cmd_seal(args)
        if args.command == 'genkey':
            return cmd_genkey(args)
    except (SealError, KeygenError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    parser.print_help()
    return 1


if __name__ == '__main__':
    sys.exit(main())
