# provisioning/connection_plugins

Local Ansible connection plugins that extend or patch collection-provided plugins.

## `libssh.py` — patched wrapper over `ansible.netcommon.libssh`

### Why this plugin exists

The VM plays use `ansible.netcommon.libssh` as the connection transport.
This avoids forking `/usr/bin/ssh` per task, which prevents the
"A worker was found in a dead state" failure that occurs when Ansible runs
inside the Cursor IDE integrated terminal (AppImage) with multiplexed SSH sockets.

However, `ansible-pylibssh` 1.4.x has two gaps that cause Ansible to capture
libssh log output as `[WARNING]` entries on **every** task:

```
[WARNING]: WorkerProcess for [broetec-core/TASK: 02_prepare_vm : Alive check — SSH without become]
errantly sent data directly to stderr instead of using Display:
    ssh_strict_fopen: Failed to open a file /etc/ssh/ssh_known_hosts for reading: No such file or directory
    ssh_packet_process: Couldn't do anything with packet type 80
```

The two messages have different root causes and are fixed independently.

---

### Warning 1 — `ssh_strict_fopen: Failed to open /etc/ssh/ssh_known_hosts`

#### Root cause

libssh uses `/etc/ssh/ssh_known_hosts` as the global known-hosts file by
default (compiled-in path, `SSH_OPTIONS_GLOBAL_KNOWNHOSTS`). The inventory
already configures `ansible_libssh_config_file=env/ssh_config_lab`, which
sets `GlobalKnownHostsFile` to a project-local empty stub. However, the
upstream plugin passes `config_file=` as a keyword argument to
`Session.connect()`, and pylibssh silently ignores it — `config_file` is
absent from both `OPTS_MAP` and `OPTS_DIR_MAP`:

```python
# pylibsshext/session.pyx — OPTS_MAP (pylibssh 1.4.x)
OPTS_MAP = {
    "knownhosts": libssh.SSH_OPTIONS_KNOWNHOSTS,   # user known-hosts only
    # SSH_OPTIONS_GLOBAL_KNOWNHOSTS (35) is NOT present
    ...
}

# Session.connect():
for key in kwargs:
    if (key in OPTS_MAP or key in OPTS_DIR_MAP) and (kwargs[key] is not None):
        self.set_ssh_options(key, kwargs[key])   # config_file= is dropped here
```

Because the option is never applied, libssh always falls back to
`/etc/ssh/ssh_known_hosts`. That file does not exist on the controller →
libssh logs a `SSH_LOG_WARN` via its C callback → Python's
`logging.getLogger("ansible-pylibssh")` → root logger → worker stderr →
Ansible reports `[WARNING]`. Creating `/etc/ssh/ssh_known_hosts` would fix it
but requires root on the controller, which is outside the project's scope.

#### Fix

1. Add `'global_knownhosts': 35` to `OPTS_MAP` at import time.
   `SSH_OPTIONS_GLOBAL_KNOWNHOSTS = 35` is the enum value in `libssh.h`,
   confirmed via `pylibsshext/includes/libssh.pxd`. `OPTS_MAP` is a plain
   Python `dict` and is mutable without recompiling anything.

2. Subclass `Session` (whose `connect()` is a Python `def`, not `cdef`) to
   inject `global_knownhosts=stub_path` into every `connect()` call.
   `set_ssh_options()` already handles string values via
   `ssh_options_set(session, key_m, PyBytes_AS_STRING(value))`.

3. Replace `Session` in the upstream module's global namespace so that
   `_connect_uncached()` — which does `self.ssh = Session()` and looks up
   `Session` by name in its defining module — transparently uses the subclass.

4. `_connect_uncached()` auto-creates `env/global-known_hosts_stub` (empty
   file) before each connection so the fix is self-sufficient even if
   `make ensure-user-known-hosts` has not been run.

---

### Warning 2 — `ssh_packet_process: Couldn't do anything with packet type 80`

#### Root cause

SSH packet type 80 is `SSH2_MSG_GLOBAL_REQUEST`. OpenSSH server (>= 6.8)
sends a `hostkeys-00@openssh.com` global request after authentication to
advertise its current host keys to the client. libssh has no handler for this
message type, so it logs a `SSH_LOG_WARN` entry. The log travels the same
path as warning 1 (C callback → Python logging → root logger → worker stderr)
and is captured by Ansible as `[WARNING]`.

This is entirely server-initiated and unrelated to the known-hosts file.
The alternative fix would be to set `UpdateHostKeys no` in
`/etc/ssh/sshd_config.d/` on each guest VM, but that would affect all SSH
clients connecting to those VMs and requires a task in `02_prepare_vm`.

#### Fix

A surgical `logging.Filter` on the `ansible-pylibssh` logger that matches
only this specific message and drops it before it reaches the root logger.
All other libssh warnings and errors continue to propagate normally.
The filter **fails open**: if the message text changes in a future libssh
release, the warning returns rather than being silently over-suppressed.

---

### Activation

```ini
# provisioning/ansible.cfg
[defaults]
connection_plugins = provisioning/connection_plugins
```

```yaml
# provisioning/inventory/manifest.yml
defaults:
  ansible_connection_vm: libssh   # short name → local plugin found first
```

The short transport name `libssh` causes Ansible to search
`connection_plugins` directories before installed collections, so this plugin
takes precedence over `ansible.netcommon.libssh`. The `ansible_libssh_*`
inventory variable prefix is preserved because the `transport` attribute is
set to `'libssh'`.

---

### Dependency pinning

`ansible.netcommon` is pinned in `collections/requirements.yml` (`==8.5.2`)
because this plugin depends on the internal symbols `_connect_uncached` and
the module-level `Session` reference in `ansible.netcommon.libssh`. A
major/minor bump that renames or moves those symbols would break the wrapper
silently. The pin should be updated intentionally alongside a review of this
file.
