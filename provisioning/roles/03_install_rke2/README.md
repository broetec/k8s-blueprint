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
| `rke2_kubeconfig_user` | `{{ ansible_user }}` | User that receives `~/.kube/config` |
| `rke2_fine_tuning_enabled` | `true` | Master switch for `tasks/fine_tuning.yml` |
| `rke2_systemd_hardening` | `true` | `rke2-server.service` drop-in (CPU/I/O priority, resilient restart) |
| `rke2_systemd_nice` | `-10` | CPU nice value for the control plane process |
| `rke2_healthcheck_enabled` | `false` | External API watchdog timer (opt-in; see below) |
| `rke2_healthcheck_timer_interval` | `5min` | How often the watchdog runs after boot delay |

## Tags

| Tag | What it runs |
|---|---|
| `rke2_preflight` | NetworkManager (firewalld off and sysctl in role 02) |
| `rke2_config` | `/etc/rancher/rke2/config.yaml` + Cilium HelmChartConfig |
| `rke2_install` | download script, enable `rke2-server`, wait Ready |
| `rke2_fine_tuning` | systemd drop-in hardening + optional API health watchdog |
| `rke2_user` | kubeconfig |

## Fine tuning

Implemented in [`tasks/fine_tuning.yml`](tasks/fine_tuning.yml). Runs after the cluster
is Ready (`install.yml`). Disable entirely with `rke2_fine_tuning_enabled: false`.

### Systemd hardening (`rke2_systemd_hardening: true`)

RKE2 runs etcd in the same process as the rest of the control plane
(`rke2-server.service`). The role writes
`/etc/systemd/system/rke2-server.service.d/override.conf` to:

1. **Raise CPU/I/O priority** — helps API and etcd election stability when the
   node has contended disk or CPU (`Nice`, `IOSchedulingClass`, `IOSchedulingPriority`).
2. **Remove systemd start limits** — the stock unit has `Restart=always` but
   `StartLimitBurst=5`. After slow-disk events (cloud backup, `fstrim`), systemd
   marks the unit `failed` and stops retrying until manual intervention.
   `StartLimitIntervalSec=0` and `StartLimitBurst=0` retry indefinitely.
3. **Extend start/stop timeouts** — slow etcd WAL recovery gets up to 20 min
   (`TimeoutStartSec`).

The drop-in triggers one `rke2-server` restart when first applied; subsequent
Ansible runs are no-op.

> **Note:** `Nice=-10` requires adequate permissions. If systemd rejects it, try
> `-5` or check `ulimit`/system policy limits.

### API health watchdog (`rke2_healthcheck_enabled: false`)

Opt-in for single-node VPS. Installs `/usr/local/sbin/rke2-healthcheck.sh` and
enables `rke2-healthcheck.timer` (first run 10 min after boot, then every 5 min).

Even with `Restart=always`, three scenarios leave `rke2-server` stuck:

1. **Live process, dead API** — etcd blocked on `fsync` or apiserver not
   responding to `/readyz`; systemd never restarts because the main process is alive.
2. **Orphan containerd shims** — after a violent failure, shims keep control-plane
   ports (`:6443`, `:2379`, `:2380`, `:10250`) and etcd WAL open. The official
   `/usr/local/bin/rke2-killall.sh` clears them without touching the data directory.
3. **Cilium data plane half-programmed** — with `kubeProxyReplacement: true` and
   Gateway API enabled, `cilium-agent` may start before the apiserver is ready and
   leave Envoy embedded without listeners (`loading 0 listener(s)`). The node shows
   `Ready` but external traffic on `:80`/`:443` fails.

The watchdog escalates gradually using a strike counter in `/run/rke2-healthcheck.strikes`:

| State | Action |
|---|---|
| API responds | Reset strike counter |
| API dead, strike 1 | `systemctl restart rke2-server` → `wait_for_api` → `reconcile_dataplane` |
| API dead, strike ≥ 2 (≥ 5 min) | `stop` → `rke2-killall.sh` → `start` → `wait_for_api` → `reconcile_dataplane` |
| `rke2-server` inactive | `systemctl start rke2-server` (reconcile deferred to next cycle) |

`reconcile_dataplane` restarts `cilium-operator` and `ds/cilium`, optionally runs
`conntrack -F` (requires `conntrack-tools`, installed when
`rke2_healthcheck_install_conntrack: true`), and deletes `Failed` pods.

Enable in `90_local.yml`:

```yaml
rke2_healthcheck_enabled: true
```

Run only fine-tuning tasks:

```bash
make install-rke2 OVERLAY=broetec-core -- --tags rke2_fine_tuning
```

Verify after install:

```bash
systemctl cat rke2-server.service | grep -E 'Nice|IOScheduling|Restart|Timeout|StartLimit'
systemctl list-timers rke2-healthcheck.timer   # when watchdog enabled
journalctl -t rke2-healthcheck -n 20
cat /run/rke2-healthcheck.strikes 2>/dev/null || echo "0 (healthy)"
```

**Manual recovery** after an incident where shims survived a reboot:

```bash
sudo /usr/local/bin/rke2-killall.sh
sudo systemctl start rke2-server.service

until kubectl --kubeconfig=/etc/rancher/rke2/rke2.yaml get --raw=/readyz >/dev/null 2>&1; do
  sleep 5
done
kubectl -n kube-system rollout restart deploy/cilium-operator
kubectl -n kube-system rollout status   deploy/cilium-operator --timeout=3m
kubectl -n kube-system rollout restart ds/cilium
kubectl -n kube-system rollout status   ds/cilium --timeout=5m
```

> **Caution:** the watchdog restarts the entire control plane and `rke2-killall.sh`
> tears down all pods on the node. On HA clusters (3+ servers) prefer a local
> `/readyz` check and let etcd handle failover; on single-node clusters it is the
> safety net that avoids prolonged downtime without a manual reboot.

## Reference

- [RKE2 docs](https://docs.rke2.io)
- [Server config reference](https://docs.rke2.io/reference/server_config)
- [Bootstrap guide](../../../docs/bootstrap/README.md)
