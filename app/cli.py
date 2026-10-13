"""k8s-blueprint CLI — overlays, catalog, DNS and validation.

Purpose
    Single command for everything that is not a playbook run: create and
    remove local overlays, list the catalog, check DNS records and validate
    the manifests. Without a subcommand it opens the terminal UI.

Related
    app/scaffold/, app/tui/, make tui, make new
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from app.inventory.generator import find_repo_root
from app.scaffold import dns as dns_checks
from app.scaffold import validate as validation
from app.scaffold.overlays import (
    TLS_ISSUERS,
    NewOverlay,
    OverlayError,
    OverlayManager,
)
from app.secrets import lab as lab_secrets

app = typer.Typer(
    help='Overlays do laboratório: gerar, listar, validar e remover.',
    no_args_is_help=False,
    add_completion=False,
)
overlay_app = typer.Typer(help='Overlays (inventário + manifests k8s).')
dns_app = typer.Typer(help='Registros DNS esperados pelos overlays.')
secrets_app = typer.Typer(help='Segredos de laboratório dos overlays.')
app.add_typer(overlay_app, name='overlay')
app.add_typer(dns_app, name='dns')
app.add_typer(secrets_app, name='secrets')

RepoRoot = Annotated[
    Path | None,
    typer.Option(
        '--repo-root',
        help='Raiz do repositório (detectada automaticamente).',
        show_default=False,
    ),
]


def _manager(repo_root: Path | None) -> OverlayManager:
    return OverlayManager(repo_root or find_repo_root())


def _fail(message: str) -> typer.Exit:
    typer.secho(f'Erro: {message}', fg=typer.colors.RED, err=True)
    return typer.Exit(code=1)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Sem subcomando abre o menu interativo."""
    if ctx.invoked_subcommand is None:
        tui()


@app.command()
def tui(repo_root: RepoRoot = None) -> None:
    """Menu interativo para montar um overlay."""
    from app.tui.app import run  # noqa: PLC0415 — textual só é carregado aqui

    run(repo_root or find_repo_root())


@app.command()
def catalog(repo_root: RepoRoot = None) -> None:
    """Lista stacks e componentes disponíveis (k8s/catalog.yml)."""
    manager = _manager(repo_root)
    for stack in manager.catalog.stacks.values():
        flag = ' (obrigatória)' if stack.required else ''
        typer.secho(f'{stack.name}{flag} — {stack.label}', bold=True)
        if stack.requires:
            typer.echo(f'    requer: {", ".join(stack.requires)}')
        if not stack.components:
            typer.echo('    (sem componentes)')
        for component in stack.components:
            kind = 'obrigatório' if component.required else 'opcional'
            hosts = ', '.join(host for host, _ in component.hosts)
            extra = f'  hosts: {hosts}' if hosts else ''
            typer.echo(
                f'    {component.ref:38} {kind:12} {component.label}{extra}'
            )


@app.command()
def validate(
    overlay: Annotated[
        str | None,
        typer.Option('--overlay', '-o', help='Valida só este overlay.'),
    ] = None,
    strict: Annotated[
        bool,
        typer.Option(
            '--strict',
            help='Trata SealedSecret ainda não gerado como erro.',
        ),
    ] = False,
    repo_root: RepoRoot = None,
) -> None:
    """Roda `kustomize build` em todos os overlays."""
    root = repo_root or find_repo_root()
    try:
        results = validation.validate(root, overlay)
    except FileNotFoundError as exc:
        raise _fail(str(exc)) from exc
    if not results:
        raise _fail('nenhum overlay encontrado')
    failed = 0
    for result in results:
        bad = result.status == validation.RESULT_ERROR or (
            strict and result.status != validation.RESULT_OK
        )
        failed += bad
        color = (
            typer.colors.RED
            if bad
            else typer.colors.GREEN
            if result.status == validation.RESULT_OK
            else typer.colors.YELLOW
        )
        typer.secho(f'{result.status:14} {result.path}', fg=color)
        if bad and result.detail:
            typer.echo(f'               {result.detail}')
    if failed:
        raise typer.Exit(code=1)


# --- overlay ------------------------------------------------------------------


@overlay_app.command('list')
def overlay_list(repo_root: RepoRoot = None) -> None:
    """Lista os overlays (versionados e locais)."""
    manager = _manager(repo_root)
    for overlay_id, spec in sorted(manager.manifest().overlays.items()):
        vm = spec.primary_vm
        origin = 'local' if spec.local else 'versionado'
        stacks = ','.join(spec.k8s.stacks) if spec.k8s else '-'
        domain = spec.k8s.domain if spec.k8s else '-'
        typer.echo(
            f'{overlay_id:22} {origin:11} {vm.ip:15} {stacks:16} {domain}'
        )


@overlay_app.command('show')
def overlay_show(overlay_id: str, repo_root: RepoRoot = None) -> None:
    """Mostra VM, seleção k8s e URLs de um overlay."""
    manager = _manager(repo_root)
    try:
        spec = manager.manifest().get_overlay(overlay_id)
    except KeyError as exc:
        raise _fail(str(exc).strip('"')) from exc
    typer.secho(f'{spec.overlay_id} — {spec.label}', bold=True)
    typer.echo(f'  origem : {"local" if spec.local else "versionado"}')
    for vm in spec.vms:
        typer.echo(f'  vm     : {vm.name} @ {vm.ip}')
    if spec.k8s is None:
        typer.echo('  k8s    : (sem manifests)')
        return
    selection = manager.selection(spec.k8s.stacks, spec.k8s.disable)
    typer.echo(f'  stacks : {", ".join(selection.stack_names)}')
    typer.echo(f'  tls    : {spec.k8s.tls_issuer}')
    typer.echo(f'  argo   : fonte {spec.k8s.argo_source}')
    typer.echo('  componentes:')
    for component in selection.components:
        typer.echo(f'    - {component.ref}')
    typer.echo('  urls:')
    for host, label in selection.hosts():
        typer.echo(f'    - https://{host}.{spec.k8s.domain}  ({label})')


@overlay_app.command('new')
def overlay_new(  # noqa: PLR0913, PLR0917 — one option per overlay setting
    overlay_id: Annotated[str, typer.Argument(help='Nome do overlay.')],
    base: Annotated[
        str | None,
        typer.Option(
            '--from',
            help='Overlay existente usado como base (stacks e componentes).',
        ),
    ] = None,
    stack: Annotated[
        list[str] | None,
        typer.Option('--stack', '-s', help='Stack a incluir (repetível).'),
    ] = None,
    disable: Annotated[
        list[str] | None,
        typer.Option(
            '--disable',
            help='Componente opcional a deixar de fora (stack/componente).',
        ),
    ] = None,
    ip: Annotated[
        str | None,
        typer.Option('--ip', help='IP estático da VM (padrão: próximo livre).'),
    ] = None,
    vm_name: Annotated[
        str | None,
        typer.Option('--vm-name', help='Nome da VM (padrão: nome do overlay).'),
    ] = None,
    domain: Annotated[
        str | None,
        typer.Option(
            '--domain',
            help='Domínio das apps (padrão: <ip>.sslip.io, sem DNS).',
        ),
    ] = None,
    tls_issuer: Annotated[
        str,
        typer.Option('--tls-issuer', help=f'Um de: {", ".join(TLS_ISSUERS)}.'),
    ] = 'selfsigned',
    vcpus: Annotated[int | None, typer.Option('--vcpus')] = None,
    memory_mb: Annotated[int | None, typer.Option('--memory-mb')] = None,
    disk_gb: Annotated[int | None, typer.Option('--disk-gb')] = None,
    label: Annotated[str | None, typer.Option('--label')] = None,
    repo_root: RepoRoot = None,
) -> None:
    """Cria um overlay local (não versionado) a partir do catálogo."""
    manager = _manager(repo_root)
    stacks: list[str] = list(stack or [])
    disabled: list[str] = list(disable or [])
    if base:
        bases = manager.bases()
        if base not in bases:
            raise _fail(
                f'base desconhecida: {base} ({", ".join(sorted(bases))})'
            )
        base_k8s = bases[base].k8s
        assert base_k8s is not None
        stacks = [*base_k8s.stacks, *stacks]
        disabled = [*base_k8s.disable, *disabled]
    try:
        created = manager.create(
            NewOverlay(
                overlay_id=overlay_id,
                ip=ip or manager.suggest_ip(),
                stacks=tuple(dict.fromkeys(stacks)),
                disable=tuple(dict.fromkeys(disabled)),
                label=label or '',
                vm_name=vm_name or '',
                domain=domain or '',
                tls_issuer=tls_issuer,
                vcpus=vcpus,
                memory_mb=memory_mb,
                disk_size_gb=disk_gb,
            )
        )
    except (OverlayError, FileExistsError) as exc:
        raise _fail(str(exc)) from exc
    spec = created.spec
    assert spec.k8s is not None
    typer.secho(f'Overlay {spec.overlay_id} criado.', fg=typer.colors.GREEN)
    typer.echo(f'  vm      : {spec.primary_vm.name} @ {spec.primary_vm.ip}')
    typer.echo(
        f'  tamanho : {created.size.vcpus} vCPU, {created.size.memory_mb} MB, '
        f'{created.size.disk_size_gb} GB'
    )
    typer.echo(f'  stacks  : {", ".join(spec.k8s.stacks)}')
    typer.echo(f'  domínio : {spec.k8s.domain} (TLS {spec.k8s.tls_issuer})')
    typer.echo(
        f'  arquivos: {len(created.files)} em k8s/**/overlays/{overlay_id}/'
    )
    typer.echo(f'\nPróximo passo: make up OVERLAY={spec.overlay_id}')


@overlay_app.command('render')
def overlay_render(
    overlay_id: str,
    check: Annotated[
        bool,
        typer.Option('--check', help='Só mostra o que difere dos templates.'),
    ] = False,
    repo_root: RepoRoot = None,
) -> None:
    """Regera os arquivos k8s de um overlay a partir dos templates."""
    manager = _manager(repo_root)
    try:
        spec = manager.manifest().get_overlay(overlay_id)
        if check:
            drift = manager.renderer.drift(spec)
            for path in drift:
                typer.echo(f'difere: {path}')
            if drift:
                raise typer.Exit(code=1)
            typer.echo('Sem diferenças.')
            return
        files = manager.render(overlay_id)
    except (OverlayError, KeyError, ValueError) as exc:
        raise _fail(str(exc).strip('"')) from exc
    typer.echo(f'{len(files)} arquivos escritos para {overlay_id}.')


@overlay_app.command('rm')
def overlay_rm(
    overlay_id: str,
    purge_env: Annotated[
        bool,
        typer.Option(
            '--purge-env',
            help='Apaga também env/<overlay> (chave BYOK e segredos do lab).',
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            '--force', help='Remove mesmo com o disco da VM presente.'
        ),
    ] = False,
    yes: Annotated[
        bool, typer.Option('--yes', '-y', help='Não pede confirmação.')
    ] = False,
    repo_root: RepoRoot = None,
) -> None:
    """Remove um overlay local (inventário e manifests k8s)."""
    manager = _manager(repo_root)
    if not yes:
        typer.confirm(f'Remover o overlay local {overlay_id}?', abort=True)
    try:
        removed = manager.remove(overlay_id, purge_env=purge_env, force=force)
    except (OverlayError, KeyError) as exc:
        raise _fail(str(exc).strip('"')) from exc
    for path in removed:
        typer.echo(f'removido: {path}')
    typer.secho(f'Overlay {overlay_id} removido.', fg=typer.colors.GREEN)


# --- secrets ------------------------------------------------------------------


@secrets_app.command('init')
def secrets_init(
    overlay: Annotated[
        str, typer.Option('--overlay', '-o', help='Overlay alvo.')
    ],
    dry_run: Annotated[
        bool, typer.Option('--dry-run', help='Não escreve arquivos.')
    ] = False,
    repo_root: RepoRoot = None,
) -> None:
    """Gera os *-secret.yaml que faltam a partir dos .example do overlay."""
    root = repo_root or find_repo_root()
    labels = {
        lab_secrets.STATUS_GENERATED: 'Written:',
        lab_secrets.STATUS_PRESENT: 'Kept:',
        lab_secrets.STATUS_MANUAL: 'Manual:',
    }
    for item in lab_secrets.init_overlay(root, overlay, dry_run=dry_run):
        typer.echo(f'{labels[item.status]:9} {item.target}')


@secrets_app.command('show')
def secrets_show(
    overlay: Annotated[
        str, typer.Option('--overlay', '-o', help='Overlay alvo.')
    ],
    name: Annotated[
        str | None, typer.Argument(help='Mostra só este valor.')
    ] = None,
    repo_root: RepoRoot = None,
) -> None:
    """Mostra os valores gerados para o overlay (ficam só nesta máquina)."""
    root = repo_root or find_repo_root()
    store = lab_secrets.LabSecretStore(lab_secrets.store_path(root, overlay))
    if not store.values:
        raise _fail(f'nenhum segredo gerado para {overlay}')
    if name is not None:
        if name not in store.values:
            raise _fail(
                f'{name} não existe ({", ".join(sorted(store.values))})'
            )
        typer.echo(store.values[name])
        return
    for key, value in sorted(store.values.items()):
        typer.echo(f'{key}: {value}')


# --- dns ----------------------------------------------------------------------


@dns_app.command('check')
def dns_check(
    overlay: Annotated[
        str | None,
        typer.Option('--overlay', '-o', help='Só este overlay.'),
    ] = None,
    repo_root: RepoRoot = None,
) -> None:
    """Mostra os registros A esperados e quais ainda não resolvem."""
    manager = _manager(repo_root)
    try:
        records = dns_checks.expected_records(
            manager.manifest(),
            manager.catalog,
            [overlay] if overlay else None,
        )
    except KeyError as exc:
        raise _fail(str(exc).strip('"')) from exc
    labels = {
        dns_checks.STATUS_OK: ('ok', typer.colors.GREEN),
        dns_checks.STATUS_AUTO: ('automático', typer.colors.GREEN),
        dns_checks.STATUS_MISSING: ('FALTA', typer.colors.RED),
        dns_checks.STATUS_WRONG: ('ERRADO', typer.colors.RED),
    }
    pending = 0
    for check in dns_checks.check_records(records):
        text, color = labels[check.status]
        record = check.record
        pending += check.status in {
            dns_checks.STATUS_MISSING,
            dns_checks.STATUS_WRONG,
        }
        got = (
            f'  (resolve para {", ".join(check.resolved)})'
            if (check.status == dns_checks.STATUS_WRONG)
            else ''
        )
        typer.secho(
            f'{text:11} A  {record.name:44} {record.ip:15} '
            f'{record.overlay_id}: {record.purpose}{got}',
            fg=color,
        )
    if pending:
        typer.echo(
            f'\n{pending} registro(s) a criar ou corrigir (tipo A, sem proxy).'
        )
        raise typer.Exit(code=1)


def run() -> None:
    app()


if __name__ == '__main__':
    run()
