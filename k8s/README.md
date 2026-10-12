# `k8s/` — manifests Kubernetes

Esta pasta guarda os values Helm e os overlays kustomize do bootstrap do cluster
(Cilium/Gateway API, PriorityClasses, local-path, cert-manager, Argo CD,
Sealed Secrets).

São aplicados pela role Ansible
[`04_deploy_k8s`](../provisioning/roles/04_deploy_k8s/), depois de o RKE2 ser
instalado pela role [`03_install_rke2`](../provisioning/roles/03_install_rke2/).

Bootstrap guide: [`04_deploy_k8s`](../provisioning/roles/04_deploy_k8s/README.md).

## Integração Make

- `make up` — inclui 03 + 04 após provisionamento da VM
- `make deploy` — só 03 + 04 (actualizar k8s sem recriar VM)
- `make deploy-k8s` — só 04

Ver também: [Estrutura do projeto](../docs/structure.md).
