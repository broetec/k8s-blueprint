# =============================================================================
# connection_plugins/libssh.py — drop-in sobre ansible.netcommon.libssh
# =============================================================================
#
# Problema
#   pylibssh 1.4.x não expõe SSH_OPTIONS_GLOBAL_KNOWNHOSTS em OPTS_MAP.
#   O parâmetro config_file= que o plugin upstream envia em Session.connect()
#   é ignorado silenciosamente (não está em OPTS_MAP nem em OPTS_DIR_MAP).
#   Resultado: libssh usa sempre /etc/ssh/ssh_known_hosts (default compilado),
#   que não existe → stderr do worker Python → Ansible mostra [WARNING].
#
# Solução
#   1. Adiciona 'global_knownhosts': 35 a OPTS_MAP em tempo de execução.
#      SSH_OPTIONS_GLOBAL_KNOWNHOSTS = 35 (confirmado em includes/libssh.pxd).
#      OPTS_MAP é um dict Python normal — mutável sem recompilar nada.
#
#   2. Subclassifica Session (Session.connect é um def Python, não cdef)
#      para injectar global_knownhosts=stub_path antes do ssh_connect().
#      set_ssh_options() já trata strings via ssh_options_set(..., PyBytes_AS_STRING).
#
#   3. Substitui Session no módulo upstream pelo nome global, para que
#      _connect_uncached() (que faz self.ssh = Session()) use a subclasse.
#
#   4. Transport name 'libssh' (curto) → Ansible procura em connection_plugins
#      antes de collections → mantém prefixo ansible_libssh_* nas vars.
#
# Activação
#   ansible.cfg: connection_plugins = provisioning/connection_plugins
#   manifest.yml / inventário: ansible_connection=libssh
# =============================================================================
from __future__ import annotations

import os

# ── 1. Expor SSH_OPTIONS_GLOBAL_KNOWNHOSTS no OPTS_MAP do pylibssh ───────────
import pylibsshext.session as _ps

_SSH_OPTIONS_GLOBAL_KNOWNHOSTS = 35
_ps.OPTS_MAP.setdefault('global_knownhosts', _SSH_OPTIONS_GLOBAL_KNOWNHOSTS)

# ── 2. Importar o módulo upstream (depois do patch ao OPTS_MAP) ───────────────
import ansible_collections.ansible.netcommon.plugins.connection.libssh as _up
from pylibsshext.session import Session as _BaseSession

# Herda todas as opções e mapeamentos de vars de inventário (ansible_libssh_*)
DOCUMENTATION = _up.DOCUMENTATION


# ── 3. Subclasse que injeta global_knownhosts em cada Session.connect() ──────
class _PatchedSession(_BaseSession):
    """Session com SSH_OPTIONS_GLOBAL_KNOWNHOSTS definido antes de ssh_connect."""

    # Caminho para o stub vazio; definido antes de criar a instância.
    _stub: str | None = None

    def connect(self, **kwargs: object) -> None:
        if self._stub and 'global_knownhosts' not in kwargs:
            kwargs['global_knownhosts'] = self._stub
        return super().connect(**kwargs)


# ── 4. Substituir Session no módulo upstream ──────────────────────────────────
# _connect_uncached() faz `self.ssh = Session()` usando o nome global do módulo
# onde está definida a função — ao trocar _up.Session usamos a subclasse.
_up.Session = _PatchedSession


# ── 5. Connection wrapper ─────────────────────────────────────────────────────
class Connection(_up.Connection):
    """Wrapper sobre ansible.netcommon.libssh com GlobalKnownHostsFile."""

    transport = 'libssh'

    def _connect_uncached(self) -> object:
        env_dir = os.path.join(os.getcwd(), 'env')
        stub = os.path.join(env_dir, 'global-known_hosts_stub')
        os.makedirs(env_dir, exist_ok=True)
        open(stub, 'a').close()  # touch — cria se não existir, não trunca se existir
        _PatchedSession._stub = stub
        return super()._connect_uncached()
