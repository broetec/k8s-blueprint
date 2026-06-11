# =============================================================================
# make/config.mk — defaults e env local (carregado pelo Makefile raiz)
# =============================================================================

LAB_ENV_FILE ?= env/.env
-include $(LAB_ENV_FILE)

# --- Inventário / overlay ------------------------------------------------------
OVERLAY ?= broetec-core
INVENTORY ?= provisioning/inventory/$(OVERLAY)/hosts.ini
PLAYBOOK ?= provisioning/site.yml
LAB_OVERLAYS := broetec-core broetec-storage broetec-monitor

# Nomes libvirt = hostname Ansible no grupo [vms] do inventário activo
_inventory_vms_list := $(shell awk 'BEGIN{v=0} /^\[vms\]$$/{v=1;next} /^\[/{if(v)v=0;next} v&&$$0!~/^[[:space:]]*([#;]|$$)/{print $$1}' "$(INVENTORY)" 2>/dev/null)
_inventory_first_vm := $(firstword $(_inventory_vms_list))
_inventory_first_vm_ip := $(shell awk 'BEGIN{v=0} /^\[vms\]$$/{v=1;next} /^\[/{if(v)v=0;next} v&&$$0!~/^[[:space:]]*([#;]|$$)/{for(i=2;i<=NF;i++){if($$i~/^vm_ip=/){sub(/^vm_ip=/,"",$$i);print $$i;exit} if($$i~/^ansible_host=/){sub(/^ansible_host=/,"",$$i);print $$i;exit}};exit}' "$(INVENTORY)" 2>/dev/null)
_inventory_ansible_user := $(shell awk 'BEGIN{v=0} /^\[vms:vars\]$$/{v=1;next} /^\[/{if(v)v=0;next} v&&$$0~/^ansible_user=/{sub(/^ansible_user=/,"");print;exit}' "$(INVENTORY)" 2>/dev/null)
VM_NAME ?= $(if $(_inventory_first_vm),$(_inventory_first_vm),broetec-core)
VM_IP ?= $(if $(_inventory_first_vm_ip),$(_inventory_first_vm_ip),10.20.30.40)
VM_USER ?= $(if $(_inventory_ansible_user),$(_inventory_ansible_user),broetec)
KVM_NETWORK ?= broetec-lab

# --- Lab (discos, cache, chave SSH) --------------------------------------------
LAB_PATH ?= $(CURDIR)/lab
LAB_DISKS_PATH ?= $(LAB_PATH)/disks
LAB_CACHE_PATH ?= $(LAB_PATH)/cache
ANSIBLE_LAB_EXTRA = -e lab_disks_path=$(LAB_DISKS_PATH) -e lab_cache_dir=$(LAB_CACHE_PATH)
LAB_KEY ?= env/k8s-blueprint
LAB_KEY_ABS := $(CURDIR)/$(LAB_KEY)

# --- Become (host vs VM) -------------------------------------------------------
BECOME_PASS_FILE := $(CURDIR)/env/become.pass
BECOME_PASS_OK := $(shell test -s '$(BECOME_PASS_FILE)' && echo 1)
ifeq ($(ANSIBLE_BECOME_PASSWORD_FILE),)
ifeq ($(BECOME_PASS_OK),1)
ANSIBLE_BECOME_PASSWORD_FILE := $(BECOME_PASS_FILE)
endif
endif
SUDO_FLAGS ?= $(if $(ANSIBLE_BECOME_PASSWORD_FILE),--become-password-file=$(ANSIBLE_BECOME_PASSWORD_FILE),--ask-become-pass)

VM_BECOME_PASS_FILE := $(CURDIR)/env/vm-become.pass
VM_BECOME_PASS_OK := $(shell test -s '$(VM_BECOME_PASS_FILE)' && echo 1)
SUDO_FLAGS_VM ?=
ifeq ($(VM_BECOME_PASS_OK),1)
ifeq ($(strip $(SUDO_FLAGS_VM)),)
SUDO_FLAGS_VM := --become-password-file=$(VM_BECOME_PASS_FILE)
endif
endif
ifneq ($(filter --ask-become-pass -K,$(SUDO_FLAGS_VM)),)
$(error Plays em vms: não use --ask-become-pass/-K. Use env/vm-become.pass ou cloud_init.sudo_nopasswd.)
endif

# --- Kubernetes distribution (role 03) ----------------------------------------
# Which distribution play 4 installs: rke2 (default) or k3s.
# Override in env/.env (K8S_DISTRIBUTION=k3s) or on the command line.
# make install-rke2 and make install-k3s set this automatically.
K8S_DISTRIBUTION ?= rke2
K8S_DISTRIBUTION_EXTRA := -e k8s_distribution=$(K8S_DISTRIBUTION)

# --- Host KVM (role 00) --------------------------------------------------------
# Bootstrap: instala pacotes libvirt no host. Default activo; desactivar em env/.env.
KVM_HOST_BOOTSTRAP ?= true
KVM_HOST_BOOTSTRAP_ON := $(filter 1 true yes TRUE YES,$(KVM_HOST_BOOTSTRAP))

# Firewall: regras NAT/FORWARD para VMs lab. Default desactivado; activar em env/.env.
KVM_HOST_FIREWALL ?= false
KVM_HOST_FIREWALL_ON := $(filter 1 true yes TRUE YES,$(KVM_HOST_FIREWALL))

# --- Ansible -------------------------------------------------------------------
ANSIBLE_FLAGS ?=
ANSIBLE_FORKS ?= 1
ANSIBLE_CFG ?= $(CURDIR)/provisioning/ansible.cfg
ANSIBLE_UNWRAP ?= env -u LD_PRELOAD -u LD_LIBRARY_PATH -u PYTHONPATH PYTHONNOUSERSITE=1 MALLOC_ARENA_MAX=2
COLLECTIONS_REQ ?= provisioning/collections/requirements.yml

# --- SSH controlador (user-space) ----------------------------------------------
LAB_SSH_CONFIG ?= env/ssh_config_lab
LAB_SSH_CONFIG_EXAMPLE ?= env/ssh_config_lab.example
LAB_SSH_GLOBAL_STUB ?= env/global-known_hosts_stub

ANSIBLE_PRUNE_SSH_KNOWN_HOSTS ?= false

# --- SSH global known_hosts (opt-in root) --------------------------------------
CREATE_SSH_GLOBAL_KNOWN_HOSTS ?= false
SSH_GLOBAL_KNOWN_HOSTS_ENABLED := $(filter 1 true yes TRUE YES,$(CREATE_SSH_GLOBAL_KNOWN_HOSTS))

# --- Sub-makes (Cursor redefine $(MAKE) para cursor.appimage) ------------------
# Invocações recursivas devem usar SUBMAKE, não $(MAKE).
SUBMAKE := $(if $(wildcard /usr/bin/make),/usr/bin/make,$(if $(wildcard /usr/bin/gmake),/usr/bin/gmake,make))

# --- Python / uv ---------------------------------------------------------------
UV ?= uv
UV_PYTHON ?= 3.12
VENV := $(CURDIR)/.venv
VENV_PYTHON := $(VENV)/bin/python
ANSIBLE_FRONT = $(ANSIBLE_UNWRAP) no_proxy='*' NO_PROXY='*' ANSIBLE_HOST_KEY_CHECKING=False ANSIBLE_CONFIG=$(ANSIBLE_CFG) ANSIBLE_FORKS=$(ANSIBLE_FORKS) ANSIBLE_PRIVATE_KEY_FILE=$(LAB_KEY_ABS) $(UV) run --directory "$(CURDIR)"
