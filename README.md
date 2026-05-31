# k8s-blueprint

Laboratório de estudo para aprender **Ansible**, **KVM/libvirt** e
**Kubernetes** com um fluxo simples: um comando `make` cria uma VM Rocky Linux
pronta para as etapas seguintes.

As dependências Python (Ansible, pylibssh, etc.) são instaladas via
[uv](https://docs.astral.sh/uv/) num `.venv` local — não é preciso instalar
Ansible globalmente.

## Pré-requisitos

- **KVM/libvirt** no host (`virsh`, `virt-install`, `qemu-img`)
- **[uv](https://docs.astral.sh/uv/)** no `PATH` e Python 3.12+
- Em distros imutáveis (Bazzite, Silverblue), instale os pacotes KVM à mão;
  o `make up` usa `--skip-tags bootstrap` por defeito

## Quick start

```bash
make sync          # cria/atualiza .venv (uv sync)
make up            # chave SSH + inventário + Ansible (VM + SO preparado)
make ssh           # SSH para rocky@<VM_IP>
make status        # virsh list + redes libvirt
make destroy       # remove VMs (mantém cache qcow2)
make clean         # remove VM, rede, lab/ e chave SSH
```

Opcional — defaults locais:

```bash
cp env/.env.example env/.env
make help
```

## Estrutura do repositório

| Pasta | Função |
|-------|--------|
| [`app/`](app/) | App Python (gerador de inventário; futuro: configs custom) |
| [`provisioning/`](provisioning/) | Ansible: playbook, inventário, roles, `ansible.cfg` |
| [`lab/`](lab/) | Discos e cache qcow2 gerados pelo `make up` (gitignored) |
| [`env/`](env/) | Chave SSH, `.env` do Make e credenciais locais |
| [`k8s/`](k8s/) | Manifests Kubernetes (futuro) |
| [`docs/`](docs/) | Documentação completa do projeto |
| [`tests/`](tests/) | Testes do app Python |

## Documentação completa

→ [`docs/index.md`](docs/index.md)
