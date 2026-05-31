# =============================================================================
# make/ansible.mk — macro ansible-playbook (uma linha — evita split de recipe)
# =============================================================================

_install_kvm_tags_bootstrap := install_kvm,bootstrap
INSTALL_KVM_TAGS := $(if $(KVM_HOST_BOOTSTRAP_ON),$(_install_kvm_tags_bootstrap),install_kvm)
INSTALL_KVM_ANSIBLE_FLAGS := $(if $(KVM_HOST_BOOTSTRAP_ON),,--skip-tags bootstrap)
INSTALL_KVM_EXTRA := $(if $(KVM_HOST_BOOTSTRAP_ON),,-e kvm_host_bootstrap=false)

define run-playbook
$(ANSIBLE_FRONT) ansible-playbook --forks=$(ANSIBLE_FORKS) -i $(INVENTORY) $(PLAYBOOK) --tags $(1) $(2) --private-key=$(LAB_KEY_ABS) -e ssh_public_key_path=$(LAB_KEY_ABS).pub -e ansible_ssh_private_key_file=$(LAB_KEY_ABS) $(ANSIBLE_LAB_EXTRA) $(3)
endef
