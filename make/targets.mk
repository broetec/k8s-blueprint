# =============================================================================
# make/targets.mk — playbook pipeline (roles 00–04) and lab flows
# =============================================================================

.PHONY: setup-host create-vm prepare-vm install-rke2 install-k3s install-k8s deploy-k8s reset-k8s redeploy-k8s deploy up up-all golden golden-seal

setup-host: setup inventory-overlay deps ensure-user-known-hosts ## 1ª vez: controlador + host KVM (role 00)
	@printf "$(B)==> [00] setup-host (OVERLAY=$(OVERLAY), KVM_HOST_BOOTSTRAP=$(KVM_HOST_BOOTSTRAP))$(N)\n"
	$(call run-playbook,$(SETUP_HOST_TAGS),$(SETUP_HOST_SUDO_FLAGS) $(SETUP_HOST_ANSIBLE_FLAGS),$(SETUP_HOST_EXTRA) $(EXTRA))

create-vm: inventory-overlay deps keys ## 01 — qcow2, cloud-init, virt-install
	@printf "$(Y)==> [01] create-vm (OVERLAY=$(OVERLAY))$(N)\n"
	$(call run-playbook,create_vm,$(ANSIBLE_FLAGS),$(EXTRA))

prepare-vm: inventory-overlay deps keys ssh-host-key-refresh ## 02 — SO dentro da VM
	@printf "$(Y)==> [02] prepare-vm (OVERLAY=$(OVERLAY))$(N)\n"
	$(call run-playbook,prepare_vm,$(SUDO_FLAGS_VM) $(ANSIBLE_FLAGS),$(EXTRA))

install-rke2: inventory-overlay deps keys ssh-host-key-refresh ## 03 — instalar RKE2 (RKE2_VERSION=vX.Y.Z+rke2rN)
	@printf "$(Y)==> [03] install-rke2 (OVERLAY=$(OVERLAY)$(if $(RKE2_VERSION), RKE2_VERSION=$(RKE2_VERSION))$(N)\n"
	$(call run-playbook,install_k8s,$(SUDO_FLAGS_VM) $(ANSIBLE_FLAGS),-e k8s_distribution=rke2$(if $(strip $(RKE2_VERSION)), -e rke2_version=$(RKE2_VERSION)) $(EXTRA))

install-k3s: inventory-overlay deps keys ssh-host-key-refresh ## 03 — instalar k3s (K3S_VERSION=vX.Y.Z+k3sN)
	@printf "$(Y)==> [03] install-k3s (OVERLAY=$(OVERLAY)$(if $(K3S_VERSION), K3S_VERSION=$(K3S_VERSION))$(N)\n"
	$(call run-playbook,install_k8s,$(SUDO_FLAGS_VM) $(ANSIBLE_FLAGS),-e k8s_distribution=k3s$(if $(strip $(K3S_VERSION)), -e k3s_version=$(K3S_VERSION)) $(EXTRA))

install-k8s: inventory-overlay deps keys ssh-host-key-refresh ## 03 — instalar Kubernetes (K8S_DISTRIBUTION + *_VERSION)
	@printf "$(Y)==> [03] install-k8s (OVERLAY=$(OVERLAY), K8S_DISTRIBUTION=$(K8S_DISTRIBUTION)$(if $(RKE2_VERSION), RKE2_VERSION=$(RKE2_VERSION))$(if $(K3S_VERSION), K3S_VERSION=$(K3S_VERSION)))$(N)\n"
	$(call run-playbook,install_k8s,$(SUDO_FLAGS_VM) $(ANSIBLE_FLAGS),$(K8S_DISTRIBUTION_EXTRA) $(EXTRA))

deploy-k8s: inventory-overlay deps keys ssh-host-key-refresh ## 04 — bootstrap k8s (cluster-config, cert-manager, argocd; SEALED_SECRETS=true p/ sealed-secrets)
	@printf "$(Y)==> [04] deploy-k8s (OVERLAY=$(OVERLAY), SEALED_SECRETS=$(SEALED_SECRETS))$(N)\n"
	$(call run-playbook,deploy_k8s,$(SUDO_FLAGS_VM) $(ANSIBLE_FLAGS),-e sealed_secrets_enabled=$(SEALED_SECRETS) $(EXTRA))

reset-k8s: inventory-overlay deps keys ssh-host-key-refresh ## 04⁻¹ — destruir todos os namespaces/releases (exceto os protegidos) SEM desinstalar o cluster
	@printf "$(R)==> [reset] reset-k8s (OVERLAY=$(OVERLAY)) — apaga tudo exceto namespaces protegidos$(N)\n"
	$(call run-playbook,reset_k8s,$(SUDO_FLAGS_VM) $(ANSIBLE_FLAGS),$(EXTRA))

redeploy-k8s: reset-k8s deploy-k8s ## reset-k8s + deploy-k8s — reaplicar a etapa 04 do zero

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

# --- Golden image (role golden_image) -------------------------------------------
# Builder VM = overlay GOLDEN_OVERLAY, sempre a partir da imagem Rocky crua.
GOLDEN_OVERLAY ?= golden
GOLDEN_TAGS := golden_seal,golden_export
GOLDEN_IMAGE ?= $(LAB_CACHE_PATH)/golden-rocky10.qcow2

golden: ## SO preparado em lab/cache/golden-*.qcow2 — base das VMs novas (refazer p/ atualizar pacotes)
	@for disk in $(LAB_DISKS_PATH)/*.qcow2; do \
	  [ -e "$$disk" ] || continue; \
	  if qemu-img info -U "$$disk" 2>/dev/null | grep -Fq "backing file: $(GOLDEN_IMAGE)"; then \
	    printf "$(R)==> %s usa a golden como backing file — make destroy antes de refazer.$(N)\n" "$$disk"; exit 1; \
	  fi; \
	done
	@printf "$(B)==> golden (builder OVERLAY=$(GOLDEN_OVERLAY))$(N)\n"
	@$(SUBMAKE) -f $(CURDIR)/Makefile destroy OVERLAY=$(GOLDEN_OVERLAY)
	@$(SUBMAKE) -f $(CURDIR)/Makefile create-vm OVERLAY=$(GOLDEN_OVERLAY) USE_GOLDEN=false
	@$(SUBMAKE) -f $(CURDIR)/Makefile prepare-vm OVERLAY=$(GOLDEN_OVERLAY) USE_GOLDEN=false
	@$(SUBMAKE) -f $(CURDIR)/Makefile golden-seal OVERLAY=$(GOLDEN_OVERLAY)
	@$(SUBMAKE) -f $(CURDIR)/Makefile destroy OVERLAY=$(GOLDEN_OVERLAY)
	@printf "\n$(G)==> Golden pronta:$(N) $(GOLDEN_IMAGE)\n"

golden-seal: inventory-overlay deps keys ssh-host-key-refresh ## (interno) sela o builder e exporta o disco
	@printf "$(Y)==> [golden] seal + export (OVERLAY=$(OVERLAY))$(N)\n"
	$(call run-playbook,$(GOLDEN_TAGS),$(SUDO_FLAGS_VM) $(ANSIBLE_FLAGS),$(EXTRA))
