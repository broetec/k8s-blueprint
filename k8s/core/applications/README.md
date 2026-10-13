# Applications do Argo CD — stack core

Manifests do *app-of-apps* da stack `core`: o `AppProject`, a `Application` raiz
(`core-apps`) e uma `Application` por componente.

## Layout

| Diretório | Função |
|-----------|--------|
| `base/` | `Application`, `AppProject` e o ConfigMap `core-release-source` (`repoURL` + `targetRevision` do Git). Caminhos de overlay ficam como `PLACEHOLDER`. |
| `overlays/_template/` | Molde do overlay, renderizado por `k8s-blueprint` (ver [`app/scaffold`](../../../app/scaffold/README.md)). |
| `overlays/<id>/` | Um por overlay: inclui `../../base`, aplica os *patches* de caminho (`…/overlays/<id>`) e os `replacements` que propagam a origem Git. |

## Applications

| Application | Fonte | Onda |
|-------------|-------|------|
| `core-apps` | Git: `k8s/core/applications/overlays/<id>` (raiz) | 0 |
| `cluster-config` | Git: `k8s/core/cluster-config/overlays/<id>` | -5 |
| `local-path-provisioner` | Helm (chart no Git do projeto) + values + Kustomize | -4 |
| `sealed-secrets` | Helm + values | -3 |
| `cert-manager` | Helm + values + Kustomize (ClusterIssuers) | -2 |
| `external-secrets-operator` | Helm + values + Kustomize (opcional) | -2 |
| `argocd` | Helm + values + Kustomize (SealedSecret da senha admin) | -1 |
| `storage-apps` | Git: `k8s/storage/applications/overlays/<id>` (só com a stack storage) | 1 |

Nas Applications Helm a ordem das fontes é fixa — Helm (0), `repoData` (1),
Kustomize (2) — porque os `replacements` do overlay escrevem em
`spec.sources.1` e `spec.sources.2`.

## Origem dos manifests

`overlays/<id>/_release-source.yaml` define `repoURL` e `targetRevision` do
ConfigMap `core-release-source`; os `replacements` copiam os dois valores para
as fontes Git de cada Application e para `AppProject.spec.sourceRepos[0]`.

- Versionado: `https://github.com/broetec/k8s-blueprint.git` / `main`.
- No lab: o role `04_deploy_k8s` reescreve esse arquivo **na cópia da VM** para
  `git@<ip da VM>:k8s-blueprint.git` (ver
  [`04_deploy_k8s`](../../../provisioning/roles/04_deploy_k8s/README.md)).

## Outras stacks

Uma stack adicional entra como recurso do overlay do core:
`../../../../storage/applications/root` traz o `AppProject storage` e a
Application `storage-apps`, que por sua vez lê
`k8s/storage/applications/overlays/<id>`.

## Bootstrap manual

```bash
kubectl apply -k k8s/core/applications/overlays/<id>
kubectl -n argocd get applications
```
