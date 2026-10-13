"""Build every overlay with kustomize to catch broken manifests early.

Purpose
    `kustomize build` each k8s/**/overlays/<id> directory (templates excluded)
    and report the ones that fail.

Notes
    SealedSecrets are generated per machine (BYOK key), so an overlay that
    lists a *-sealedsecret.yaml only builds after sealing; such failures are
    reported as "needs sealing" instead of errors unless strict.

Related
    app/cli.py (k8s-blueprint validate)
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.scaffold.render import K8S_DIR, TEMPLATE_DIR

RESULT_OK = 'ok'
RESULT_UNSEALED = 'needs-sealing'
RESULT_ERROR = 'error'


@dataclass(frozen=True)
class BuildResult:
    path: Path
    status: str
    detail: str = ''


def kustomize_command() -> list[str]:
    if shutil.which('kustomize'):
        return ['kustomize', 'build']
    if shutil.which('kubectl'):
        return ['kubectl', 'kustomize']
    msg = 'kustomize (or kubectl) not found in PATH'
    raise FileNotFoundError(msg)


def overlay_dirs(repo_root: Path, overlay_id: str | None = None) -> list[Path]:
    """Repo-relative overlay directories that hold a kustomization.yaml."""
    root = repo_root / K8S_DIR
    pattern = f'**/overlays/{overlay_id or "*"}/kustomization.yaml'
    return sorted(
        path.parent.relative_to(repo_root)
        for path in root.glob(pattern)
        if path.parent.name != TEMPLATE_DIR
    )


def build(repo_root: Path, directory: Path) -> BuildResult:
    proc = subprocess.run(
        [*kustomize_command(), str(repo_root / directory)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        return BuildResult(path=directory, status=RESULT_OK)
    detail = proc.stderr.strip().splitlines()[-1] if proc.stderr else ''
    if 'sealedsecret.yaml' in proc.stderr and 'no such file' in proc.stderr:
        return BuildResult(directory, RESULT_UNSEALED, detail)
    return BuildResult(directory, RESULT_ERROR, detail)


def validate(
    repo_root: Path, overlay_id: str | None = None
) -> list[BuildResult]:
    return [
        build(repo_root, path) for path in overlay_dirs(repo_root, overlay_id)
    ]
