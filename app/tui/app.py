"""Interactive wizard: pick a base, components and VM, then create the overlay.

Purpose
    Keyboard-only terminal UI (works over SSH) on top of
    app.scaffold.overlays.OverlayManager — the same engine used by
    `k8s-blueprint overlay new`.

Steps
    base -> components -> vm -> network -> review -> done

Related
    app/cli.py (k8s-blueprint tui), make tui
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import (
    Button,
    ContentSwitcher,
    Footer,
    Header,
    Input,
    Label,
    RadioButton,
    RadioSet,
    SelectionList,
    Static,
)
from textual.widgets.selection_list import Selection

from app.scaffold.overlays import (
    TLS_ISSUERS,
    CreatedOverlay,
    NewOverlay,
    OverlayError,
    OverlayManager,
    sslip_domain,
)

STEPS = ('base', 'components', 'vm', 'network', 'review', 'done')
TITLES = {
    'base': '1/5  Base — de qual overlay existente partir',
    'components': '2/5  Stacks e componentes opcionais',
    'vm': '3/5  Máquina virtual',
    'network': '4/5  Domínio e TLS',
    'review': '5/5  Revisão',
    'done': 'Overlay criado',
}
_STACK_PREFIX = 'stack:'
_DOMAIN_SSLIP = 'sslip'
_DOMAIN_CUSTOM = 'custom'


class OverlayWizard(App[CreatedOverlay | None]):
    """Wizard that returns the created overlay (or None when cancelled)."""

    TITLE = 'k8s-blueprint'
    SUB_TITLE = 'novo overlay local'

    CSS = """
    #title { padding: 1 2 0 2; text-style: bold; }
    #body { padding: 1 2; height: 1fr; }
    #error { padding: 0 2; color: $error; height: auto; }
    #buttons { height: 3; padding: 0 2; }
    #buttons Button { margin-right: 2; }
    .hint { color: $text-muted; padding-bottom: 1; }
    .field { height: auto; padding-bottom: 1; }
    .field Label { width: 22; padding-top: 1; }
    .field Input { width: 1fr; }
    RadioSet { width: 1fr; margin-bottom: 1; }
    SelectionList { height: auto; max-height: 16; margin-bottom: 1; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding('ctrl+n', 'next', 'Avançar'),
        Binding('ctrl+b', 'back', 'Voltar'),
        Binding('ctrl+q', 'quit', 'Sair'),
    ]

    def __init__(self, manager: OverlayManager) -> None:
        super().__init__()
        self.manager = manager
        self.bases = sorted(manager.bases().items())
        self.step = STEPS[0]
        self.created: CreatedOverlay | None = None

    # -- layout -------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(TITLES[self.step], id='title')
        with ContentSwitcher(initial='base', id='body'):
            yield from self._compose_base()
            yield from self._compose_components()
            yield from self._compose_vm()
            yield from self._compose_network()
            with VerticalScroll(id='review'):
                yield Static(id='summary')
            with VerticalScroll(id='done'):
                yield Static(id='result')
        yield Static(id='error')
        with Horizontal(id='buttons'):
            yield Button('Voltar', id='back', disabled=True)
            yield Button('Avançar', id='next', variant='primary')
            yield Button('Sair', id='quit')
        yield Footer()

    def _compose_base(self) -> ComposeResult:
        with VerticalScroll(id='base'):
            yield Static(
                'O novo overlay herda as stacks e os componentes da base. '
                'Dá para ajustar tudo no passo seguinte.',
                classes='hint',
            )
            with RadioSet(id='base-choice'):
                for index, (overlay_id, spec) in enumerate(self.bases):
                    assert spec.k8s is not None
                    stacks = ', '.join(spec.k8s.stacks)
                    yield RadioButton(
                        f'{overlay_id}  —  {stacks}  ({spec.label})',
                        value=index == 0,
                    )

    @staticmethod
    def _compose_components() -> ComposeResult:
        with VerticalScroll(id='components'):
            yield Static(
                'Espaço marca/desmarca. A stack core e os componentes '
                'obrigatórios entram sempre.',
                classes='hint',
            )
            yield SelectionList[str](id='component-choice')

    @staticmethod
    def _compose_vm() -> ComposeResult:
        with VerticalScroll(id='vm'):
            yield Static(
                'O nome do overlay vale para OVERLAY= no make. O IP é '
                'estático, fora da faixa DHCP da rede do lab.',
                classes='hint',
            )
            for field_id, label, placeholder in (
                ('overlay-id', 'Nome do overlay', 'meu-lab'),
                ('vm-name', 'Nome da VM', 'igual ao overlay'),
                ('ip', 'IP da VM', ''),
                ('vcpus', 'vCPUs', ''),
                ('memory-mb', 'Memória (MB)', ''),
                ('disk-gb', 'Disco (GB)', ''),
            ):
                with Horizontal(classes='field'):
                    yield Label(label)
                    yield Input(placeholder=placeholder, id=field_id)

    @staticmethod
    def _compose_network() -> ComposeResult:
        with VerticalScroll(id='network'):
            yield Static(
                'As aplicações ficam em <app>.<domínio>. Com sslip.io nada '
                'precisa ser criado no DNS; com domínio próprio é preciso um '
                'registro A curinga apontando para o IP da VM.',
                classes='hint',
            )
            with RadioSet(id='domain-mode'):
                yield RadioButton('sslip.io (sem DNS)', value=True)
                yield RadioButton('Domínio próprio')
            with Horizontal(classes='field'):
                yield Label('Domínio')
                yield Input(
                    placeholder='lab.exemplo.com.br',
                    id='domain',
                    disabled=True,
                )
            yield Static('Emissor do certificado do Gateway', classes='hint')
            with RadioSet(id='tls-issuer'):
                for index, issuer in enumerate(TLS_ISSUERS):
                    yield RadioButton(issuer, value=index == 0)

    def on_mount(self) -> None:
        self._fill_components()
        self.query_one('#ip', Input).value = self.manager.suggest_ip()
        self._fill_vm_size()
        self.query_one('#base-choice', RadioSet).focus()

    # -- state --------------------------------------------------------------

    def _base_spec(self):  # noqa: ANN202 — OverlaySpec of the chosen base
        index = self.query_one('#base-choice', RadioSet).pressed_index
        return self.bases[max(index, 0)][1]

    def _fill_components(self) -> None:
        """One entry per optional stack and per optional component."""
        k8s = self._base_spec().k8s
        assert k8s is not None
        choices = self.query_one('#component-choice', SelectionList)
        choices.clear_options()
        for stack in self.manager.catalog.stacks.values():
            if not stack.components:
                continue
            if not stack.required:
                choices.add_option(
                    Selection(
                        f'stack {stack.name} — {stack.label}',
                        f'{_STACK_PREFIX}{stack.name}',
                        stack.name in k8s.stacks,
                    )
                )
            for component in stack.components:
                if component.required:
                    continue
                choices.add_option(
                    Selection(
                        f'    {component.ref} — {component.label}',
                        component.ref,
                        component.ref not in k8s.disable,
                    )
                )

    def _chosen(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """(stacks, disabled components) from the selection list."""
        selected = set(
            self.query_one('#component-choice', SelectionList).selected
        )
        catalog = self.manager.catalog
        stacks = tuple(
            name
            for name, stack in catalog.stacks.items()
            if stack.required or f'{_STACK_PREFIX}{name}' in selected
        )
        disable = tuple(
            component.ref
            for name in stacks
            for component in catalog.stack(name).components
            if not component.required and component.ref not in selected
        )
        return stacks, disable

    def _fill_vm_size(self) -> None:
        stacks, disable = self._chosen()
        try:
            size = self.manager.selection(stacks, disable).vm_size()
        except OverlayError:
            return
        self.query_one('#vcpus', Input).value = str(size.vcpus)
        self.query_one('#memory-mb', Input).value = str(size.memory_mb)
        self.query_one('#disk-gb', Input).value = str(size.disk_size_gb)

    def _value(self, field_id: str) -> str:
        return self.query_one(f'#{field_id}', Input).value.strip()

    def _number(self, field_id: str, label: str) -> int:
        raw = self._value(field_id)
        if not raw.isdigit() or int(raw) <= 0:
            msg = f'{label}: informe um número inteiro maior que zero'
            raise OverlayError(msg)
        return int(raw)

    def _domain_mode(self) -> str:
        index = self.query_one('#domain-mode', RadioSet).pressed_index
        return _DOMAIN_CUSTOM if index == 1 else _DOMAIN_SSLIP

    def request(self) -> NewOverlay:
        """Build the request from the widgets (raises OverlayError)."""
        stacks, disable = self._chosen()
        ip = self._value('ip')
        domain = ''
        if self._domain_mode() == _DOMAIN_CUSTOM:
            domain = self._value('domain')
            if not domain:
                msg = 'Informe o domínio ou escolha sslip.io'
                raise OverlayError(msg)
        issuer_index = self.query_one('#tls-issuer', RadioSet).pressed_index
        return NewOverlay(
            overlay_id=self._value('overlay-id'),
            ip=ip,
            stacks=stacks,
            disable=disable,
            vm_name=self._value('vm-name'),
            domain=domain,
            tls_issuer=TLS_ISSUERS[max(issuer_index, 0)],
            vcpus=self._number('vcpus', 'vCPUs'),
            memory_mb=self._number('memory-mb', 'Memória'),
            disk_size_gb=self._number('disk-gb', 'Disco'),
        )

    def _validate_step(self) -> None:
        """Raise OverlayError when the current step cannot be left."""
        if self.step == 'components':
            self.manager.selection(*self._chosen())
        elif self.step in {'vm', 'network'}:
            self.manager.build_spec(self.request())

    def _summary(self) -> str:
        spec, size = self.manager.build_spec(self.request())
        assert spec.k8s is not None
        selection = self.manager.selection(spec.k8s.stacks, spec.k8s.disable)
        vm = spec.primary_vm
        lines = [
            f'Overlay   : {spec.overlay_id}',
            f'VM        : {vm.name} @ {vm.ip}',
            f'Tamanho   : {size.vcpus} vCPU, {size.memory_mb} MB de RAM, '
            f'{size.disk_size_gb} GB de disco',
            f'Stacks    : {", ".join(selection.stack_names)}',
            f'Domínio   : {spec.k8s.domain}',
            f'TLS       : {spec.k8s.tls_issuer}',
            '',
            'Componentes:',
            *(f'  - {c.ref} ({c.label})' for c in selection.components),
            '',
            'URLs:',
            *(
                f'  - https://{host}.{spec.k8s.domain}  ({label})'
                for host, label in selection.hosts()
            ),
            '',
            'Nada é versionado: os arquivos ficam em '
            f'k8s/**/overlays/{spec.overlay_id}/ e em',
            f'provisioning/inventory/{spec.overlay_id}/ (ignorados pelo git).',
        ]
        if spec.k8s.domain != sslip_domain(vm.ip):
            lines += [
                '',
                f'DNS a criar: A  *.{spec.k8s.domain}  ->  {vm.ip}',
            ]
        return '\n'.join(lines)

    # -- navigation ---------------------------------------------------------

    def _show(self, step: str) -> None:
        self.step = step
        self.query_one('#body', ContentSwitcher).current = step
        self.query_one('#title', Static).update(TITLES[step])
        self.query_one('#error', Static).update('')
        back = self.query_one('#back', Button)
        forward = self.query_one('#next', Button)
        back.disabled = step in {STEPS[0], 'done'}
        forward.label = {'review': 'Gerar overlay', 'done': 'Concluir'}.get(
            step, 'Avançar'
        )
        focus = {
            'base': '#base-choice',
            'components': '#component-choice',
            'vm': '#overlay-id',
            'network': '#domain-mode',
        }.get(step, '#next')
        self.query_one(focus).focus()

    def _error(self, message: str) -> None:
        self.query_one('#error', Static).update(f'Erro: {message}')

    def action_next(self) -> None:
        if self.step == 'done':
            self.exit(self.created)
            return
        try:
            self._validate_step()
            if self.step == 'base':
                self._fill_components()
                self._fill_vm_size()
            elif self.step == 'components':
                self._fill_vm_size()
            elif self.step == 'network':
                self.query_one('#summary', Static).update(self._summary())
            elif self.step == 'review':
                self.created = self.manager.create(self.request())
                self.query_one('#result', Static).update(self._result())
        except (OverlayError, FileExistsError) as exc:
            self._error(str(exc))
            return
        self._show(STEPS[STEPS.index(self.step) + 1])

    def action_back(self) -> None:
        index = STEPS.index(self.step)
        if self.step == 'done' or index == 0:
            return
        self._show(STEPS[index - 1])

    def _result(self) -> str:
        assert self.created is not None
        spec = self.created.spec
        return '\n'.join([
            f'Overlay {spec.overlay_id} criado '
            f'({len(self.created.files)} arquivos k8s).',
            '',
            'Próximos passos:',
            f'  make up OVERLAY={spec.overlay_id}       # VM + RKE2 + Argo CD',
            f'  make k8s-push OVERLAY={spec.overlay_id}   # após editar k8s/',
            f'  uv run k8s-blueprint overlay show {spec.overlay_id}',
        ])

    # -- events -------------------------------------------------------------

    @on(Button.Pressed, '#next')
    def _on_next(self) -> None:
        self.action_next()

    @on(Button.Pressed, '#back')
    def _on_back(self) -> None:
        self.action_back()

    @on(Button.Pressed, '#quit')
    def _on_quit(self) -> None:
        self.exit(self.created)

    @on(Input.Submitted)
    def _on_submit(self) -> None:
        self.action_next()

    @on(RadioSet.Changed, '#domain-mode')
    def _on_domain_mode(self) -> None:
        custom = self._domain_mode() == _DOMAIN_CUSTOM
        self.query_one('#domain', Input).disabled = not custom


def run(repo_root: Path) -> CreatedOverlay | None:
    """Open the wizard; prints the next step when an overlay was created."""
    created = OverlayWizard(OverlayManager(repo_root)).run()
    if created is not None:
        print(f'Overlay {created.spec.overlay_id} criado.')
        print(f'Próximo passo: make up OVERLAY={created.spec.overlay_id}')
    return created
