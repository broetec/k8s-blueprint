# `00_install_kvm` — prepare the KVM/libvirt host

Ansible role **00** in the k8s-blueprint lab pipeline. It prepares the physical
(or local) **KVM host** before [`01_create_vm`](../01_create_vm/) creates VMs.

This role is **not** part of `make up` (daily flow). Run it once via
`make setup-host` (first time) or re-apply with `make install-kvm`.

## Purpose

Ensure the controller machine can run libvirt VMs with:

1. Required packages and `libvirtd` (optional bootstrap)
2. A NAT libvirt network with stable DHCP reservations per VM MAC
3. firewalld rules so lab VMs can reach the internet (Fedora/RHEL + Docker hosts)

## What it does

| Step | File | Description |
|------|------|-------------|
| Bootstrap | `tasks/bootstrap.yml` | Installs `qemu-kvm`, `libvirt`, `virt-install`, ISO tools; enables `libvirtd` |
| Network | `tasks/network.yml` | Derives MACs, defines/updates libvirt NAT network, DHCP reservations, restarts dnsmasq when XML changes |
| Firewalld | `tasks/firewalld-lab.yml` | NAT/forward for the lab subnet on `libvirt-routed` zone (skipped if firewalld inactive) |

```text
bootstrap.yml  →  network.yml  →  firewalld-lab.yml
     (optional)        (always)         (optional)
```

## Requirements

- Target host in inventory group **`kvm_hosts`** (typically `localhost` with `ansible_connection=local`)
- **`become: true`** (sudo) on the host
- Collection **`ansible.posix`** (firewalld module)
- After bootstrap: `virsh`, `virt-install` on `PATH`

## Tags

| Tag | Runs |
|-----|------|
| `install_kvm` | Network + firewalld blocks (imported from `main.yml`) |
| `bootstrap`, `install` | Package install + `libvirtd` service |

By default, **`KVM_HOST_BOOTSTRAP=true`** in `env/.env` (or Makefile default)
runs bootstrap together with network and firewalld.

Disable package install (immutable OS or pre-configured host):

```bash
# env/.env
KVM_HOST_BOOTSTRAP=false
```

Or on the command line:

```bash
make setup-host KVM_HOST_BOOTSTRAP=false
make install-kvm KVM_HOST_BOOTSTRAP=false
```

## Role variables

### Defaults (`defaults/main.yml`)

| Variable | Default | Meaning |
|----------|---------|---------|
| `kvm_host_bootstrap` | `true` | Install KVM packages and enable `libvirtd` when bootstrap tag runs |
| `kvm_network_firewalld` | `true` | Apply firewalld NAT/forward rules when firewalld is active |

### From inventory (`group_vars/all.yml`)

These are **not** defined in the role; set them in shared inventory (see
`provisioning/inventory/_shared/group_vars/all.yml`):

| Variable | Purpose |
|----------|---------|
| `kvm_network` | Network name, bridge, gateway, DHCP range, domain |
| `kvm_network_dhcp_reservations` | Generated list of `{name, mac, ip}` for all overlays (`make inventory`) |
| `kvm_network_force_restart` | Force libvirt network restart (used by `make network-refresh`) |

## Outputs

| Fact | Set by | Used by |
|------|--------|---------|
| `kvm_vm_mac_by_host` | `network.yml` | `01_create_vm` (`virt-install` MAC, DHCP validation) |
| `kvm_libvirt_net_runtime_needs_refresh` | `network.yml` | Internal; triggers dnsmasq lease cleanup + net restart |

**Note:** `01_create_vm` recomputes `kvm_vm_mac_by_host` when run alone
(`make up`), because Ansible facts do not persist across separate
`ansible-playbook` invocations.

## Make targets

| Command | Effect |
|---------|--------|
| `make setup-host` | `make setup` + role 00 (first-time controller + host; bootstrap from `env/.env`) |
| `make install-kvm` | Role 00 only (re-apply network/firewalld/bootstrap without re-running `setup`) |
| `make network-refresh` | Reapply network with `kvm_network_force_restart=true` |

## Immutable OS (Bazzite, Silverblue, Kinoite)

Do **not** install RPMs via Ansible on immutable hosts:

- Set `KVM_HOST_BOOTSTRAP=false` in `env/.env` (or `kvm_host_bootstrap: false` in inventory)
- Install equivalent packages with `rpm-ostree` / distro docs manually
- Then run `make setup-host` or `make install-kvm` for network and firewalld only

## Idempotency

- **Network:** Compares a SHA256 fingerprint of logical XML (forward, bridge, DHCP hosts) before `net-define`
- **DHCP:** Removes stale dnsmasq lease files when reservations change or VM is renamed
- **Firewalld:** No-op when `systemctl is-active firewalld` is not `active`
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
  --limit kvm_hosts
```

## Manual verification

```bash
make setup-host              # first time (bootstrap on by default)
make install-kvm             # re-apply role 00
make install-kvm KVM_HOST_BOOTSTRAP=false   # network + firewalld only
make network-refresh

virsh -c qemu:///system net-list --all
virsh -c qemu:///system net-dumpxml broetec-lab
```

## License

MIT (see repository)
