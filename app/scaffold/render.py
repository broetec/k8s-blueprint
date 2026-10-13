"""Render overlays/_template/ directories into overlays/<id>/.

Purpose
    Turn the Kubernetes selection of an overlay into files: every selected
    component (and the stack-level dirs, e.g. applications) has an
    overlays/_template/ directory rendered with Jinja2.

Inputs
    k8s/catalog.yml, k8s/<stack>/<dir>/overlays/_template/**, OverlaySpec.

Outputs
    Mapping of repo-relative path -> content; written by OverlayRenderer.write.

Notes
    Delimiters are [[ var ]] and [% block %] so templates can hold Helm/Go
    template syntax and `$repoData` untouched. A file that renders empty is
    not written, which lets a template opt out with a top-level [% if %].

Related
    app/scaffold/catalog.py, k8s/README.md
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from app.inventory.models import OverlaySpec
from app.scaffold.catalog import Catalog, Selection

TEMPLATE_DIR = '_template'
K8S_DIR = Path('k8s')


@dataclass(frozen=True)
class RenderContext:
    overlay_id: str
    node_name: str
    vm_ip: str
    apps_domain: str
    iface: str
    tls_issuer: str
    repo_url: str
    revision: str
    stacks: tuple[str, ...]
    components: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            'overlay_id': self.overlay_id,
            'node_name': self.node_name,
            'vm_ip': self.vm_ip,
            'apps_domain': self.apps_domain,
            'iface': self.iface,
            'tls_issuer': self.tls_issuer,
            'repo_url': self.repo_url,
            'revision': self.revision,
            'stacks': list(self.stacks),
            'components': list(self.components),
        }


def _environment() -> Environment:
    return Environment(
        variable_start_string='[[',
        variable_end_string=']]',
        block_start_string='[%',
        block_end_string='%]',
        comment_start_string='[#',
        comment_end_string='#]',
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
    )


class OverlayRenderer:
    def __init__(self, repo_root: Path, catalog: Catalog | None = None) -> None:
        self.repo_root = repo_root.resolve()
        self.catalog = catalog or Catalog.load(self.repo_root)
        self._env = _environment()

    def selection(self, overlay: OverlaySpec) -> Selection:
        if overlay.k8s is None:
            msg = f'Overlay {overlay.overlay_id!r} has no k8s section'
            raise ValueError(msg)
        return self.catalog.select(overlay.k8s.stacks, overlay.k8s.disable)

    def context(self, overlay: OverlaySpec) -> RenderContext:
        selection = self.selection(overlay)
        k8s = overlay.k8s
        assert k8s is not None
        vm = overlay.primary_vm
        return RenderContext(
            overlay_id=overlay.overlay_id,
            node_name=vm.name,
            vm_ip=vm.ip,
            apps_domain=k8s.domain,
            iface=self.catalog.iface,
            tls_issuer=k8s.tls_issuer,
            repo_url=self.catalog.repo_url,
            revision=self.catalog.revision,
            stacks=tuple(selection.stack_names),
            components=tuple(selection.component_refs),
        )

    def template_dirs(self, overlay: OverlaySpec) -> list[Path]:
        """Repo-relative overlays/_template dirs of the selection."""
        selection = self.selection(overlay)
        dirs: list[Path] = []
        for stack in selection.stacks:
            for directory in stack.dirs:
                dirs.append(K8S_DIR / stack.name / directory)
        for component in selection.components:
            for directory in component.dirs:
                dirs.append(K8S_DIR / component.stack / directory)
        result: list[Path] = []
        for directory in dirs:
            template = directory / 'overlays' / TEMPLATE_DIR
            if not (self.repo_root / template).is_dir():
                msg = f'Missing template directory: {template}'
                raise FileNotFoundError(msg)
            result.append(template)
        return result

    def overlay_dirs(self, overlay_id: str) -> list[Path]:
        """Existing repo-relative k8s/**/overlays/<id> directories."""
        root = self.repo_root / K8S_DIR
        return sorted(
            path.relative_to(self.repo_root)
            for path in root.glob(f'**/overlays/{overlay_id}')
            if path.is_dir()
        )

    def render(self, overlay: OverlaySpec) -> dict[Path, str]:
        """Return {repo-relative path: content} for one overlay."""
        context = self.context(overlay).as_dict()
        files: dict[Path, str] = {}
        for template_dir in self.template_dirs(overlay):
            source_root = self.repo_root / template_dir
            target_root = template_dir.parent / overlay.overlay_id
            for source in sorted(source_root.rglob('*')):
                if not source.is_file():
                    continue
                text = source.read_text(encoding='utf-8')
                rendered = self._env.from_string(text).render(context)
                if not rendered.strip():
                    continue
                files[target_root / source.relative_to(source_root)] = rendered
        return files

    def write(self, overlay: OverlaySpec, *, force: bool = False) -> list[Path]:
        """Write rendered files; refuse to touch existing ones unless force."""
        files = self.render(overlay)
        existing = [path for path in files if (self.repo_root / path).exists()]
        if existing and not force:
            msg = (
                f'Overlay {overlay.overlay_id!r} already has files '
                f'(e.g. {existing[0]}); use force to overwrite'
            )
            raise FileExistsError(msg)
        for path, content in files.items():
            target = self.repo_root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8')
        return sorted(files)

    def drift(self, overlay: OverlaySpec) -> list[Path]:
        """Rendered paths whose on-disk content differs (or is missing)."""
        differing: list[Path] = []
        for path, content in self.render(overlay).items():
            target = self.repo_root / path
            if not target.is_file():
                differing.append(path)
            elif target.read_text(encoding='utf-8') != content:
                differing.append(path)
        return sorted(differing)
