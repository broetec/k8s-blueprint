# =============================================================================
# connection_plugins/libssh.py — drop-in wrapper over ansible.netcommon.libssh
# =============================================================================
#
# Problem
#   pylibssh 1.4.x does not expose SSH_OPTIONS_GLOBAL_KNOWNHOSTS in OPTS_MAP.
#   The config_file= parameter sent by the upstream plugin via Session.connect()
#   is silently ignored (it is absent from both OPTS_MAP and OPTS_DIR_MAP).
#   Result: libssh always tries to read /etc/ssh/ssh_known_hosts (compiled-in
#   default), which does not exist → written to Python worker stderr → Ansible
#   surfaces it as [WARNING].
#
# Solution
#   1. Add 'global_knownhosts': 35 to OPTS_MAP at runtime.
#      SSH_OPTIONS_GLOBAL_KNOWNHOSTS = 35 (confirmed in includes/libssh.pxd).
#      OPTS_MAP is a plain Python dict — mutable without recompiling anything.
#
#   2. Subclass Session (Session.connect is a Python def, not cdef) to inject
#      global_knownhosts=stub_path before ssh_connect() is called.
#      set_ssh_options() already handles strings via ssh_options_set(...,
#      PyBytes_AS_STRING(value)).
#
#   3. Replace Session in the upstream module's global namespace so that
#      _connect_uncached() (which does self.ssh = Session()) uses the subclass.
#
#   4. Transport name 'libssh' (short form) → Ansible searches connection_plugins
#      directories before collections → preserves ansible_libssh_* var prefix.
#
# Activation
#   ansible.cfg: connection_plugins = provisioning/connection_plugins
#   manifest.yml / inventory: ansible_connection=libssh
# =============================================================================
from __future__ import annotations

import logging
import os
import re

# ── 0. Surgical filter for SSH2_MSG_GLOBAL_REQUEST (type 80) ─────────────────
# The SSH server (OpenSSH >= 6.8) sends hostkeys-00@openssh.com after
# authentication to advertise its host keys. libssh has no handler for this
# global request type → logs SSH_LOG_WARN → Python callback → worker stderr →
# Ansible captures as [WARNING]. The filter drops only this specific message;
# all other libssh warnings and errors continue to propagate normally.
# Fails open: if the message text changes in a future libssh release, the
# warning returns rather than being silently over-suppressed.

class _PacketType80Filter(logging.Filter):
    """Drop the benign SSH2_MSG_GLOBAL_REQUEST unhandled-packet warning."""

    _RE = re.compile(r'ssh_packet_process.*packet type 80', re.IGNORECASE)

    def filter(self, record: logging.LogRecord) -> bool:
        return not self._RE.search(record.getMessage())


logging.getLogger('ansible-pylibssh').addFilter(_PacketType80Filter())

# ── 1. Expose SSH_OPTIONS_GLOBAL_KNOWNHOSTS in pylibssh's OPTS_MAP ───────────
import pylibsshext.session as _ps

_SSH_OPTIONS_GLOBAL_KNOWNHOSTS = 35
_ps.OPTS_MAP.setdefault('global_knownhosts', _SSH_OPTIONS_GLOBAL_KNOWNHOSTS)

# ── 2. Import the upstream module (after patching OPTS_MAP) ──────────────────
import ansible_collections.ansible.netcommon.plugins.connection.libssh as _up
from pylibsshext.session import Session as _BaseSession

# Inherit all options and inventory var mappings (ansible_libssh_*)
DOCUMENTATION = _up.DOCUMENTATION


# ── 3. Subclass that injects global_knownhosts into every Session.connect() ──
class _PatchedSession(_BaseSession):
    """Session with SSH_OPTIONS_GLOBAL_KNOWNHOSTS set before ssh_connect."""

    # Path to the empty stub file; set before each instance is created.
    _stub: str | None = None

    def connect(self, **kwargs: object) -> None:
        if self._stub and 'global_knownhosts' not in kwargs:
            kwargs['global_knownhosts'] = self._stub
        return super().connect(**kwargs)


# ── 4. Replace Session in the upstream module ─────────────────────────────────
# _connect_uncached() looks up Session by name in the module where the function
# is defined; replacing _up.Session makes it use our subclass.
_up.Session = _PatchedSession


# ── 5. Connection wrapper ─────────────────────────────────────────────────────
class Connection(_up.Connection):
    """Wrapper over ansible.netcommon.libssh with GlobalKnownHostsFile support."""

    transport = 'libssh'

    def _connect_uncached(self) -> object:
        env_dir = os.path.join(os.getcwd(), 'env')
        stub = os.path.join(env_dir, 'global-known_hosts_stub')
        os.makedirs(env_dir, exist_ok=True)
        open(stub, 'a').close()  # touch — create if missing, no-op if present
        _PatchedSession._stub = stub
        return super()._connect_uncached()
