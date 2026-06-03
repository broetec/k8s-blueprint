# `00_install_kvm` — prepare the KVM/libvirt host

Ansible role **00** in the k8s-blueprint lab pipeline. It prepares the physical
(or local) **KVM host** before [`01_create_vm`](../01_create_vm/) creates VMs.

This role is **not** part of `make up` (daily flow). Run it once via
`make setup-host` (first time) or re-apply with `make install-kvm`.

## Purpose

Ensure the controller machine can run libvirt VMs with:

1. Required packages and `libvirtd` (optional bootstrap)
2. A shared NAT libvirt network (lab VMs get static IPs via cloud-init on the seed ISO)
3. Optional host firewall rules so lab VMs can reach the internet (opt-in)

## What it does

| Step | File | Description |
|------|------|-------------|
| Bootstrap | `tasks/bootstrap.yml` | Installs `qemu-kvm`, `libvirt`, `virt-install`, ISO tools; enables `libvirtd` |
| Network | `tasks/network.yml` | Defines/updates libvirt NAT network (bridge, gateway, optional DHCP pool); restarts when base XML changes. **Inline design notes:** see the file header in `tasks/network.yml`. |
| Firewall | `tasks/firewall/` | NAT/forward for the lab subnet when `kvm_host_firewall=true` (auto-detects backend) |

```text
bootstrap.yml  →  network.yml  →  firewall/ (opt-in)
     (optional)        (always)      (KVM_HOST_FIREWALL=true)
```

### Firewall backends (`tasks/firewall/`)

When `kvm_host_firewall=true`, the role detects the active backend (first match wins):

| Backend | When | Rules |
|---------|------|-------|
| firewalld | `systemctl is-active firewalld` == active | Zone `libvirt-routed`, masquerade, direct FORWARD + NAT |
| ufw | ufw service active and `ufw status` shows active | `before.rules` NAT/FORWARD block, `DEFAULT_FORWARD_POLICY=ACCEPT` |
| iptables | FORWARD chain policy is DROP | FORWARD accept + NAT MASQUERADE via `iptables` |
| none | No match | Debug message; no host changes |

Default is **off** (`KVM_HOST_FIREWALL=false` in `env/.env`). Most users without an
active host firewall are unaffected.

## Requirements

- Target host in inventory group **`kvm_hosts`** (typically `localhost` with `ansible_connection=local`)
- **`become: true`** (sudo) on the host
- Collection **`ansible.posix`** (firewalld, sysctl modules)
- After bootstrap: `virsh`, `virt-install` on `PATH`

## Tags

| Tag | Runs |
|-----|------|
| `install_kvm` | Network + firewall blocks (imported from `main.yml`) |
| `bootstrap`, `install` | Package install + `libvirtd` service |

By default, **`KVM_HOST_BOOTSTRAP=true`** in `env/.env` runs bootstrap together
with the libvirt network. Firewall rules are **not** applied unless
**`KVM_HOST_FIREWALL=true`**.

Disable package install (immutable OS or pre-configured host):

```bash
# env/.env
KVM_HOST_BOOTSTRAP=false
```

Enable host firewall rules (Docker + active firewall on the host):

```bash
# env/.env
KVM_HOST_FIREWALL=true
```

Or on the command line:

```bash
make setup-host KVM_HOST_BOOTSTRAP=false
make install-kvm KVM_HOST_FIREWALL=true
```

## Role variables

### Defaults (`defaults/main.yml`)

| Variable | Default | Meaning |
|----------|---------|---------|
| `kvm_host_bootstrap` | `true` | Install KVM packages and enable `libvirtd` when bootstrap tag runs |
| `kvm_host_firewall` | `false` | Apply NAT/forward rules on the host (auto-detect firewalld, ufw, iptables) |

### From inventory (`group_vars/all.yml`)

These are **not** defined in the role; set them in shared inventory (see
`provisioning/inventory/_shared/group_vars/all.yml`):

| Variable | Purpose |
|----------|---------|
| `kvm_network` | Network name, bridge, gateway, DHCP pool range, domain |
| `kvm_network_force_restart` | Force libvirt network restart (used by `make network-refresh`) |

Via Make, prefer `KVM_HOST_FIREWALL=true` in `env/.env` over inventory overrides.

## Outputs

| Fact | Set by | Used by |
|------|--------|---------|
| `kvm_libvirt_net_runtime_needs_refresh` | `network.yml` | Internal; triggers net restart when base XML changes |
| `kvm_firewall_backend` | `firewall/detect.yml` | Internal; selects firewalld, ufw, iptables, or none |

**Note:** `kvm_vm_mac_by_host` is set by [`01_create_vm`](../01_create_vm/) for
`virt-install` and `network-config` (not by this role).

## Make targets

| Command | Effect |
|---------|--------|
| `make setup-host` | `make setup` + role 00 (first-time controller + host; bootstrap from `env/.env`) |
| `make install-kvm` | Role 00 only (re-apply network/firewall/bootstrap without re-running `setup`) |
| `make network-refresh` | Reapply libvirt network with `kvm_network_force_restart=true` |

## Immutable OS (Bazzite, Silverblue, Kinoite)

Do **not** install RPMs via Ansible on immutable hosts:

- Set `KVM_HOST_BOOTSTRAP=false` in `env/.env` (or `kvm_host_bootstrap: false` in inventory)
- Install equivalent packages with `rpm-ostree` / distro docs manually
- Then run `make setup-host` or `make install-kvm` for network (and firewall if needed)

## Idempotency

- **Network:** Compares a SHA256 fingerprint of logical XML (forward, bridge, gateway, DHCP pool) before `net-define`
- **Firewall:** Skipped when `kvm_host_firewall=false`; when on, backend-specific checks (`-C`, `blockinfile` markers) avoid duplicate rules
- **Bootstrap:** `package` and `service` modules are idempotent

## Example playbook

From [`provisioning/site.yml`](../../site.yml):

```yaml
- name: "[1/5] Prepare KVM/libvirt host"
  hosts: kvm_hosts
  become: true
  gather_facts: true
  tags:
    - install_kvm
  roles:
    - role: 00_install_kvm
```

Manual run:

```bash
uv run ansible-playbook \
  -i provisioning/inventory/broetec-core/hosts.ini \
  provisioning/site.yml \
  --tags install_kvm \
  --limit kvm_hosts \
  -e kvm_host_firewall=true
```

## Manual verification

```bash
make setup-host                              # first time (bootstrap on by default)
make install-kvm                             # re-apply role 00 (network only)
make install-kvm KVM_HOST_FIREWALL=true      # network + host firewall rules
make install-kvm KVM_HOST_BOOTSTRAP=false    # skip package install
make network-refresh

virsh -c qemu:///system net-list --all
virsh -c qemu:///system net-dumpxml broetec-lab
```

## License

MIT (see repository)
