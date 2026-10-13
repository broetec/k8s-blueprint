# k8s-blueprint

Laboratório de estudo para aprender **Ansible**, **KVM/libvirt** e
**Kubernetes** com um fluxo simples: `make up` provisiona a VM, prepara o SO,
instala o RKE2 e entrega o cluster ao **Argo CD** (app-of-apps), que instala o
restante a partir de [`k8s/`](k8s/). Além dos overlays versionados
(`broetec-*`), cada pessoa pode montar o próprio overlay — escolhendo stacks,
componentes e o tamanho da VM num menu interativo — sem commitar nada.

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
make destroy           # remove VM do overlay activo (OVERLAY=)
make destroy-all       # remove as VMs de todos os overlays
make clean             # reset completo
```

Outros overlays: `make up OVERLAY=broetec-storage`

## Montar o seu overlay

```bash
make tui                                   # menu interativo (typer + textual)
make new NAME=meu-lab FROM=broetec-storage # o mesmo, sem interação
make up OVERLAY=meu-lab                    # VM + RKE2 + Argo CD
make k8s-push OVERLAY=meu-lab              # depois de editar k8s/: Argo CD aplica
make rm-overlay NAME=meu-lab               # remove (após make destroy)
```

O overlay local fica em `provisioning/inventory/manifest.local.yml`,
`provisioning/inventory/<nome>/` e `k8s/**/overlays/<nome>/`, todos ignorados
pelo git. O Argo CD lê um repositório Git servido pela própria VM, então nada
precisa ser enviado ao GitHub para testar. Por padrão as URLs usam
`<app>.<ip-com-hífens>.sslip.io` com certificado autoassinado, sem criar DNS.
Detalhes em [`k8s/README.md`](k8s/README.md).

## URLs dos overlays versionados

`<app>.<papel>.local.broetec.com.br`, apontando para o IP da VM no libvirt:

| Overlay | IP | URLs |
|---------|----|------|
| `broetec-core` | 10.20.30.40 | `argo.core.local.broetec.com.br` |
| `broetec-storage` | 10.20.30.50 | `argo`, `harbor`, `s3` e `filer` em `.storage.local.broetec.com.br` |
| `broetec-monitor` | 10.20.30.60 | `argo.monitor.local.broetec.com.br` |

`make dns-check` lista os registros A esperados e os que ainda não resolvem.
Login do Argo CD no lab: `admin` / `broetec`.

Defaults locais: `cp env/.env.example env/.env` · `KVM_HOST_BOOTSTRAP=false` para saltar pacotes · re-login após bootstrap · `KVM_HOST_FIREWALL=true` para regras NAT no host · `make help`

## Pipeline Ansible (00–04)

| Etapa | Role | Target Make |
|-------|------|-------------|
| 00 | `00_install_kvm` | `make setup-host` (uma vez) |
| 01 | `01_create_vm` | `make create-vm` |
| 02 | `02_prepare_vm` | `make prepare-vm` |
| 03 | `03_install_rke2` | `make install-rke2` (ou `make install-k3s`) |
| 04 | `04_deploy_k8s` | `make deploy-k8s` |

`make up` = 01 + 02 + 03 + 04 (default overlay `broetec-core`).

## Estrutura

| Pasta | Função |
|-------|--------|
| [`app/`](app/) | App Python: inventário, overlays locais (`k8s-blueprint`), menu interativo e Sealed Secrets offline |
| [`make/`](make/) | Makefile orchestration — targets, defaults, Ansible wrapper ([`make/README.md`](make/README.md)) |
| [`provisioning/`](provisioning/) | Ansible: playbook, inventário, roles, `ansible.cfg` |
| [`lab/`](lab/) | Discos e cache qcow2 gerados pelo `make up` (gitignored) |
| [`env/`](env/) | Chave SSH, `.env` do Make e credenciais locais |
| [`k8s/`](k8s/) | Manifests Kubernetes por stack (`core`, `storage`): `applications/` do Argo CD + componentes `base/overlays` |
| [`docs/`](docs/) | Documentação completa do projeto |
| [`tests/`](tests/) | Testes do app Python |

→ [`docs/index.md`](docs/index.md)
