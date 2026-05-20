"""CLI do inventário — base para futura interface terminal."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.inventory.env_file import load_dotenv
from app.inventory.generator import InventoryGenerator, find_repo_root, resolve_overlay_ids
from app.inventory.models import InventoryManifest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='k8s-blueprint-inventory',
        description='Gera hosts.ini a partir de provisioning/inventory/manifest.yml',
    )
    parser.add_argument(
        '--repo-root',
        type=Path,
        default=None,
        help='Raiz do repositório (auto-detecta por defeito)',
    )
    parser.add_argument(
        '--env-file',
        type=Path,
        default=None,
        help='Ficheiro .env (default: env/.env)',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    gen = sub.add_parser('generate', help='Gera hosts.ini para overlay(s)')
    gen.add_argument(
        '--overlay',
        '-o',
        action='append',
        dest='overlays',
        metavar='NAME',
        help='Overlay a gerar (repetível)',
    )
    gen.add_argument(
        '--all',
        action='store_true',
        help='Gera todos os overlays do manifesto',
    )
    gen.add_argument(
        '--dry-run',
        action='store_true',
        help='Não escreve ficheiros; imprime no stdout',
    )

    sub.add_parser('list', help='Lista overlays definidos no manifesto')

    show = sub.add_parser('show', help='Mostra VMs de um overlay')
    show.add_argument('overlay', help='ID do overlay')

    return parser


def cmd_generate(args: argparse.Namespace) -> int:
    repo_root = args.repo_root or find_repo_root()
    env_path = args.env_file or (repo_root / 'env/.env')
    generator = InventoryGenerator(repo_root, env_path=env_path)
    manifest = generator.load_manifest()
    env = load_dotenv(env_path)
    if args.all:
        overlay_ids = manifest.overlay_ids()
    elif args.overlays:
        overlay_ids = list(args.overlays)
        for name in overlay_ids:
            manifest.get_overlay(name)
    else:
        overlay_ids = resolve_overlay_ids(
            manifest,
            cli_overlay=None,
            generate_all=False,
            env=env,
        )

    if args.dry_run:
        for overlay_id in overlay_ids:
            overlay = manifest.get_overlay(overlay_id)
            overlay = generator._apply_env_overrides(overlay, env)  # noqa: SLF001
            text = generator.render_hosts_ini(overlay, manifest)
            print(f'--- {overlay_id} ---')
            print(text)
        return 0

    paths = generator.generate(overlay_ids)
    for path in paths:
        print(f'Gerado: {path}')
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    repo_root = args.repo_root or find_repo_root()
    generator = InventoryGenerator(repo_root, env_path=args.env_file)
    manifest = generator.load_manifest()
    for overlay_id in manifest.overlay_ids():
        spec = manifest.get_overlay(overlay_id)
        vm = spec.primary_vm
        print(f'{overlay_id:20} {vm.name:20} {vm.ip:15}  {spec.label}')
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    repo_root = args.repo_root or find_repo_root()
    generator = InventoryGenerator(repo_root, env_path=args.env_file)
    manifest = generator.load_manifest()
    overlay = manifest.get_overlay(args.overlay)
    print(f'Overlay: {overlay.overlay_id}')
    print(f'Label:   {overlay.label}')
    print(f'Role:    {overlay.role}')
    for vm in overlay.vms:
        print(f'  VM: {vm.name} @ {vm.ip}')
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == 'generate':
        return cmd_generate(args)
    if args.command == 'list':
        return cmd_list(args)
    if args.command == 'show':
        return cmd_show(args)
    parser.print_help()
    return 1


if __name__ == '__main__':
    sys.exit(main())
