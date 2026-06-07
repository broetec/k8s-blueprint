# `lab/` — artefactos locais do laboratório KVM

> Mapa geral do repositório: [`docs/structure.md`](../docs/structure.md)

Esta pasta guarda **tudo o que o `make up` gera no disco** e que não deve ir
para o Git. É descartável: `make clean` apaga o conteúdo gerado; apagar o
clone inteiro do repositório remove o lab por completo.

## Estrutura

| Subpasta | Conteúdo |
|----------|----------|
| `disks/` | Discos das VMs (`*.qcow2`), seed ISOs de cloud-init |
| `cache/` | Imagem base Rocky Linux (download único, clonada para cada VM nova) |

Os caminhos por defeito vêm de `LAB_PATH` no `Makefile` / `env/.env`
(padrão: `./lab` na raiz do repositório). Subpastas: `LAB_DISKS_PATH`,
`LAB_CACHE_PATH` (ou `$(LAB_PATH)/disks` e `/cache`). O Ansible recebe os
mesmos paths via `libvirt_pool.path` e `os_image.cache_dir` no inventário.

## O que **não** fica aqui

- Definições libvirt (rede `broetec-lab`, domínios XML) — ficam no host, geridas
  pelo playbook.
- Chave SSH do lab — em `env/k8s-blueprint` (gitignored noutra pasta).
- Ambiente Python do Ansible — em `.venv/` na raiz do repo.

## Limpeza

```bash
make clean          # remove VM, rede libvirt e apaga lab/cache + lab/disks (mantém este README)
rm -rf lab/cache lab/disks   # só os artefactos, sem tocar na VM (manual)
```

`make destroy` e `make clean` não usam `sudo` no host: o directório `lab/` fica
sob o utilizador que corre o lab, mesmo quando o libvirt muda o dono dos discos
para `qemu:qemu`.

Se migrou de uma versão antiga que usava `var/libvirt/`, pode apagar essa pasta
à mão depois de `make clean`:

```bash
sudo rm -rf var/libvirt
```
