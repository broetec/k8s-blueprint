# k8s-blueprint

Laboratório de estudo para aprender **Ansible**, **KVM/libvirt** e
**Kubernetes** com um fluxo simples: `make up` provisiona a VM, prepara o SO e
corre as etapas k8s (stubs 03/04 até implementação completa).

Dependências Python (Ansible, pylibssh) via [uv](https://docs.astral.sh/uv/)
num `.venv` local.

## Pré-requisitos

- **KVM/libvirt** no host (`virsh`, `virt-install`, `qemu-img`)
- **[uv](https://docs.astral.sh/uv/)** no `PATH` e Python 3.12+

## Quick start

```bash
make sync              # .venv (uv sync)
make setup-host        # 1ª vez: deps + host KVM (bootstrap; re-login depois)
make up                # broetec-core: VM + SO + k8s (01–04)
make ssh               # rocky@10.20.30.40
make up-all            # core + storage + monitor (3 VMs)
make deploy            # só k8s (03 + 04) no overlay activo
make destroy           # remove VM do overlay
make clean             # reset completo
```

Outros overlays: `make up OVERLAY=broetec-storage`

Defaults locais: `cp env/.env.example env/.env` · `KVM_HOST_BOOTSTRAP=false` para saltar pacotes · re-login após bootstrap · `KVM_HOST_FIREWALL=true` para regras NAT no host · `make help`

## Pipeline Ansible (00–04)

| Etapa | Role | Target Make |
|-------|------|-------------|
| 00 | `00_install_kvm` | `make setup-host` (uma vez) |
| 01 | `01_create_vm` | `make create-vm` |
| 02 | `02_prepare_vm` | `make prepare-vm` |
| 03 | `03_install_rke2` | `make install-rke2` (stub) |
| 04 | `04_deploy_k8s` | `make deploy-k8s` (stub) |

`make up` = 01 + 02 + 03 + 04 (default overlay `broetec-core`).

## Estrutura

| Pasta | Função |
|-------|--------|
| [`app/`](app/) | App Python (gerador de inventário; futuro: configs custom) |
| [`make/`](make/) | Defaults e macros Ansible (includes do Makefile) |
| [`provisioning/`](provisioning/) | Ansible: playbook, inventário, roles, `ansible.cfg` |
| [`lab/`](lab/) | Discos e cache qcow2 gerados pelo `make up` (gitignored) |
| [`env/`](env/) | Chave SSH, `.env` do Make e credenciais locais |
| [`k8s/`](k8s/) | Manifests Kubernetes (futuro) |
| [`docs/`](docs/) | Documentação completa do projeto |
| [`tests/`](tests/) | Testes do app Python |

→ [`docs/index.md`](docs/index.md)
