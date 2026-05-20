# `provisioning/` — Ansible · KVM · cloud-init

Fase **imperativa** do k8s-blueprint da Broetec: este Ansible cria a rede libvirt
`10.20.30.0/24`, baixa a imagem qcow2 do Rocky Linux, gera o seed ISO de
cloud-init e provisiona as VMs definidas no inventário (overlays `broetec-*`),
deixando o sistema operacional pronto para etapas posteriores.

```text
provisioning/
├── site.yml                       # playbook mestre (orquestra as duas plays)
├── inventory/
│   ├── manifest.yml               # fonte de verdade (gera hosts.ini)
│   ├── _shared/group_vars/all.yml # variáveis Ansible partilhadas
│   ├── broetec-core/              # core @ 10.20.30.40
│   ├── broetec-storage/           # storage @ 10.20.30.50
│   └── broetec-monitor/           # telemetria @ 10.20.30.60
├── templates/
│   └── cloud-init.j2              # user-data (rede = DHCP + reserva MAC na libvirt)
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
  O utilizador na VM é sempre **`rocky`** (cloud-init não copia a chave para
  outras contas). Ex.: `ssh -i env/k8s-blueprint rocky@<vm_ip>` — não uses só
  `ssh <ip>` ou vais autenticar como o teu utilizador no laptop e levas *Permission denied*.
- **[uv](https://docs.astral.sh/uv/)** no `PATH` e **Python 3.12+** (o `Makefile` usa
  `make sync` → `uv sync` com o lock do repositório; ver secção seguinte).

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

## Ansible e Python (caminho padronizado: `uv` + `pyproject.toml`)

As versões de **ansible-core** e **ansible-pylibssh** ficam fixadas no repositório
(`pyproject.toml` + `uv.lock`), para o mesmo ambiente em qualquer distro Linux
onde o `uv` consiga obter o interpretador (`UV_PYTHON`, por defeito 3.12).

> **Por que não `libvirt-python`?** O role `kvm_vm` foi escrito para usar
> apenas o binário `virsh` (que você já tem instalado com o KVM). Isso evita
> compilar `libvirt-python` no controller — o que exigiria `libvirt-devel`,
> `pkgconf` e `gcc` instalados como camada `rpm-ostree` no Bazzite.

### Instalar o `uv` e sincronizar o projeto

```bash
# Caso ainda não tenha o uv:
curl -LsSf https://astral.sh/uv/install.sh | sh

# Na raiz do repositório (cria/atualiza .venv a partir do lock):
make sync
# ou:  uv sync --python 3.12 --frozen
```

O `Makefile` invoca o Ansible com **`uv run`** a partir da raiz do projeto
(usa sempre o `.venv` do lock). Ferramentas opcionais (ex.: `ansible-lint`)
podem ser adicionadas em `[project.optional-dependencies]` no `pyproject.toml`
e instaladas com `uv sync --extra …` se precisar.

**Armazenamento KVM no repositório:** discos das VMs (`*.qcow2`), seed ISOs e o
cache da imagem Rocky ficam em `lab/` na raiz do projeto (`lab/disks`, `lab/cache`;
gitignored — ver `lab/README.md`). `make clean` apaga essa árvore; não usa
`/var/lib/libvirt/images` do sistema.

**Dois “Pythons” no lab:** no **controlador** (laptop + play `kvm_hosts` local) corre
sempre o interpretador do `.venv` (`ansible_playbook_python` em
`group_vars/kvm_hosts.yml`). Nas **VMs** (`vms`), os módulos Ansible executam o
Python instalado no Rocky (`interpreter_python = auto_silent` no `ansible.cfg`) —
não copie nem aponte o `.venv` do repositório para o inventário das VMs.

### Coleções Galaxy (`ansible.posix`, `ansible.netcommon`)

- **`ansible.posix`**: módulo `firewalld` na role `os_prepare`.
- **`ansible.netcommon`**: plugin `libssh` para SSH às VMs sem fork do binário
  `ssh` (evita *worker dead* no terminal integrado do Cursor).

O alvo **`make deps`** instala ambas a partir de
`provisioning/collections/requirements.yml`. Manualmente:

```bash
uv run ansible-galaxy collection install -r provisioning/collections/requirements.yml
```

### Erro `A worker was found in a dead state`

O Ansible usa *workers* em processos filhos; em alguns ambientes (terminal
integrado do Cursor, AppImage, ou processo pai com *threads* extra) o segundo
bloco do playbook pode falhar mesmo com `forks=1`.

- Por defeito, `make up` corre **duas** invocações do `ansible-playbook`
  (`UP_SPLIT=1`), uma com `--tags kvm_lab` e outra com `--tags os_prepare`,
  para reiniciar o processo Python entre as plays.
- O inventário de exemplo usa **`ansible_connection=ansible.netcommon.libssh`**
  (bindings Python, não o subprocesso `ssh` do sistema — o plugin `ssh` openssh
  costuma falhar com *worker dead* no Cursor). Há **pipelining desativado** no
  `ansible.cfg`, `make up` em **duas invocações** (`UP_SPLIT=1`), e a role
  `os_prepare` começa com um `ping` sem `become`.
- Se ainda falhar: corra `make up` num **terminal fora do IDE** ou experimente
  outro `UV_PYTHON` (ex.: `make sync UV_PYTHON=3.13` antes do `make up`).
- Playbook numa só corrida: `make up UP_SPLIT=0` (pode voltar a falhar no 2.º
  play no mesmo ambiente). Com `--ask-become-pass`, o split pode pedir a senha
  **duas vezes** na 1.ª play; na 2.ª use `env/vm-become.pass` ou conta `rocky`
  com `NOPASSWD` (ver `make help`).

### Avisos `ssh_strict_fopen` / `packet type 80` (libssh)

Por defeito o blueprint **não altera ficheiros do sistema** (`/etc/ssh/…`).
Chaves de host do lab ficam em **`$HOME/.ssh/known_hosts`** (`make
ssh-host-key-refresh`, `make ssh`, plugin libssh).

O aviso `ssh_strict_fopen: … /etc/ssh/ssh_known_hosts` vem da biblioteca C
**libssh**, que tenta ler o ficheiro global opcional do SO (distinto de
`~/.ssh/known_hosts`). Em Bazzite/Fedora Atomic esse ficheiro muitas vezes não
existe; o playbook pode continuar com `failed=0`.

**Opt-in** (só se quiseres criar o ficheiro global no controlador):

```bash
cp env/.env.example env/.env
# Edite: CREATE_SSH_GLOBAL_KNOWN_HOSTS=true
make up   # ou: make ensure-ssh-global-known-hosts
```

`packet type 80` costuma ser ruído do handshake libssh↔`sshd` da Rocky. Se houver
falhas reais de ligação, actualize `ansible-pylibssh` / `ansible.netcommon`.

### Ficheiro `env/.env` (defaults do Make)

Copie `env/.env.example` → `env/.env` (gitignored; ver `env/README.md`).
Variáveis úteis: `OVERLAY`, `VM_IP`, `VM_NAME`, `UP_SPLIT`,
`CREATE_SSH_GLOBAL_KNOWN_HOSTS`. `make help` mostra a config efectiva.

---

## Executar o exemplo

### Caminho recomendado — `make up` (na raiz do projeto)

Há um `Makefile` na raiz que orquestra todo o ciclo de vida da VM. Ele
gera uma chave SSH **local de lab** em `env/k8s-blueprint[.pub]` (gitignored,
criada apenas na primeira execução), passa essa chave como override para o
Ansible e roda o playbook automaticamente. Você nunca precisa criar chave
manualmente nem editar `~/.ssh/`.

```bash
# Da raiz do repositório (opcional: cp env/.env.example env/.env):
make sync       # primeira vez ou após pull que altere pyproject.toml / uv.lock
make up         # provisiona (cria chave do lab + roda Ansible)
make ssh        # conecta na VM (rocky@10.20.30.40)
make status     # mostra estado da VM e da rede libvirt
make destroy    # remove a VM, mantém o cache da qcow2
make clean      # destrói TUDO (VM + rede + cache + chave do lab)
```

Overlays e IPs versionados em `provisioning/inventory/manifest.yml`.
Geração de `hosts.ini`: `make inventory` (ver `scripts/inventory/README.md`).

```bash
make inventory              # todos os overlays
make up OVERLAY=broetec-core
make up-lab                 # core + storage + monitor (3 VMs)
make ssh OVERLAY=broetec-storage
make destroy OVERLAY=broetec-monitor

# Sobrescrever IP do overlay ativo (env/.env ou linha de comando):
# OVERLAY=broetec-core  VM_IP=10.20.30.45
make inventory && make up
```

`make help` lista todos os targets e mostra a config atual.

### Caminho manual — `ansible-playbook` (didático)

Útil para entender o que o `Makefile` faz por baixo do capô. Corra **`make sync`**
antes (ou `uv sync`) para ter o mesmo `ansible-core` do lock. Use **`uv run`**
na raiz do repositório para carregar o `.venv` e respeitar o `ansible.cfg` do projeto.

Antes:

- Crie sua própria chave SSH (caso não use `make keys`), na raiz do repo:
  ```bash
  ssh-keygen -t ed25519 -C "k8s-blueprint" -f env/k8s-blueprint -N ""
  ```
- Ou ajuste `ssh_public_key_path` em `inventory/<overlay>/group_vars/all.yml`
  para apontar para uma chave existente.

Depois, da raiz:

```bash
uv run ansible-playbook \
  -i provisioning/inventory/broetec-core/hosts.ini \
  provisioning/site.yml \
  --skip-tags bootstrap \
  --ask-become-pass
```

Os caminhos `env/k8s-blueprint` estão definidos em `group_vars/all.yml`
(`_repo_root`). Gere a chave antes com `make keys` ou `ssh-keygen … -f env/k8s-blueprint`.

`--skip-tags bootstrap` pula as duas tasks que instalariam pacotes e
habilitariam `libvirtd` no host (necessário em Bazzite/imutáveis ou em
hosts onde KVM já está pronto). `--ask-become-pass` é necessário porque a
primeira play roda no `localhost` com `become: true` para criar `lab/disks` e
`lab/cache` (seed ISO, discos e cache da imagem base — gitignored).

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
  uv run ansible-playbook -i provisioning/inventory/broetec-core/hosts.ini \
    provisioning/site.yml --skip-tags bootstrap --ask-become-pass --check --diff
  ```

---

## Derrubar tudo

A forma mais simples é `make clean` (destrói VM + rede + `lab/` + chave do lab).
Se quiser fazer manualmente para entender o que acontece:

```bash
virsh -c qemu:///system destroy broetec || true
virsh -c qemu:///system undefine broetec --remove-all-storage

virsh -c qemu:///system net-destroy broetec-lab || true
virsh -c qemu:///system net-undefine broetec-lab

sudo rm -rf lab/cache lab/disks    # discos, seed ISO e cache da qcow2 base
rm -f env/k8s-blueprint env/k8s-blueprint.pub   # remove a chave SSH local
```
