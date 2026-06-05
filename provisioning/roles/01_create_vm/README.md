# `01_create_vm` — provision lab VMs on libvirt

Ansible role **01** in the k8s-blueprint pipeline. Clones the Rocky cloud image,
builds cloud-init seed ISOs, and runs `virt-install` for each host in `groups['vms']`.

Requires role **00** (or equivalent host prep): NAT network `broetec-lab`, tools on `PATH`.

## Host privileges

Play [`site.yml`](../../site.yml) runs this role with **`become: false`**. The operator
needs:

- Group **`libvirt`** — `virsh -c qemu:///system`, `virt-install --connect qemu:///system`
- Group **`kvm`** — access to `/dev/kvm`
- **Active session** after bootstrap (re-login once; see [`00_install_kvm`](../00_install_kvm/README.md))
- Writable `lab/disks` and `lab/cache` (owned by `kvm_host_libvirt_user`, default `$USER`)

SELinux `virt_image_t` for lab paths is configured once in role **00** bootstrap.

## Related commands

```bash
make create-vm
make up    # includes create-vm
```
