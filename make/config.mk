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
VM_NAME ?= $(if $(_inventory_first_vm),$(_inventory_first_vm),broetec-core)
VM_IP ?= $(if $(_inventory_first_vm_ip),$(_inventory_first_vm_ip),10.20.30.40)
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
$(error Plays em vms: não use --ask-become-pass/-K. Use env/vm-become.pass ou rocky NOPASSWD.)
endif

# --- Ansible -------------------------------------------------------------------
ANSIBLE_FLAGS ?= --skip-tags bootstrap
ANSIBLE_FORKS ?= 1
ANSIBLE_CFG ?= $(CURDIR)/provisioning/ansible.cfg
ANSIBLE_SSH_ARGS ?= -C -o ControlMaster=no -o ControlPersist=no
ANSIBLE_UNWRAP ?= env -u LD_PRELOAD -u LD_LIBRARY_PATH -u PYTHONPATH PYTHONNOUSERSITE=1 MALLOC_ARENA_MAX=2
COLLECTIONS_REQ ?= provisioning/collections/requirements.yml

# --- SSH global known_hosts (opt-in) -------------------------------------------
CREATE_SSH_GLOBAL_KNOWN_HOSTS ?= false
SSH_GLOBAL_KNOWN_HOSTS_ENABLED := $(filter 1 true yes TRUE YES,$(CREATE_SSH_GLOBAL_KNOWN_HOSTS))

# --- Python / uv ---------------------------------------------------------------
UV ?= uv
UV_PYTHON ?= 3.12
VENV := $(CURDIR)/.venv
VENV_PYTHON := $(VENV)/bin/python
ANSIBLE_FRONT = $(ANSIBLE_UNWRAP) no_proxy='*' NO_PROXY='*' ANSIBLE_HOST_KEY_CHECKING=False ANSIBLE_SSH_ARGS='$(ANSIBLE_SSH_ARGS)' ANSIBLE_CONFIG=$(ANSIBLE_CFG) ANSIBLE_FORKS=$(ANSIBLE_FORKS) ANSIBLE_PRIVATE_KEY_FILE=$(LAB_KEY_ABS) $(UV) run --directory "$(CURDIR)"
