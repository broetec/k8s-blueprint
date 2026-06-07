# `provisioning/templates/` — NoCloud seed ISO templates

Jinja2 templates rendered by role **`01_create_vm`** for each host in `groups['vms']`.
Output is packed into a NoCloud seed ISO at `lab/disks/<vm_name>-seed.iso` and attached
to the libvirt domain at first boot.

Part of `make create-vm` and `make up`. Requires `make inventory` so each VM has
`vm_ip` and `vm_mac` in `hosts.ini`.

## Position in the pipeline

```mermaid
flowchart LR
  MAN["manifest.yml"]
  GEN["make inventory"]
  INI["hosts.ini vm_ip vm_mac"]
  R01["role 01_create_vm"]
  ISO["lab/disks/vm-seed.iso"]
  VM["guest first boot"]

  MAN --> GEN --> INI --> R01 --> ISO --> VM
```

| Make target | What uses these templates |
|-------------|---------------------------|
| `make create-vm` | Role **01** — renders both templates per VM |
| `make up` | Roles **01–04** (templates only in role 01) |

## Templates

| Template | File on seed ISO | Purpose | Key variables |
|----------|------------------|---------|---------------|
| [`cloud-init.j2`](cloud-init.j2) | `user-data` | User, hostname, `/etc/hosts`, SSH keys | `cloud_init.*`, `vm_hostname`, `vm_ip`, `base_domain` |
| [`network-config.j2`](network-config.j2) | `network-config` | Static IP by MAC inside the guest | `vm_mac`, `vm_ip`, `kvm_network.*` |

Inventory source for `vm_ip` / `vm_mac`: [`provisioning/inventory/manifest.yml`](../inventory/manifest.yml)
→ `make inventory` → `hosts.ini`. Shared network vars: [`_shared/group_vars/all.yml`](../inventory/_shared/group_vars/all.yml).

## Network model

- Lab VMs get a **static address inside the guest** via `network-config` (not libvirt DHCP).
- `vm_mac` in inventory is passed to `virt-install --mac` and matched in `network-config.j2`
  so the correct NIC (`lab0`) receives `vm_ip`.
- MAC derivation when omitted in manifest: `52:54:00:<md5(hostname)>` — same rule as
  [`app/inventory/mac.py`](../../app/inventory/mac.py) and role **00**.

## When to regenerate

Changing `vm_ip` or `vm_mac` in `manifest.yml` **does not** update a running VM automatically.
The old address may persist from the previous seed ISO or DHCP pool (`.100–.200`).

```bash
make inventory OVERLAY=broetec-core
make destroy OVERLAY=broetec-core   # or remove lab/disks/<vm>-seed.iso and the domain
make up OVERLAY=broetec-core
```

See also [inventory troubleshooting](../inventory/README.md#wrong-ip-eg-102030118-instead-of-40) (Wrong IP section).

## Verification

On the KVM host:

```bash
virsh -c qemu:///system dumpxml broetec-core | grep "mac address"
# must match vm_mac in provisioning/inventory/<overlay>/hosts.ini

# inspect seed ISO contents (example)
mkdir -p /tmp/seed && mount -o loop lab/disks/broetec-core-seed.iso /tmp/seed
cat /tmp/seed/network-config /tmp/seed/user-data
sudo umount /tmp/seed
```

Inside the VM (after `make up`):

```bash
ip -4 addr show
ping -c 2 "{{ kvm_network.gateway }}"
```

## Configuration

Full variable catalog: [`inventory/_shared/group_vars/all.yml`](../inventory/_shared/group_vars/all.yml)
(`cloud_init`, `kvm_network`, `base_domain`). Per-VM overrides: `90_local.yml` in each overlay.

Role **01** task flow: [`roles/01_create_vm/README.md`](../roles/01_create_vm/README.md).

## Requirements

- `genisoimage` or `xorriso` on the KVM host (role 00 bootstrap or manual install)
- `make inventory` before `make create-vm`
- Role **00** NAT network `broetec-lab` defined (or equivalent)

## Advanced reference

Manual playbook (same templates, role 01 only):

```bash
uv run ansible-playbook \
  -i provisioning/inventory/broetec-core/hosts.ini \
  provisioning/site.yml \
  --tags create_vm \
  --limit kvm_hosts
```
