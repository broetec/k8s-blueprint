# =============================================================================
# make/ansible.mk — ansible-playbook macro (single-line recipe)
# =============================================================================

# install-kvm only: whether role 00 runs host bootstrap (KVM packages + libvirtd).
# Controlled by KVM_HOST_BOOTSTRAP in env/.env or on the make command line.
# When off, install-kvm still applies network (and firewall if KVM_HOST_FIREWALL=true).
_install_kvm_tags_bootstrap := install_kvm,bootstrap
INSTALL_KVM_TAGS := $(if $(KVM_HOST_BOOTSTRAP_ON),$(_install_kvm_tags_bootstrap),install_kvm)
INSTALL_KVM_ANSIBLE_FLAGS := $(if $(KVM_HOST_BOOTSTRAP_ON),,--skip-tags bootstrap)
INSTALL_KVM_EXTRA := \
  $(if $(KVM_HOST_BOOTSTRAP_ON),,-e kvm_host_bootstrap=false) \
  $(if $(KVM_HOST_FIREWALL_ON),-e kvm_host_firewall=true,-e kvm_host_firewall=false)

# Shared wrapper for all playbook targets (inventory, keys, lab paths).
define run-playbook
$(ANSIBLE_FRONT) ansible-playbook --forks=$(ANSIBLE_FORKS) -i $(INVENTORY) $(PLAYBOOK) --tags $(1) $(2) --private-key=$(LAB_KEY_ABS) -e ssh_public_key_path=$(LAB_KEY_ABS).pub -e ansible_ssh_private_key_file=$(LAB_KEY_ABS) $(ANSIBLE_LAB_EXTRA) $(3)
endef
