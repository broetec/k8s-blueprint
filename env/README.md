# `env/` — credenciais locais do laboratório

Esta pasta guarda **credenciais geradas localmente** para o ambiente de
laboratório do `k8s-blueprint`. Tudo aqui (exceto este `README.md`) é
gitignored — cada clone do repositório gera e usa as suas próprias
credenciais; nada de chave compartilhada no git.

## Conteúdo gerado automaticamente

| Arquivo | Origem | Uso |
|---|---|---|
| `k8s-blueprint` | `make keys` / `make up` (1ª execução) | chave **privada** usada pelo Ansible (via `--private-key` e `-e ansible_ssh_private_key_file=...`) e pelo `make ssh` para conectar nas VMs do lab |
| `k8s-blueprint.pub` | mesma origem | chave **pública** injetada no usuário `rocky` da VM via cloud-init (Ansible recebe via `-e ssh_public_key_path=...`) |

A geração é idempotente: se a chave já existe, o Make pula esse passo.

## O que NÃO colocar aqui

- **Configuração por ambiente** (VM name, IP, subrede, vCPUs) → fica em
  `provisioning/inventory/<overlay>/group_vars/all.yml` e `hosts.ini`.
  Para criar um novo ambiente, copie a pasta `inventory/example` para
  `inventory/<seu-nome>` e rode `make up OVERLAY=<seu-nome>`.
- **Segredos de produção** (tokens de cloud, deploy keys do GitHub, etc.) →
  use `sealed-secrets` / `external-secrets` na fase declarativa do cluster
  (ver `docs/`). Esta pasta é só para o ciclo de vida do lab local.

## Como zerar as credenciais

```bash
make clean   # remove a VM, a rede libvirt, o cache da qcow2 e a chave do lab
```

Depois disso, o próximo `make up` gera uma chave nova e provisiona do zero.
