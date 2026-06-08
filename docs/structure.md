# Estrutura do projeto

Mapa de pastas do **k8s-blueprint** — laboratório de estudo para Ansible,
KVM/libvirt e Kubernetes.

← [Índice da documentação](index.md)

---

## Visão geral

```text
k8s-blueprint/
├── README.md                 # Entrada: quick start
├── Makefile                  # Orquestrador (includes em make/)
├── make/                     # Makefile includes — see make/README.md
│   ├── README.md
│   ├── config.mk
│   ├── ansible.mk
│   └── ssh.mk
├── pyproject.toml            # Dependências Python (Ansible via uv)
│
├── app/                      # App Python
├── tests/                    # Testes do app/
│
├── provisioning/             # Todo o Ansible
│   ├── ansible.cfg
│   ├── site.yml
│   ├── collections/
│   ├── inventory/
│   ├── roles/
│   │   ├── 00_install_kvm/
│   │   ├── 01_create_vm/
│   │   ├── 02_prepare_vm/
│   │   ├── 03_install_rke2/  # stub
│   │   └── 04_deploy_k8s/    # stub
│   └── templates/
│
├── lab/                      # Artefactos locais KVM (conteúdo gitignored)
├── env/                      # Credenciais e .env local
├── k8s/                      # Manifests Kubernetes (futuro)
└── docs/                     # Documentação (futuro Sphinx)
```

---

## app

App Python do projeto. Hoje contém o **gerador de inventário Ansible**
(`app/inventory/`), invocado por `make inventory` via o script
`k8s-blueprint-inventory`.

| Conteúdo | Versionado |
|----------|------------|
| Código Python (`app/`) | Sim |
| `.venv/` | Não (gitignored; criado por `make sync`) |

**Futuro:** configs personalizadas do lab (topologia, overlays, parâmetros de VM)
geradas por CLI ou UI Python.

---

## make

Orquestração **Make** na raiz do repo: targets (`up`, `setup-host`, …),
defaults (`env/.env`), invocação Ansible e utilitários SSH/libvirt.

| Path | Purpose |
|------|---------|
| [make/README.md](../make/README.md) | Hub — targets, pipeline, configuration, troubleshooting |
| `config.mk` | Defaults, overlay paths, become flags, `ANSIBLE_FRONT` |
| `ansible.mk` | `run-playbook` macro, `setup-host` tag logic |
| `ssh.mk` | SSH known_hosts, `make ssh`, `destroy`, `clean` |

---

## provisioning

All **Ansible** configuration for the lab.

| Path | Purpose |
|------|---------|
| [provisioning/README.md](../provisioning/README.md) | Hub — prerequisites, `make up`, SSH, doc map |
| `ansible.cfg` | Timeouts, SSH, libssh (terminal stability) |
| `site.yml` | Master playbook — 5 plays (00–04) |
| [inventory/README.md](../provisioning/inventory/README.md) | `manifest.yml`, overlays `broetec-*`, group_vars |
| [app/inventory/README.md](../app/inventory/README.md) | `make inventory` generator (Python) |
| [roles/00_install_kvm/](../provisioning/roles/00_install_kvm/README.md) | Host bootstrap, libvirt network, firewall (opt-in) |
| [roles/01_create_vm/](../provisioning/roles/01_create_vm/README.md) | qcow2, cloud-init, virt-install |
| [roles/02_prepare_vm/](../provisioning/roles/02_prepare_vm/README.md) | swap, SELinux, firewalld in VM |
| [roles/03_install_rke2/](../provisioning/roles/03_install_rke2/README.md) | RKE2 (stub) |
| [roles/04_deploy_k8s/](../provisioning/roles/04_deploy_k8s/README.md) | k8s manifests (stub) |
| [templates/README.md](../provisioning/templates/README.md) | NoCloud seed ISO templates |
| [collections/README.md](../provisioning/collections/README.md) | Galaxy collections (`ansible.posix`, `ansible.netcommon`) |

**Nota:** o grupo de inventário `[kvm_hosts]` e variáveis como
`kvm_host_bootstrap` mantêm nomes técnicos Ansible; só as **pastas das roles**
usam a nomenclatura numerada.

---

## lab

Artefactos **gerados no disco** pelo `make up`. Descartáveis com `make clean`.

| Subpasta | Conteúdo | Versionado |
|----------|----------|------------|
| `disks/` | Discos qcow2 das VMs, seed ISOs cloud-init | Não |
| `cache/` | Imagem base Rocky Linux (download único) | Não |
| `README.md` | Documentação da pasta | Sim |

Documentação: [lab/README.md](../lab/README.md).

---

## env

Defaults e **credenciais locais** do laboratório.

| Ficheiro | Versionado | Função |
|----------|------------|--------|
| `.env.example` | Sim | Template de variáveis do Make |
| `README.md` | Sim | Documentação |
| `.env` | Não | Defaults locais (`OVERLAY`, `VM_IP`, …) |
| `k8s-blueprint` / `.pub` | Não | Chave SSH do lab (gerada por `make keys` / `make up`) |
| `become.pass` / `vm-become.pass` | Não | Passwords sudo opcionais |

Documentação: [env/README.md](../env/README.md).

---

## k8s

Reservado para **manifests Kubernetes** (RKE2, CNI, workloads). Ainda não
integrado no fluxo automatizado do `make up`.

Documentação: [k8s/README.md](../k8s/README.md) · guia manual:
[bootstrap/README.md](bootstrap/README.md).

---

## docs

Fonte da documentação do projeto, preparada para migração futura para
**Sphinx** (`docs/_build/` já está no `.gitignore`).

| Conteúdo | Descrição |
|----------|-----------|
| `index.md` | Índice / toctree |
| `structure.md` | Este ficheiro |
| `bootstrap/`, `fine-tuning/`, `upgrade/` | Guias Kubernetes |

---

## tests

Testes unitários do app Python (`pytest`). Correr com:

```bash
uv run pytest
```

---

## Fluxo `make up`

```mermaid
sequenceDiagram
  participant User
  participant Make as Makefile
  participant Ansible
  participant Host as Host_KVM
  participant VM as VM_Rocky

  User->>Make: make setup-host
  Make->>Ansible: 00 install_kvm
  Ansible->>Host: 00_install_kvm

  User->>Make: make up
  Make->>Ansible: 01 create_vm
  Ansible->>Host: 01_create_vm
  Make->>Ansible: 02 prepare_vm
  Ansible->>VM: 02_prepare_vm
  Make->>Ansible: 03 install_rke2
  Ansible->>VM: 03_install_rke2 stub
  Make->>Ansible: 04 deploy_k8s
  Ansible->>VM: 04_deploy_k8s stub
```

### Targets Make

| Target | Etapas |
|--------|--------|
| `setup-host` | `setup` + 00 (controlador + host KVM; bootstrap via `env/.env`) |
| `up` | 01 + 02 + 03 + 04 (default `OVERLAY=broetec-core`) |
| `up-all` | loop `up` nos 3 overlays |
| `deploy` | 03 + 04 |
### Ordem das roles

1. **00_install_kvm** — host (`kvm_hosts`): pacotes KVM, rede, firewall (opt-in)
2. **01_create_vm** — host: qcow2, virt-install, wait SSH
3. **02_prepare_vm** — VM: swap, SELinux, firewalld
4. **03_install_rke2** — VM: RKE2 (stub)
5. **04_deploy_k8s** — VM: manifests (stub)

---

## Onde customizar

| Objetivo | Onde editar |
|----------|-------------|
| Topologia de VMs (nome, IP, overlay) | `provisioning/inventory/manifest.yml` → `make inventory` |
| Sobrescrever overlay ativo | `env/.env` (`OVERLAY`, `VM_NAME`, `VM_IP`) |
| Variáveis Ansible partilhadas | `provisioning/inventory/_shared/group_vars/` |
| Caminho dos discos | `env/.env` (`LAB_PATH`) ou `group_vars/all.yml` |
| Pular instalação de pacotes no host | `env/.env` → `KVM_HOST_BOOTSTRAP=false` (ou `make setup-host KVM_HOST_BOOTSTRAP=false`) |
| Regras NAT/FORWARD no host (Docker + firewall) | `env/.env` → `KVM_HOST_FIREWALL=true` (ou `make setup-host KVM_HOST_FIREWALL=true`) |
| Host sem sudo no dia-a-dia | Bootstrap uma vez → re-login → grupos `libvirt` + `kvm`; ver [`00_install_kvm`](../provisioning/roles/00_install_kvm/README.md) |

---

## Versionado vs gitignored

| Versionado | Gitignored (gerado/local) |
|------------|---------------------------|
| Código, playbooks, inventário base | `.venv/`, `lab/disks/`, `lab/cache/` |
| `env/.env.example`, `env/README.md` | `env/.env`, chaves SSH |
| Overlays `broetec-*` no inventário | `kubeconfig*`, `.ansible/` |

Ver [.gitignore](../.gitignore) para a lista completa.
