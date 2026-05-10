# `provisioning/` — Ansible · KVM · cloud-init

Fase **imperativa** do k8s-blueprint da Broetec: este Ansible cria a rede libvirt
`10.20.30.0/24`, baixa a imagem qcow2 do Rocky Linux, gera o seed ISO de
cloud-init e provisiona a VM definida no inventário (`node-01` / `10.20.30.40`),
deixando o sistema operacional pronto para etapas posteriores.

```text
provisioning/
├── site.yml                       # playbook mestre (orquestra as duas plays)
├── inventory/
│   └── example/                   # overlay de referência (versionado no git)
│       ├── hosts.ini
│       └── group_vars/all.yml
├── templates/
│   ├── cloud-init.j2              # user-data (cloud-init)
│   └── network-config.j2          # rede v2 para o seed ISO NoCloud
└── roles/
    ├── kvm_vm/tasks/main.yml      # libvirt, qcow2, seed ISO, virt-install
    └── os_prepare/tasks/main.yml  # swap, SELinux, firewalld dentro da VM
```

---

## Pré-requisitos

- **Host com KVM/libvirt funcionando.** Verifique com:
  ```bash
  systemctl is-active libvirtd
  virsh -c qemu:///system list --all
  command -v virt-install qemu-img && { command -v genisoimage >/dev/null || command -v xorriso >/dev/null; }
  ```
  Em distros imutáveis (Bazzite, Silverblue, Kinoite), o `Makefile` já corre com
  `--skip-tags bootstrap` por defeito — o Ansible **não** chama `dnf`/`rpm` no host.
  Instale os pacotes à mão (secção seguinte) e configure o `libvirtd` antes do `make up`.
- **Chave SSH** — com `make up` ela é criada em `env/k8s-blueprint[.pub]` (ver
  `env/README.md`). No caminho manual (sem Make), use uma chave própria ou
  gere no repositório:
  ```bash
  ssh-keygen -t ed25519 -C "k8s-blueprint" -f env/k8s-blueprint -N ""
  ```
- **Ansible Core 2.16+** instalado em user space (uma das opções abaixo).

### Fedora Atomic / Bazzite — equivalente à tag `bootstrap`

O role `kvm_vm` estava a instalar estes RPMs no host KVM (quando a tag `bootstrap`
corre). Em **Bazzite** faça a camada equivalente com `rpm-ostree`, **reinicie**, e só
depois rode `make up`:

| Pacote | Uso neste projeto |
|--------|-------------------|
| `qemu-kvm` | hypervisor e `qemu-img` (clonar/redimensionar qcow2) |
| `libvirt` | daemon e ferramentas base |
| `libvirt-client` | `virsh` |
| `virt-install` | criar a VM (`virt-install --import`) |
| `libguestfs-tools` | utilitários guestfs (a role segue o playbook original) |
| `xorriso` **ou** `genisoimage` | gerar o seed ISO do cloud-init (basta um dos dois) |

Comando típico (um dos ISO tools chega):

```bash
rpm-ostree install qemu-kvm libvirt libvirt-client virt-install libguestfs-tools xorriso
sudo systemctl reboot
```

Após o reboot, garanta o serviço e permissões (o playbook **não** faz isto quando
salta `bootstrap`):

```bash
sudo systemctl enable --now libvirtd
sudo usermod -aG libvirt "$USER"
# novo login na sessão para o grupo `libvirt` fazer efeito
```

Fedora **Workstation** clássico (dnf): se preferir que o Ansible instale tudo, use
`make up ANSIBLE_FLAGS=` (sem saltar a tag `bootstrap`).

---

## Instalação do Ansible

Use **um** dos dois métodos. Ambos instalam o Ansible em user space, sem mexer
em pacotes do sistema — adequado tanto para distros imutáveis quanto para
distros tradicionais.

> **Por que não `libvirt-python`?** O role `kvm_vm` foi escrito para usar
> apenas o binário `virsh` (que você já tem instalado com o KVM). Isso evita
> compilar `libvirt-python` no controller — o que exigiria `libvirt-devel`,
> `pkgconf` e `gcc` instalados como camada `rpm-ostree` no Bazzite.

### Método 1 — `uv` (recomendado)

[`uv`](https://docs.astral.sh/uv/) é o gerenciador Python da Astral; é rápido,
mantém venvs isolados por ferramenta e funciona perfeitamente em Bazzite.

```bash
# Caso ainda não tenha o uv:
curl -LsSf https://astral.sh/uv/install.sh | sh

# Ansible (engine + pacote agregador "ansible")
uv tool install ansible-core --with ansible

# Tooling auxiliar (lint e UI textual)
uv tool install ansible-lint
uv tool install ansible-navigator
```

> O `--with ansible` traz o pacote agregador (`ansible`) com as coleções
> community por cima do `ansible-core`, dentro do mesmo venv da ferramenta.

### Método 2 — `pipx` (alternativa)

[`pipx`](https://pipx.pypa.io/) também isola cada CLI em seu próprio venv. É
útil se você já o utiliza para outras ferramentas Python.

```bash
# Caso ainda não tenha o pipx:
python3 -m pip install --user pipx
python3 -m pipx ensurepath

pipx install ansible-core
pipx inject  ansible-core ansible
pipx install ansible-lint
pipx install ansible-navigator
```

### Coleções Ansible (passo comum aos dois métodos)

Apenas `ansible.posix` é necessária (usada pelo módulo `firewalld` na role
`os_prepare`):

```bash
ansible-galaxy collection install ansible.posix
```

Confira a instalação:

```bash
ansible --version
ansible-galaxy collection list | grep ansible.posix
```

---

## Executar o exemplo

### Caminho recomendado — `make up` (na raiz do projeto)

Há um `Makefile` na raiz que orquestra todo o ciclo de vida da VM. Ele
gera uma chave SSH **local de lab** em `env/k8s-blueprint[.pub]` (gitignored,
criada apenas na primeira execução), passa essa chave como override para o
Ansible e roda o playbook automaticamente. Você nunca precisa criar chave
manualmente nem editar `~/.ssh/`.

```bash
# Da raiz do repositório:
make up         # provisiona (cria chave do lab + roda Ansible)
make ssh        # conecta na VM (rocky@10.20.30.40)
make status     # mostra estado da VM e da rede libvirt
make destroy    # remove a VM, mantém o cache da qcow2
make clean      # destrói TUDO (VM + rede + cache + chave do lab)
```

Para alternar entre overlays (a configuração por ambiente vive **só** em
`provisioning/inventory/`):

```bash
cp -r provisioning/inventory/example provisioning/inventory/local
$EDITOR provisioning/inventory/local/group_vars/all.yml

# Se a sua VM/IP/rede do overlay forem diferentes do default, sobrescreva
# na linha de comando para que o `make ssh`/`destroy`/`status` aponte certo:
make up      OVERLAY=local
make ssh     OVERLAY=local VM_IP=10.20.30.50
make destroy OVERLAY=local VM_NAME=node-02 KVM_NETWORK=outra-rede
```

`make help` lista todos os targets e mostra a config atual.

### Caminho manual — `ansible-playbook` (didático)

Útil para entender o que o `Makefile` faz por baixo do capô. Antes:

- Crie sua própria chave SSH (caso não use `make keys`), na raiz do repo:
  ```bash
  ssh-keygen -t ed25519 -C "k8s-blueprint" -f env/k8s-blueprint -N ""
  ```
- Ou ajuste `ssh_public_key_path` em `inventory/<overlay>/group_vars/all.yml`
  para apontar para uma chave existente.

Depois, da raiz:

```bash
ansible-playbook \
  -i provisioning/inventory/example/hosts.ini \
  provisioning/site.yml \
  --skip-tags bootstrap \
  --ask-become-pass
```

Os caminhos `env/k8s-blueprint` estão definidos em `group_vars/all.yml`
(`_repo_root`). Gere a chave antes com `make keys` ou `ssh-keygen … -f env/k8s-blueprint`.

`--skip-tags bootstrap` pula as duas tasks que instalariam pacotes e
habilitariam `libvirtd` no host (necessário em Bazzite/imutáveis ou em
hosts onde KVM já está pronto). `--ask-become-pass` é necessário porque a
primeira play roda no `localhost` com `become: true` para escrever em
`/var/lib/libvirt/images`.

Para fixar `--skip-tags bootstrap` permanentemente, defina no overlay:

```yaml
# inventory/<overlay>/group_vars/all.yml
kvm_host_bootstrap: false
```

### Modo dry-run (`--check --diff`) — limitações

`--check` simula tudo sem aplicar; `--diff` mostra o que seria escrito. **No
primeiro run, porém, ele vai falhar a partir do momento em que precisar de
artefatos que ainda não existem** (a qcow2 base que seria baixada, o seed ISO,
etc.) — porque o Ansible não pode "simular" o `get_url`/`copy` em algo que
não existe no host. Algumas tasks também aparecem como `skipping` porque o
módulo `command` é, por design, pulado em `--check` (existem alguns que
marcamos com `check_mode: false` por serem read-only seguras, como
`virsh net-list`).

Como usar:

- **Primeira execução:** rode `make up` (ou o `ansible-playbook` direto).
- **Re-execuções (após o cache da qcow2 já existir):** aí sim,
  `--check --diff` é útil para confirmar que nada inesperado mudou:

  ```bash
  ansible-playbook -i provisioning/inventory/example/hosts.ini \
    provisioning/site.yml --skip-tags bootstrap --ask-become-pass --check --diff
  ```

---

## Derrubar tudo

A forma mais simples é `make clean` (destrói VM + rede + cache + chave do lab).
Se quiser fazer manualmente para entender o que acontece:

```bash
virsh -c qemu:///system destroy node-01 || true
virsh -c qemu:///system undefine node-01 --remove-all-storage

virsh -c qemu:///system net-destroy broetec-lab || true
virsh -c qemu:///system net-undefine broetec-lab

sudo rm -f /var/lib/libvirt/images/node-01-seed.iso
sudo rm -rf /var/lib/libvirt/images/_cache    # opcional: descarta o cache da qcow2
rm -f env/k8s-blueprint env/k8s-blueprint.pub   # remove a chave SSH local
```
