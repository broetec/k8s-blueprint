# `env/` — credenciais locais do laboratório

Esta pasta agrupa **defaults e credenciais locais** do laboratório
`k8s-blueprint`. Ficheiros sensíveis ou pessoais são gitignored; versionamos
apenas este `README.md` e `env/.env.example`.

## Defaults do Make (`env/.env`)

```bash
cp env/.env.example env/.env
# edite OVERLAY, VM_IP, CREATE_SSH_GLOBAL_KNOWN_HOSTS, etc.
make help
```

O `Makefile` carrega `env/.env` automaticamente. A linha de comando continua
a poder sobrepor: `make up VM_IP=10.20.30.50`.

| Variável | Uso |
|---|---|
| `OVERLAY`, `VM_NAME`, `VM_IP`, `KVM_NETWORK` | atalhos em vez de flags no `make` |
| `CREATE_SSH_GLOBAL_KNOWN_HOSTS` | `false` (padrão) = só `~/.ssh/known_hosts`; `true` = criar `/etc/ssh/ssh_known_hosts` no controlador (sudo, opt-in) |

## Conteúdo gerado automaticamente

| Arquivo | Origem | Uso |
|---|---|---|
| `k8s-blueprint` | `make keys` / `make up` (1ª execução) | chave **privada** usada pelo Ansible (via `--private-key` e `-e ansible_ssh_private_key_file=...`) e pelo `make ssh` para conectar nas VMs do lab |
| `k8s-blueprint.pub` | mesma origem | chave **pública** injetada no usuário `rocky` da VM via cloud-init (Ansible recebe via `-e ssh_public_key_path=...`) |

A geração é idempotente: se a chave já existe, o Make pula esse passo.

## O que NÃO colocar aqui

- **Inventário Ansible completo** (roles, group_vars versionados) →
  `provisioning/inventory/<overlay>/`. O `env/.env` só substitui defaults do
  `Makefile` (IP, overlay, flags). Para outro ambiente, copie
  `inventory/example` → `inventory/<nome>` e use `OVERLAY=<nome>` no `.env` ou
  no `make`.
- **Segredos de produção** (tokens de cloud, deploy keys do GitHub, etc.) →
  use `sealed-secrets` / `external-secrets` na fase declarativa do cluster
  (ver `docs/`). Esta pasta é só para o ciclo de vida do lab local.

## Como zerar as credenciais

```bash
make clean   # remove a VM, a rede libvirt, o cache da qcow2 e a chave do lab
```

Depois disso, o próximo `make up` gera uma chave nova e provisiona do zero.
