# k8s-blueprint — documentação

Laboratório Broetec para estudar Ansible, KVM/libvirt e Kubernetes.

## Começar

- [Estrutura do projeto](structure.md) — mapa de pastas, fluxo `make up`, o que é versionado

## Provisionamento

- [Provisionamento Ansible](../provisioning/README.md) — playbook, roles, pré-requisitos
- [Inventário](../provisioning/inventory/README.md) — overlays, manifest.yml, variáveis
- [Ambiente local (env/)](../env/README.md) — chaves SSH, `.env` do Make
- [Artefactos do lab (lab/)](../lab/README.md) — discos qcow2 e cache

## Kubernetes

- [Manifests k8s](../k8s/README.md) — pasta reservada para manifests (futuro)
- [Bootstrap RKE2](bootstrap/README.md) — guia manual de instalação do cluster
- [Fine-tuning](fine-tuning/README.md)
- [Upgrade](upgrade/README.md)
