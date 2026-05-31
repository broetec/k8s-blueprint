# `env/` — credenciais locais do laboratório

> Mapa geral do repositório: [`docs/structure.md`](../docs/structure.md)

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
| `OVERLAY` | overlay ativo (`broetec-core`, `broetec-storage`, …) |
| `VM_NAME`, `VM_IP` | sobrescrevem a VM do overlay ao gerar `hosts.ini` (`make inventory`) |
| `KVM_NETWORK` | rede libvirt no `make clean` |
| `KVM_HOST_BOOTSTRAP` | `true` (padrão): instala pacotes libvirt no host (`make setup-host` / `install-kvm`); `false`: só rede + firewalld |
| `LAB_PATH` | raiz de `lab/` (discos + cache qcow2; ver `lab/README.md`) |
| `CREATE_SSH_GLOBAL_KNOWN_HOSTS` | `false` (padrão) = só `~/.ssh/known_hosts`; `true` = criar `/etc/ssh/ssh_known_hosts` no controlador (sudo, opt-in) |

## Conteúdo gerado automaticamente

| Arquivo | Origem | Uso |
|---|---|---|
| `k8s-blueprint` | `make keys` / `make up` (1ª execução) | chave **privada** usada pelo Ansible (via `--private-key` e `-e ansible_ssh_private_key_file=...`) e pelo `make ssh` para conectar nas VMs do lab |
| `k8s-blueprint.pub` | mesma origem | chave **pública** injetada no usuário `rocky` da VM via cloud-init (Ansible recebe via `-e ssh_public_key_path=...`) |

A geração é idempotente: se a chave já existe, o Make pula esse passo.

## O que NÃO colocar aqui

- **Topologia de VMs** → edite `provisioning/inventory/manifest.yml` e corra
  `make inventory`. O `env/.env` só sobrescreve o overlay ativo (`OVERLAY`,
  opcionalmente `VM_NAME` / `VM_IP`). Variáveis Ansible partilhadas:
  `provisioning/inventory/_shared/group_vars/`.
- **Segredos de produção** (tokens de cloud, deploy keys do GitHub, etc.) →
  use `sealed-secrets` / `external-secrets` na fase declarativa do cluster
  (ver `docs/`). Esta pasta é só para o ciclo de vida do lab local.

## Como zerar as credenciais

```bash
make clean   # remove a VM, a rede libvirt, lab/ (discos+cache) e a chave do lab
```

Para apagar **tudo** do lab (incluindo a qcow2 baixada), remova `lab/cache` e
`lab/disks` ou o clone inteiro do repositório. Depois disso, o próximo
`make up` gera uma chave nova e provisiona do zero.
