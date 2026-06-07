# `provisioning/` — Ansible · KVM · cloud-init

> Repository map: [`docs/structure.md`](../docs/structure.md)

**Imperative** phase of the Broetec k8s-blueprint: this Ansible stack creates the
libvirt network `10.20.30.0/24`, downloads the Rocky Linux qcow2 image, builds
cloud-init seed ISOs, and provisions VMs from inventory overlays (`broetec-*`),
leaving the guest OS ready for later stages.

```text
provisioning/
├── README.md                      # this hub — prerequisites, make up, SSH
├── ansible.cfg                    # timeouts, SSH, libssh (Makefile sets ANSIBLE_CONFIG)
├── site.yml                       # master playbook (5 plays, roles 00–04)
├── collections/
│   ├── README.md                  # Galaxy deps, make deps, troubleshooting
│   └── requirements.yml
├── inventory/
│   ├── README.md                  # overlays, manifest, group_vars layers
│   ├── manifest.yml               # source of truth → hosts.ini
│   └── _shared/group_vars/all.yml # shared Ansible variables
├── templates/
│   ├── README.md                  # NoCloud seed ISO templates
│   ├── cloud-init.j2              # user-data (user, hostname, /etc/hosts)
│   └── network-config.j2          # static guest IP (NoCloud seed ISO)
└── roles/
    ├── 00_install_kvm/README.md   # host bootstrap, libvirt network, firewall
    ├── 01_create_vm/README.md     # qcow2, seed ISO, virt-install
    ├── 02_prepare_vm/README.md    # swap, SELinux, firewalld inside VM
    ├── 03_install_rke2/README.md  # RKE2 (stub)
    └── 04_deploy_k8s/README.md    # k8s manifests (stub)
```

Generator for `make inventory`: [`app/inventory/README.md`](../app/inventory/README.md).

## Documentation map

| Topic | Where to read |
|-------|---------------|
| Master playbook, tags, Make targets | [`site.yml`](site.yml) banner, [roles READMEs](roles/) |
| Ansible.cfg (forks, libssh) | [`ansible.cfg`](ansible.cfg), [`collections/README.md`](collections/README.md) |
| Overlays, manifest, group_vars | [`inventory/README.md`](inventory/README.md) |
| Shared variables | [`inventory/_shared/group_vars/all.yml`](inventory/_shared/group_vars/all.yml) |
| Cloud-init / network templates | [`templates/README.md`](templates/README.md) |
| Galaxy collections | [`collections/README.md`](collections/README.md) |
| Inventory generator (Python) | [`app/inventory/README.md`](../app/inventory/README.md) |
| Disposable disk artifacts | [`lab/README.md`](../lab/README.md) |
| env/.env defaults | [`env/README.md`](../env/README.md) |

---

## Prerequisites

- **KVM/libvirt host working.** Verify with:
  ```bash
  systemctl is-active libvirtd
  virsh -c qemu:///system list --all
  command -v virt-install qemu-img && { command -v genisoimage >/dev/null || command -v xorriso >/dev/null; }
  ```
  On immutable distros (Bazzite, Silverblue, Kinoite), set `KVM_HOST_BOOTSTRAP=false`
  in `env/.env` — Ansible will **not** run `dnf`/`rpm` on the host. Install packages
  manually (next section) and configure `libvirtd` before `make up`.
- **SSH key** — `make up` creates `env/k8s-blueprint[.pub]` (see `env/README.md`).
  Manual path without Make:
  ```bash
  ssh-keygen -t ed25519 -C "k8s-blueprint" -f env/k8s-blueprint -N ""
  ```
  SSH user for Ansible plays is **`rocky`** (`manifest.yml` defaults). Cloud-init
  creates `cloud_init.default_user` (see `all.yml`). Example:
  `ssh -i env/k8s-blueprint rocky@<vm_ip>` — do not use bare `ssh <ip>` or you
  authenticate as your laptop user and get *Permission denied*.
- **[uv](https://docs.astral.sh/uv/)** on `PATH` and **Python 3.12+** (`make sync` →
  `uv sync` with the repo lock; see below).

### Fedora Atomic / Bazzite — equivalent to tag `bootstrap`

Role `00_install_kvm` installs these RPMs on the KVM host when tag `bootstrap`
runs. On **Bazzite**, use `rpm-ostree`, **reboot**, then `make up`:

| Package | Use in this project |
|---------|---------------------|
| `qemu-kvm` | hypervisor and `qemu-img` (clone/resize qcow2) |
| `libvirt` | daemon and base tools |
| `libvirt-client` | `virsh` |
| `virt-install` | create VM (`virt-install --import`) |
| `libguestfs-tools` | guestfs utilities (role follows original playbook) |
| `xorriso` **or** `genisoimage` | cloud-init seed ISO (either is enough) |

Typical command (one ISO tool is enough):

```bash
rpm-ostree install qemu-kvm libvirt libvirt-client virt-install libguestfs-tools xorriso
sudo systemctl reboot
```

After reboot, ensure service and permissions (playbook **skips** this when
bootstrap is off):

```bash
sudo systemctl enable --now libvirtd
sudo usermod -aG libvirt,kvm "$USER"
# new login for groups to take effect
```

Classic Fedora **Workstation** (dnf): if you prefer Ansible to install everything,
use `make up ANSIBLE_FLAGS=` (do not skip tag `bootstrap`).

---

## Ansible and Python (`uv` + `pyproject.toml`)

**ansible-core** and **ansible-pylibssh** versions are pinned in the repo
(`pyproject.toml` + `uv.lock`) for a consistent environment on any Linux distro
where `uv` can obtain the interpreter (`UV_PYTHON`, default 3.12).

> **Why no `libvirt-python`?** Roles `00_install_kvm` and `01_create_vm` use only
> the `virsh` binary (installed with KVM). That avoids compiling `libvirt-python` on
> the controller — which would require `libvirt-devel`, `pkgconf`, and `gcc` as an
> `rpm-ostree` layer on Bazzite.

### Install `uv` and sync the project

```bash
# If you do not have uv yet:
curl -LsSf https://astral.sh/uv/install.sh | sh

# At repo root (creates/updates .venv from lock):
make sync
# or:  uv sync --python 3.12 --frozen
```

The `Makefile` invokes Ansible with **`uv run`** from the project root (always
uses the lock `.venv`). Optional tools (e.g. `ansible-lint`) can go in
`[project.optional-dependencies]` in `pyproject.toml`.

**KVM storage in the repo:** VM disks (`*.qcow2`), seed ISOs, and Rocky image
cache live under `lab/` (`lab/disks`, `lab/cache`; gitignored — see `lab/README.md`).
`make clean` removes that tree; does not use system `/var/lib/libvirt/images`.

**Two Pythons in the lab:** on the **controller** (laptop + local `kvm_hosts` play),
always the `.venv` interpreter (`ansible_playbook_python` in
`_shared/group_vars/kvm_hosts.yml`, symlinked per overlay via `make inventory`).
On **VMs** (`vms`), Ansible modules use Rocky’s system Python
(`interpreter_python = auto_silent` in `provisioning/ansible.cfg`) — do not point
VM inventory at the repo `.venv`.

### Galaxy collections

See [`collections/README.md`](collections/README.md) for full detail. Summary:

- **`ansible.posix`**: firewalld/sysctl on role 00 (host) and role 02 (VM).
- **`ansible.netcommon`**: `libssh` plugin for VM SSH without forking system `ssh`.

```bash
make deps
# or manually:
uv run ansible-galaxy collection install -r provisioning/collections/requirements.yml
```

### Error `A worker was found in a dead state`

Ansible uses worker child processes; in some environments (Cursor integrated
terminal, AppImage, or parent with extra threads) the second playbook block can
fail even with `forks=1`.

- By default, `make up` runs **multiple** `ansible-playbook` invocations
  (create-vm, prepare-vm, install-rke2, deploy-k8s) — fresh Python process per stage.
- Inventory uses **`ansible_connection=ansible.netcommon.libssh`** (Python bindings,
  not system `ssh` subprocess). **Pipelining is off** in `provisioning/ansible.cfg`;
  role `02_prepare_vm` starts with `ping` without `become`.
- If it still fails: run `make up` in a **terminal outside the IDE** or try another
  `UV_PYTHON` (e.g. `make sync UV_PYTHON=3.13`).
- With `--ask-become-pass`, Make only asks for host password when bootstrap or
  `KVM_HOST_FIREWALL=true` run. `make up` / `create-vm` do not use sudo on the host.
  For `vms` plays use `env/vm-become.pass` or `rocky` with `NOPASSWD` (see `make help`).

### Warnings `ssh_strict_fopen` / `packet type 80` (libssh)

By default the blueprint **does not modify system files** (`/etc/ssh/…`).

**Mitigation without root (default):**

1. `make setup-host` runs `ensure-user-known-hosts` once on the controller:
   `~/.ssh/known_hosts`, `env/global-known_hosts_stub`, `env/ssh_config_lab`.
2. Inventory sets `ansible_libssh_config_file` to that config (lab network `10.20.30.*`).
3. `ssh-host-key-refresh` records the VM key before plays against `vms`.
4. Make passes `ansible_prune_ssh_known_hosts=false` — avoids `site.yml` removing
   the key right after refresh.

Skipping `setup-host` still works via `make keys` or `make up` (fallback).

| Variable (`env/.env`) | Default | Effect |
|---|---|---|
| `CREATE_SSH_GLOBAL_KNOWN_HOSTS` | `false` | `true` → `sudo` creates empty `/etc/ssh/ssh_known_hosts` (silences `ssh_strict_fopen`) |
| `ANSIBLE_VM_CONNECTION` | `libssh` | `ssh` → OpenSSH (less libssh noise; worker-dead risk in Cursor) |
| `ANSIBLE_PRUNE_SSH_KNOWN_HOSTS` | `false` | `true` → `site.yml` runs `ssh-keygen -R` (manual `ansible-playbook` use) |

`packet type 80` is usually libssh↔Rocky `sshd` handshake noise. For real connection
failures, update `ansible-pylibssh` / `ansible.netcommon`.

### `env/.env` (Make defaults)

Copy `env/.env.example` → `env/.env` (gitignored; see `env/README.md`).
Useful keys: `OVERLAY`, `VM_IP`, `VM_NAME`, `CREATE_SSH_GLOBAL_KNOWN_HOSTS`,
`ANSIBLE_VM_CONNECTION`, `ANSIBLE_PRUNE_SSH_KNOWN_HOSTS`, `KVM_HOST_BOOTSTRAP`,
`KVM_HOST_FIREWALL`.

---

## Run the lab

### Recommended — `make up` (repo root)

The root `Makefile` orchestrates the VM lifecycle: generates a **local lab SSH key**
at `env/k8s-blueprint[.pub]` (gitignored, first run only), passes it to Ansible,
and runs the playbook. No manual key setup or `~/.ssh` edits required.

```bash
# First time (cp env/.env.example env/.env if needed):
make setup-host

# Daily use (default broetec-core):
make sync
make inventory          # required after fresh clone
make up                 # 01–04: VM + OS + k8s (stubs 03/04)
make ssh
make status
make destroy
make clean

# Overlays:
make up OVERLAY=broetec-core
make up-all             # core + storage + monitor (3 VMs)
make deploy OVERLAY=broetec-core   # k8s only (03 + 04)
make ssh OVERLAY=broetec-storage
make destroy OVERLAY=broetec-monitor
```

`make help` lists all targets and current config.

### Manual — `ansible-playbook` (educational)

Run **`make sync`** first (or `uv sync`) for the locked `ansible-core`. Use **`uv run`**
at repo root to load `.venv` and honor `provisioning/ansible.cfg`.

Before running:

- Create your SSH key (if not using `make keys`):
  ```bash
  ssh-keygen -t ed25519 -C "k8s-blueprint" -f env/k8s-blueprint -N ""
  ```
- Or set `ssh_public_key_path` in overlay `90_local.yml` to an existing key.

To skip host package install (Bazzite/immutable or KVM already ready), in `env/.env`:

```bash
KVM_HOST_BOOTSTRAP=false
KVM_HOST_FIREWALL=true   # NAT/FORWARD rules on host
```

Or: `make setup-host KVM_HOST_BOOTSTRAP=false`.

Manual equivalent: `--skip-tags bootstrap`. With bootstrap and firewall off, **no**
`--ask-become-pass` on the host (user in `libvirt` and `kvm` groups, active session):

```bash
uv run ansible-playbook \
  -i provisioning/inventory/broetec-core/hosts.ini \
  provisioning/site.yml \
  --skip-tags bootstrap \
  --tags install_kvm \
  --limit kvm_hosts
```

With `KVM_HOST_FIREWALL=true` or bootstrap on, use `--ask-become-pass` or
`env/become.pass` for role 00 tasks with `become: true`.

Key paths are in `group_vars/all.yml` (`_repo_root`). Generate with `make keys` or
`ssh-keygen … -f env/k8s-blueprint`.

Inventory alternative without Make:

```yaml
# inventory/<overlay>/group_vars/all/90_local.yml
kvm_host_bootstrap: false
```

### Dry-run (`--check --diff`) — limitations

`--check` simulates without applying; `--diff` shows pending writes. **On first
run it fails** when tasks need artifacts that do not exist yet (qcow2 download, seed
ISO, etc.). Some `command` tasks show `skipping` in check mode by design.

- **First run:** use `make up` (or direct `ansible-playbook`).
- **Re-runs** (after qcow2 cache exists): `--check --diff` is useful:

  ```bash
  uv run ansible-playbook -i provisioning/inventory/broetec-core/hosts.ini \
    provisioning/site.yml --skip-tags bootstrap --check --diff
  ```

---

## Tear down

Simplest: `make clean` (destroys VM + network + `lab/` + lab SSH key).
`make destroy` and `make clean` **do not require host sudo** in the normal flow:
`virsh` uses Polkit (`libvirt` + `kvm` groups after `make setup-host` and re-login);
files in `lab/disks/` are owned by the operator — deleting `*.qcow2` or `*-seed.iso`
only needs write access to `lab/disks/`, not root.

Manual equivalent:

```bash
virsh -c qemu:///system destroy broetec-core || true
virsh -c qemu:///system undefine broetec-core --remove-all-storage

virsh -c qemu:///system net-destroy broetec-lab || true
virsh -c qemu:///system net-undefine broetec-lab

rm -rf lab/cache lab/disks
rm -f env/k8s-blueprint env/k8s-blueprint.pub
```
