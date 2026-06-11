# =============================================================================
# make/targets.mk — playbook pipeline (roles 00–04) and lab flows
# =============================================================================

.PHONY: setup-host create-vm prepare-vm install-rke2 install-k3s install-k8s deploy-k8s deploy up up-all

setup-host: setup inventory-overlay deps ensure-user-known-hosts ## 1ª vez: controlador + host KVM (role 00)
	@printf "$(B)==> [00] setup-host (OVERLAY=$(OVERLAY), KVM_HOST_BOOTSTRAP=$(KVM_HOST_BOOTSTRAP))$(N)\n"
	$(call run-playbook,$(SETUP_HOST_TAGS),$(SETUP_HOST_SUDO_FLAGS) $(SETUP_HOST_ANSIBLE_FLAGS),$(SETUP_HOST_EXTRA) $(EXTRA))

create-vm: inventory-overlay deps keys ## 01 — qcow2, cloud-init, virt-install
	@printf "$(Y)==> [01] create-vm (OVERLAY=$(OVERLAY))$(N)\n"
	$(call run-playbook,create_vm,$(ANSIBLE_FLAGS),$(EXTRA))

prepare-vm: inventory-overlay deps keys ssh-host-key-refresh ## 02 — SO dentro da VM
	@printf "$(Y)==> [02] prepare-vm (OVERLAY=$(OVERLAY))$(N)\n"
	$(call run-playbook,prepare_vm,$(SUDO_FLAGS_VM) $(ANSIBLE_FLAGS),$(EXTRA))

install-rke2: inventory-overlay deps keys ssh-host-key-refresh ## 03 — instalar RKE2 nas VMs
	@printf "$(Y)==> [03] install-rke2 (OVERLAY=$(OVERLAY))$(N)\n"
	$(call run-playbook,install_k8s,$(SUDO_FLAGS_VM) $(ANSIBLE_FLAGS),-e k8s_distribution=rke2 $(EXTRA))

install-k3s: inventory-overlay deps keys ssh-host-key-refresh ## 03 — instalar k3s nas VMs
	@printf "$(Y)==> [03] install-k3s (OVERLAY=$(OVERLAY))$(N)\n"
	$(call run-playbook,install_k8s,$(SUDO_FLAGS_VM) $(ANSIBLE_FLAGS),-e k8s_distribution=k3s $(EXTRA))

install-k8s: inventory-overlay deps keys ssh-host-key-refresh ## 03 — instalar Kubernetes (usa K8S_DISTRIBUTION)
	@printf "$(Y)==> [03] install-k8s (OVERLAY=$(OVERLAY), K8S_DISTRIBUTION=$(K8S_DISTRIBUTION))$(N)\n"
	$(call run-playbook,install_k8s,$(SUDO_FLAGS_VM) $(ANSIBLE_FLAGS),$(K8S_DISTRIBUTION_EXTRA) $(EXTRA))

deploy-k8s: inventory-overlay deps keys ssh-host-key-refresh ## 04 — manifests k8s (stub)
	@printf "$(Y)==> [04] deploy-k8s (OVERLAY=$(OVERLAY))$(N)\n"
	$(call run-playbook,deploy_k8s,$(SUDO_FLAGS_VM) $(ANSIBLE_FLAGS),$(EXTRA))

deploy: install-k8s deploy-k8s ## 03 + 04 — instalar k8s + deploy manifests (usa K8S_DISTRIBUTION)

up: inventory-overlay deps keys ensure-ssh-global-known-hosts ## VM + SO + k8s (01–04)
	@printf "$(B)==> up OVERLAY='$(OVERLAY)'$(N)\n"
	@$(SUBMAKE) -f $(CURDIR)/Makefile create-vm OVERLAY=$(OVERLAY)
	@$(SUBMAKE) -f $(CURDIR)/Makefile prepare-vm OVERLAY=$(OVERLAY)
	@$(SUBMAKE) -f $(CURDIR)/Makefile deploy OVERLAY=$(OVERLAY)
	@printf "\n$(G)==> Pronto.$(N) $(B)make ssh$(N) para entrar na VM.\n"

up-all: inventory deps keys ensure-ssh-global-known-hosts ## Sobe todos os overlays
	@for o in $(LAB_OVERLAYS); do \
	  printf "\n$(B)==> make up OVERLAY=%s$(N)\n" "$$o"; \
	  $(SUBMAKE) -f $(CURDIR)/Makefile up OVERLAY=$$o || exit $$?; \
	done
	@printf "\n$(G)==> Lab completo ($(words $(LAB_OVERLAYS)) VMs).$(N)\n"
