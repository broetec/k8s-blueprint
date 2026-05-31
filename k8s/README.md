# `k8s/` — manifests Kubernetes

Esta pasta guardará os manifests e configurações Kubernetes do laboratório
(RKE2, CNI, workloads de exemplo, etc.).

Por enquanto o cluster ainda não é provisionado automaticamente por este
repositório. O guia manual de bootstrap está em
[`docs/bootstrap/README.md`](../docs/bootstrap/README.md).

## Próximos passos (futuro)

- Manifests base do cluster (namespaces, RBAC, storage classes)
- Integração com o fluxo `make up` após a fase de provisionamento Ansible
- Kubeconfig local em `env/` (gitignored)

Ver também: [Estrutura do projeto](../docs/structure.md).
