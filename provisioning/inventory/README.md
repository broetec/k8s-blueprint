# Inventário Ansible — overlays Broetec

## Overlays versionados

| Overlay | VM (libvirt) | IP | Papel (`vm_role`) |
|---------|--------------|-----|-------------------|
| `broetec-core` | broetec-core | 10.20.30.40 | `core` |
| `broetec-storage` | broetec-storage | 10.20.30.50 | `storage` |
| `broetec-monitor` | broetec-monitor | 10.20.30.60 | `monitor` |

Todos partilham o mesmo playbook (`provisioning/site.yml`) e roles (`kvm_host`, `kvm_vm`, `os_prepare`).

## Camadas de variáveis (por overlay)

Cada overlay tem `group_vars/all/` com merge automático (ordem alfabética):

| Ficheiro | Origem | Função |
|----------|--------|--------|
| `00_shared.yml` | symlink → `_shared/group_vars/all.yml` | Base comum (rede, imagem, cloud-init) |
| `10_dhcp_reservations.yml` | symlink → `_shared/.../dhcp_reservations.yml` | Reservas DHCP (gerado) |
| `50_overlay.generated.yml` | **gerado** (`make inventory`) | `vm_role`, `overlay_id`, `vars` do manifest |
| `90_local.yml` | **versionado, manual** | Overrides por máquina (disco, vCPUs, etc.) |

Edite **`manifest.yml`** para identidade (IP, role, vars declarativas) e **`90_local.yml`** para ajustes finos por overlay.

## Gerar `hosts.ini`

```bash
make inventory
# ou um overlay:
make inventory OVERLAY=broetec-core
```

Não edite `hosts.ini` à mão — inclui `vm_role` em `[vms:vars]`.

## Overlay local (gitignored)

```bash
# 1. Adicione entrada em manifest.yml (no seu fork) ou copie um overlay versionado
cp -r broetec-core ../meu-lab   # fora do git — ver .gitignore

# 2. Ou use só env/.env para sobrescrever IP/nome do overlay ativo:
#    OVERLAY=broetec-core
#    VM_IP=10.20.30.45
make inventory
```

## IP errado (ex.: 10.20.30.118 em vez de .40)

O IP estático vem da **reserva DHCP por MAC** na rede `broetec-lab`, não do
`hosts.ini` sozinho. Se renomeou a VM (`node-01` → `broetec-core`), o MAC muda
e a reserva antiga deixa de aplicar → a VM cai no DHCP (.100–.200).

```bash
make network-refresh OVERLAY=broetec-core   # manifest + rede + limpa leases antigos
virsh -c qemu:///system destroy broetec-core && virsh -c qemu:///system start broetec-core
```

`reboot` **não basta** se o dnsmasq ainda tiver lease antiga em
`/var/lib/libvirt/dnsmasq/virbr-broetec.status` (ex.: `.40` preso ao MAC de `node-01`).

Confirme: `virsh net-dumpxml broetec-lab | grep host` deve listar o MAC da VM
(`virsh dumpxml broetec-core | grep "mac address"`).

## Sem internet na VM (IP correcto, ping 8.8.8.8 falha)

Em Fedora com **Docker** no mesmo host, o `firewalld`/`FORWARD` bloqueia o tráfego
`vnet* → wlan0`. O `make up` aplica regras na role `kvm_host` (`firewalld-lab.yml`).

Correcção manual (uma vez):

```bash
make network-refresh OVERLAY=broetec-core
# ou repita make up OVERLAY=broetec-core
```

Teste na VM: `ping -c 2 8.8.8.8` e `curl -I http://example.com`.

## Subir o lab completo (3 VMs)

```bash
make up-lab
```

Cada overlay cria uma VM na mesma rede libvirt `broetec-lab` (10.20.30.0/24).

## Roles futuras por papel

Use `vm_role` em plays condicionais:

```yaml
- hosts: vms
  roles:
    - role: storage_setup
      when: vm_role == 'storage'
```
