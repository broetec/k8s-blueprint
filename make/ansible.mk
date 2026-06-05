# =============================================================================
# make/ansible.mk — ansible-playbook macro (single-line recipe)
# =============================================================================

# setup-host (role 00): whether host bootstrap runs (KVM packages + libvirtd).
# Controlled by KVM_HOST_BOOTSTRAP in env/.env or on the make command line.
# When off, setup-host still applies network (and firewall if KVM_HOST_FIREWALL=true).
_setup_host_tags_bootstrap := install_kvm,bootstrap
SETUP_HOST_TAGS := $(if $(KVM_HOST_BOOTSTRAP_ON),$(_setup_host_tags_bootstrap),install_kvm)
SETUP_HOST_ANSIBLE_FLAGS := $(if $(KVM_HOST_BOOTSTRAP_ON),,--skip-tags bootstrap)
SETUP_HOST_EXTRA := \
  $(if $(KVM_HOST_BOOTSTRAP_ON),,-e kvm_host_bootstrap=false) \
  $(if $(KVM_HOST_FIREWALL_ON),-e kvm_host_firewall=true,-e kvm_host_firewall=false)

# Host plays 00/01: sudo only when bootstrap or host firewall runs (see site.yml become: false).
SETUP_HOST_SUDO_FLAGS := $(if $(filter 1,$(KVM_HOST_BOOTSTRAP_ON) $(KVM_HOST_FIREWALL_ON)),$(SUDO_FLAGS),)

# Shared wrapper for all playbook targets (inventory, keys, lab paths).
define run-playbook
$(ANSIBLE_FRONT) ansible-playbook --forks=$(ANSIBLE_FORKS) -i $(INVENTORY) $(PLAYBOOK) --tags $(1) $(2) --private-key=$(LAB_KEY_ABS) -e ssh_public_key_path=$(LAB_KEY_ABS).pub -e ansible_ssh_private_key_file=$(LAB_KEY_ABS) $(ANSIBLE_LAB_EXTRA) $(3)
endef
