# `k8s/` — manifests Kubernetes

Esta pasta guardará os manifests e configurações Kubernetes do laboratório
(RKE2, CNI, workloads de exemplo, etc.).

Por enquanto os manifests serão aplicados pela role Ansible
[`04_deploy_k8s`](../provisioning/roles/04_deploy_k8s/) (stub). O RKE2 será
instalado pela role [`03_install_rke2`](../provisioning/roles/03_install_rke2/)
(stub).

Guia manual: [`docs/bootstrap/README.md`](../docs/bootstrap/README.md).

## Integração Make

- `make up` — inclui 03 + 04 após provisionamento da VM
- `make deploy` — só 03 + 04 (actualizar k8s sem recriar VM)
- `make deploy-k8s` — só 04

Ver também: [Estrutura do projeto](../docs/structure.md).
