# Inventário Ansible — overlays Broetec

## Overlays versionados

| Overlay | VM (libvirt) | IP | Papel (`vm_role`) |
|---------|--------------|-----|-------------------|
| `broetec-core` | broetec-core | 10.20.30.40 | `core` |
| `broetec-storage` | broetec-storage | 10.20.30.50 | `storage` |
| `broetec-monitor` | broetec-monitor | 10.20.30.60 | `monitor` |

Todos partilham o mesmo playbook (`provisioning/site.yml`) e roles
(`00_install_kvm`, `01_create_vm`, `02_prepare_vm`).

## Camadas de variáveis (por overlay)

Cada overlay tem `group_vars/all/` com merge automático (ordem alfabética):

| Ficheiro | Origem | Função |
|----------|--------|--------|
| `00_shared.yml` | symlink → `_shared/group_vars/all.yml` | Base comum (rede, imagem, cloud-init) |
| `50_overlay.generated.yml` | **gerado** (`make inventory`) | `vm_role`, `overlay_id`, `vars` do manifest |
| `90_local.yml` | **versionado, manual** | Overrides por máquina (disco, vCPUs, etc.) |

Só para o grupo **`[kvm_hosts]`** (`localhost` na play KVM), o gerador cria também:

| Ficheiro | Origem | Função |
|----------|--------|--------|
| `group_vars/kvm_hosts.yml` | symlink → `_shared/group_vars/kvm_hosts.yml` | Python do controlador (`.venv` via `ansible_playbook_python`) |

Edite **`manifest.yml`** para identidade (IP, role, vars declarativas) e **`90_local.yml`** para ajustes finos por overlay.

### `become` nas VMs (opcional)

Variáveis só do grupo `[vms]` podem ir em `group_vars/vms.yml` (crie manualmente no overlay, não é gerado). Ex.: `ansible_become_password` quando `cloud_init.sudo_nopasswd: false` — use ficheiro local `env/vm-rocky.pass` (gitignored) ou Ansible Vault; ver comentários em `provisioning/README.md`.

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

O IP estático vem do **`network-config` no seed ISO** (cloud-init), gerado por
`01_create_vm` a partir de `vm_ip` / `vm_mac` no inventário (`make inventory`).
Se mudou IP ou MAC no `manifest.yml` sem recriar a VM, o SO pode manter o endereço antigo
ou cair no pool DHCP da rede (`.100–.200`).

```bash
make inventory OVERLAY=broetec-core
make destroy OVERLAY=broetec-core    # ou apague lab/disks/<vm>-seed.iso e a VM
make up OVERLAY=broetec-core
```

Confirme o MAC: `virsh dumpxml broetec-core | grep "mac address"` deve coincidir com
`vm_mac` em `hosts.ini`. Confirme o IP na VM: `ip -4 addr show`.

## Sem internet na VM (IP correcto, ping 8.8.8.8 falha)

Em hosts com **Docker** e firewall activo, a cadeia `FORWARD` pode bloquear tráfego
`vnet* → wlan0`. Defina `KVM_HOST_FIREWALL=true` em `env/.env` e corra `make install-kvm`
(a role `00_install_kvm` detecta firewalld, ufw ou iptables e aplica regras NAT).

Correcção manual (uma vez):

```bash
make network-refresh OVERLAY=broetec-core
# ou repita make up OVERLAY=broetec-core
```

Teste na VM: `ping -c 2 8.8.8.8` e `curl -I http://example.com`.

## Subir o lab completo (3 VMs)

```bash
make up-all
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
