"""Catalog of stacks and components available to build an overlay.

Purpose
    Parse k8s/catalog.yml and resolve which components an overlay selects
    (stacks minus disabled optional components), validating dependencies.

Inputs
    k8s/catalog.yml.

Outputs
    Catalog / Selection dataclasses used by app.scaffold.render.

Related
    k8s/README.md, app/scaffold/render.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CATALOG_FILE = Path('k8s/catalog.yml')


@dataclass(frozen=True)
class VmSize:
    vcpus: int = 4
    memory_mb: int = 8192
    disk_size_gb: int = 60

    def merge_max(self, other: VmSize) -> VmSize:
        return VmSize(
            vcpus=max(self.vcpus, other.vcpus),
            memory_mb=max(self.memory_mb, other.memory_mb),
            disk_size_gb=max(self.disk_size_gb, other.disk_size_gb),
        )


@dataclass(frozen=True)
class Component:
    stack: str
    name: str
    label: str
    required: bool = False
    requires: tuple[str, ...] = ()
    dirs: tuple[str, ...] = ()
    hosts: tuple[tuple[str, str], ...] = ()

    @property
    def ref(self) -> str:
        return f'{self.stack}/{self.name}'


@dataclass(frozen=True)
class Stack:
    name: str
    label: str
    required: bool = False
    requires: tuple[str, ...] = ()
    dirs: tuple[str, ...] = ()
    vm: VmSize | None = None
    components: tuple[Component, ...] = ()

    def component(self, name: str) -> Component:
        for component in self.components:
            if component.name == name:
                return component
        msg = f'Unknown component: {self.name}/{name}'
        raise KeyError(msg)


@dataclass(frozen=True)
class Selection:
    """Stacks and components chosen for one overlay."""

    stacks: tuple[Stack, ...]
    components: tuple[Component, ...]

    @property
    def stack_names(self) -> list[str]:
        return [stack.name for stack in self.stacks]

    @property
    def component_refs(self) -> list[str]:
        return [component.ref for component in self.components]

    def hosts(self) -> list[tuple[str, str]]:
        """(host, label) pairs exposed by the selected components."""
        return [
            pair for component in self.components for pair in component.hosts
        ]

    def vm_size(self) -> VmSize:
        size = VmSize()
        for stack in self.stacks:
            if stack.vm is not None:
                size = size.merge_max(stack.vm)
        return size


@dataclass
class Catalog:
    repo_url: str
    revision: str
    iface: str
    stacks: dict[str, Stack] = field(default_factory=dict)

    @classmethod
    def load(cls, repo_root: Path) -> Catalog:
        path = repo_root / CATALOG_FILE
        raw = yaml.safe_load(path.read_text(encoding='utf-8'))
        if not isinstance(raw, dict):
            msg = f'Invalid catalog: {path}'
            raise ValueError(msg)
        repo = raw.get('repo') or {}
        defaults = raw.get('defaults') or {}
        stacks = {
            name: _parse_stack(name, data or {})
            for name, data in (raw.get('stacks') or {}).items()
        }
        if not stacks:
            msg = f'Catalog has no stacks: {path}'
            raise ValueError(msg)
        return cls(
            repo_url=str(repo['url']),
            revision=str(repo.get('revision', 'main')),
            iface=str(defaults.get('iface', 'enp1s0')),
            stacks=stacks,
        )

    def stack(self, name: str) -> Stack:
        try:
            return self.stacks[name]
        except KeyError as exc:
            msg = f'Unknown stack: {name!r}. Available: {sorted(self.stacks)}'
            raise KeyError(msg) from exc

    def component(self, ref: str) -> Component:
        stack_name, _, name = ref.partition('/')
        if not name:
            msg = f'Invalid component reference (want stack/name): {ref!r}'
            raise KeyError(msg)
        return self.stack(stack_name).component(name)

    def required_stacks(self) -> list[str]:
        return [name for name, stack in self.stacks.items() if stack.required]

    def select(
        self,
        stacks: tuple[str, ...] | list[str],
        disable: tuple[str, ...] | list[str] = (),
    ) -> Selection:
        """Resolve stacks minus disabled components, checking dependencies."""
        names = list(dict.fromkeys([*self.required_stacks(), *stacks]))
        disabled = set(disable)
        for ref in disabled:
            component = self.component(ref)
            if component.stack not in names:
                msg = f'Cannot disable {ref}: stack not selected'
                raise ValueError(msg)
            if component.required:
                msg = f'Component {ref} is required and cannot be disabled'
                raise ValueError(msg)
        chosen_stacks = tuple(self.stack(name) for name in names)
        components = tuple(
            component
            for stack in chosen_stacks
            for component in stack.components
            if component.ref not in disabled
        )
        selection = Selection(stacks=chosen_stacks, components=components)
        self._check_requires(selection)
        return selection

    def _check_requires(self, selection: Selection) -> None:
        present = set(selection.component_refs)
        for stack in selection.stacks:
            for ref in stack.requires:
                self.component(ref)
                if ref not in present:
                    msg = f'Stack {stack.name} requires component {ref}'
                    raise ValueError(msg)
        for component in selection.components:
            for ref in component.requires:
                self.component(ref)
                if ref not in present:
                    msg = f'Component {component.ref} requires {ref}'
                    raise ValueError(msg)


def _parse_vm(data: Any) -> VmSize | None:
    if not data:
        return None
    base = VmSize()
    return VmSize(
        vcpus=int(data.get('vcpus', base.vcpus)),
        memory_mb=int(data.get('memory_mb', base.memory_mb)),
        disk_size_gb=int(data.get('disk_size_gb', base.disk_size_gb)),
    )


def _parse_stack(name: str, data: dict[str, Any]) -> Stack:
    components = tuple(
        Component(
            stack=name,
            name=component_name,
            label=str((spec or {}).get('label', component_name)),
            required=bool((spec or {}).get('required', False)),
            requires=tuple((spec or {}).get('requires') or ()),
            dirs=tuple((spec or {}).get('dirs') or ()),
            hosts=tuple(((spec or {}).get('hosts') or {}).items()),
        )
        for component_name, spec in (data.get('components') or {}).items()
    )
    return Stack(
        name=name,
        label=str(data.get('label', name)),
        required=bool(data.get('required', False)),
        requires=tuple(data.get('requires') or ()),
        dirs=tuple(data.get('dirs') or ()),
        vm=_parse_vm(data.get('vm')),
        components=components,
    )
