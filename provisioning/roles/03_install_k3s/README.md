# `03_install_k3s` — k3s installation

Installs and configures k3s on Rocky Linux VMs.

**Invocation:** `make install-k3s`, `make deploy`, or `make up` with `k8s_distribution=k3s`.

## Selection

Set `k8s_distribution: k3s` in `provisioning/inventory/_shared/group_vars/all.yml`  
or per overlay in `90_local.yml`, or at runtime:

```bash
make install-k3s OVERLAY=broetec-core
# or
make install-rke2 OVERLAY=broetec-core  # with K8S_DISTRIBUTION=k3s in env/.env
```

## Key variables (`defaults/main.yml`)

| Variable | Default | Description |
|---|---|---|
| `k3s_version` | `""` | Pin version (e.g. `v1.31.4+k3s1`); empty = latest stable |
| `k3s_channel` | `stable` | Install channel |
| `k3s_node_ip` | `{{ vm_ip }}` | Intra-cluster IP |
| `k3s_tls_san` | `[]` | Extra TLS SANs for the API server cert |
| `k3s_flannel_backend` | `vxlan` | `none` to bring your own CNI |
| `k3s_disable` | `[traefik, servicelb]` | Built-in components to skip |
| `k3s_write_kubeconfig_mode` | `0644` | Kubeconfig file permissions |
| `k3s_configure_shell` | `true` | Add `kubectl` completions and aliases |
| `k3s_disable_firewalld` | `true` | Stop/disable firewalld before install |

## Tags

| Tag | What it runs |
|---|---|
| `k3s_preflight` | firewalld, NetworkManager, sysctl |
| `k3s_config` | `/etc/rancher/k3s/config.yaml` |
| `k3s_install` | download script, enable service, wait Ready |
| `k3s_user` | kubeconfig, shell profile |

## Reference

- [k3s docs](https://docs.k3s.io)
- [Install options](https://docs.k3s.io/installation/configuration)
