# Stack `monitor`

Catálogo ainda vazio: a stack existe em [`../catalog.yml`](../catalog.yml) sem
componentes, e o overlay `broetec-monitor` sobe apenas com a stack `core`.

Para acrescentar monitoração, siga o mesmo padrão de [`../storage/`](../storage/):

1. `applications/{base,root,overlays/_template}` com o `AppProject`, a
   Application raiz (`monitor-apps`) e uma Application por componente.
2. Um diretório por componente com `base/` e `overlays/_template/`.
3. Componentes, dependências e hosts declarados no catálogo.
4. No template `k8s/core/applications/overlays/_template/kustomization.yaml`,
   incluir `../../../../monitor/applications/root` quando `'monitor' in stacks`
   (como já é feito para `storage`).

Passo a passo em [`app/scaffold/README.md`](../../app/scaffold/README.md).
