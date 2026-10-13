# Estrutura do projeto

Mapa de pastas do **k8s-blueprint** — laboratório de estudo para Ansible,
KVM/libvirt e Kubernetes.

← [Índice da documentação](index.md)

---

## Visão geral

```text
k8s-blueprint/
├── README.md                 # Entrada: quick start
├── Makefile                  # Entry point — help + includes (make/*.mk)
├── make/                     # Makefile modules — see make/README.md
│   ├── README.md
│   ├── config.mk
│   ├── colors.mk
│   ├── ansible.mk
│   ├── setup.mk
│   ├── inventory.mk
│   ├── targets.mk
│   ├── overlays.mk
│   └── ssh.mk
├── pyproject.toml            # Dependências Python (Ansible via uv)
│
├── app/                      # App Python (inventário, overlays, menu, sealed secrets)
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
│   │   ├── 03_install_rke2/  # RKE2 (ou 03_install_k3s/)
│   │   ├── 04_deploy_k8s/    # bootstrap k8s + entrega ao Argo CD (app-of-apps)
│   │   ├── reset_k8s/        # teardown dos workloads (opt-in)
│   │   └── golden_image/     # imagem base com SO preparado (opt-in)
│   └── templates/
│
├── lab/                      # Artefactos locais KVM (conteúdo gitignored)
├── env/                      # Credenciais e .env local
├── k8s/                      # Manifests Kubernetes por stack (core, storage)
│   ├── catalog.yml           #   stacks e componentes disponíveis
│   ├── core/                 #   applications/ + componentes base/overlays
│   └── storage/
└── docs/                     # Documentação (Sphinx)
```

---

## app

App Python do projeto.

| Pacote | Função | Comando |
|--------|--------|---------|
| `app/inventory/` | Gera `hosts.ini` e `group_vars` a partir de `manifest.yml` (+ `manifest.local.yml`) | `k8s-blueprint-inventory`, `make inventory` |
| `app/scaffold/` | Catálogo (`k8s/catalog.yml`), render dos `overlays/_template/`, criação/remoção de overlays locais, checagem de DNS, validação com kustomize | `k8s-blueprint`, `make new`, `make dns-check`, `make validate-k8s` |
| `app/tui/` | Menu interativo (Textual) sobre a mesma engine | `k8s-blueprint tui`, `make tui` |
| `app/secrets/` | Chave BYOK e selamento offline de Secrets; segredos de laboratório | `k8s-blueprint-seal`, `k8s-blueprint secrets` |

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
| `colors.mk` | ANSI colours for help and status messages |
| `setup.mk` | `sync`, `deps`, `keys`, `setup` |
| `inventory.mk` | `inventory`, `inventory-overlay` |
| `targets.mk` | Playbook pipeline (`setup-host`, `up`, …) |
| `ansible.mk` | `run-playbook` macro, `setup-host` tag logic |
| `ssh.mk` | SSH known_hosts, `make ssh`, `destroy`, `destroy-all`, `clean` |

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
| [roles/02_prepare_vm/](../provisioning/roles/02_prepare_vm/README.md) | swap, SELinux, iptables baseline in VM |
| [roles/03_install_rke2/](../provisioning/roles/03_install_rke2/README.md) | RKE2 server, Cilium, Gateway API |
| [roles/04_deploy_k8s/](../provisioning/roles/04_deploy_k8s/README.md) | cluster-config, local-path, Argo CD, Git local, Application raiz |
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

Manifests Kubernetes organizados por **stack** (`core`, `storage`), cada uma
com `applications/{base,overlays/<id>}` (Applications do Argo CD) e
componentes `base/` + `overlays/<id>/`. O role 04 faz o bootstrap mínimo e
aplica a Application raiz do overlay; o Argo CD instala o restante lendo um
Git servido pela própria VM.

| Conteúdo | Versionado |
|----------|------------|
| `catalog.yml`, `base/`, `overlays/_template/`, `overlays/broetec-*/` | Sim |
| `overlays/<overlay local>/` (criados por `k8s-blueprint overlay new`) | Não |
| `*-sealedsecret.yaml` (selados com a chave BYOK da máquina) | Não |

Documentação: [k8s/README.md](../k8s/README.md) · bootstrap:
[04_deploy_k8s/README.md](../provisioning/roles/04_deploy_k8s/README.md).

---

## docs

Fonte da documentação do projeto, preparada para migração futura para
**Sphinx** (`docs/_build/` já está no `.gitignore`).

| Conteúdo | Descrição |
|----------|-----------|
| `index.md` | Índice / toctree |
| `structure.md` | Este ficheiro |
| `upgrade/` | Guia de upgrade Kubernetes |

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
  Ansible->>VM: 03_install_rke2
  Make->>Ansible: 04 deploy_k8s
  Ansible->>VM: 04_deploy_k8s
```

### Targets Make

| Target | Etapas |
|--------|--------|
| `setup-host` | `setup` + 00 (controlador + host KVM; bootstrap via `env/.env`) |
| `up` | 01 + 02 + 03 + 04 (default `OVERLAY=broetec-core`) |
| `up-all` | loop `up` nos 3 overlays |
| `deploy` | 03 + 04 |
| `k8s-push` | Reenvia `k8s/` ao Git local da VM e pede refresh ao Argo CD |
| `tui` / `new` / `rm-overlay` | Cria ou remove um overlay local (não versionado) |
| `dns-check` / `validate-k8s` | Registros DNS esperados · `kustomize build` de todos os overlays |
| `golden` | Constrói a golden image (SO preparado) em `lab/cache/` com o overlay `golden` |
| `snapshot` / `revert` / `snapshots` | Snapshots libvirt das VMs do overlay (`NAME=<nome>`) |
### Ordem das roles

1. **00_install_kvm** — host (`kvm_hosts`): pacotes KVM, rede, firewall (opt-in)
2. **01_create_vm** — host: qcow2, virt-install, wait SSH
3. **02_prepare_vm** — VM: swap, SELinux, iptables baseline (firewalld off)
4. **03_install_rke2** — VM: RKE2 server com Cilium (ou **03_install_k3s**)
5. **04_deploy_k8s** — VM: cluster-config, local-path, Argo CD, Git local e
   Application raiz; o Argo CD instala sealed-secrets, cert-manager, External
   Secrets e as demais stacks

---

## Onde customizar

| Objetivo | Onde editar |
|----------|-------------|
| Topologia de VMs (nome, IP, overlay) | `provisioning/inventory/manifest.yml` → `make inventory` |
| Sobrescrever overlay ativo | `env/.env` (`OVERLAY`, `VM_NAME`, `VM_IP`) |
| Criar um overlay próprio (VM + stacks k8s) | `make tui` ou `make new NAME=...` → `manifest.local.yml` |
| Stacks/componentes de um overlay versionado | `k8s:` em `manifest.yml` → `uv run k8s-blueprint overlay render <id>` |
| Acrescentar um componente ao catálogo | `k8s/catalog.yml` + `base/` e `overlays/_template/` do componente |
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
| Overlays `broetec-*` e `_template` em `k8s/` | Overlays locais: `manifest.local.yml`, `provisioning/inventory/<id>/`, `k8s/**/overlays/<id>/` |
| `*-secret.yaml.example` | `*-secret.yaml` (exceto o didático do Argo CD), `*-sealedsecret.yaml`, `env/<overlay>/` |

Ver [.gitignore](../.gitignore) para a lista completa.
