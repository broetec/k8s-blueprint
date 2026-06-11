# `03_install_rke2` — RKE2 installation

Installs and configures RKE2 on Rocky Linux VMs (single-node or multi-node).

**Invocation:** `make install-rke2`, `make deploy`, or `make up` (default distribution).

## Selection

`k8s_distribution: rke2` is the default in `provisioning/inventory/_shared/group_vars/all.yml`.  
Override per overlay in `90_local.yml` or at runtime:

```bash
make install-rke2 OVERLAY=broetec-core
```

## Key variables (`defaults/main.yml`)

| Variable | Default | Description |
|---|---|---|
| `rke2_version` | `""` | Pin version (e.g. `v1.31.4+rke2r1`); empty = latest stable |
| `rke2_channel` | `stable` | Install channel |
| `rke2_node_ip` | `{{ vm_ip }}` | Intra-cluster IP |
| `rke2_tls_san` | `[]` | Extra TLS SANs for the API server cert |
| `rke2_cni` | `cilium` | CNI plugin |
| `rke2_disable_kube_proxy` | `true` | Let Cilium replace kube-proxy |
| `rke2_disable` | `[rke2-ingress-nginx]` | Built-in components to skip |
| `rke2_cilium_version` | `v1.18.7` | Pinned Cilium image tag |
| `rke2_cilium_operator_replicas` | `1` | Single-node safe (avoids port conflicts) |
| `rke2_secrets_encryption` | `true` | Encrypt secrets at rest |
| `rke2_write_kubeconfig_mode` | `0644` | Kubeconfig file permissions |
| `rke2_configure_shell` | `true` | Add `kubectl`/`helm` completions and aliases |
| `rke2_disable_firewalld` | `true` | Stop/disable firewalld before install |

## Tags

| Tag | What it runs |
|---|---|
| `rke2_preflight` | firewalld, NetworkManager, sysctl |
| `rke2_config` | `/etc/rancher/rke2/config.yaml` + Cilium HelmChartConfig |
| `rke2_install` | download script, enable `rke2-server`, wait Ready |
| `rke2_user` | kubeconfig, shell profile |

## Reference

- [RKE2 docs](https://docs.rke2.io)
- [Server config reference](https://docs.rke2.io/reference/server_config)
- [Bootstrap guide](../../../docs/bootstrap/README.md)
