# =============================================================================
# Makefile — Broetec k8s-blueprint
# =============================================================================
# Entry point: help + includes. Targets live under make/*.mk
#
# Quick start: make setup-host (once) → make up → make ssh
# Full reference: make/README.md
# cp env/.env.example env/.env  — optional local defaults
# =============================================================================

include make/config.mk
include make/colors.mk
include make/ansible.mk
include make/setup.mk
include make/inventory.mk
include make/ssh.mk
include make/targets.mk

.DEFAULT_GOAL := help
.PHONY: help

help: ## Lista targets e config actual
	@printf "$(B)Setup (1ª vez):$(N)\n"
	@printf "  $(G)setup$(N)          uv sync + deps + chaves\n"
	@printf "  $(G)setup-host$(N)     setup + role 00 host KVM (bootstrap via env/.env)\n"
	@printf "\n$(B)Lab (cotidiano):$(N)\n"
	@printf "  $(G)up$(N)              create-vm + prepare-vm + deploy (OVERLAY=$(OVERLAY))\n"
	@printf "  $(G)up-all$(N)          todos os overlays ($(LAB_OVERLAYS))\n"
	@printf "  $(G)deploy$(N)          install-rke2 + deploy-k8s\n"
	@printf "\n$(B)Etapas (01–04):$(N)\n"
	@printf "  $(G)create-vm$(N)      01 — libvirt + qcow2\n"
	@printf "  $(G)prepare-vm$(N)     02 — SO na VM\n"
	@printf "  $(G)install-rke2$(N)   03 — RKE2 (stub)\n"
	@printf "  $(G)deploy-k8s$(N)     04 — manifests (stub)\n"
	@printf "\n$(B)Operações:$(N)\n"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / { \
		if ($$1 !~ /^(setup|setup-host|create-vm|prepare-vm|install-rke2|deploy-k8s|deploy|up|up-all)$$/) \
		  printf "  $(G)%-18s$(N) %s\n", $$1, $$2 \
	}' $(MAKEFILE_LIST)
	@printf "\n$(B)Config:$(N) OVERLAY=$(OVERLAY)  VM=$(VM_NAME)@$(VM_IP)  KVM_HOST_BOOTSTRAP=$(KVM_HOST_BOOTSTRAP)\n"
	@printf "  inventory=$(INVENTORY)\n"
	@printf "  env/.env: %s\n" "$(if $(wildcard $(LAB_ENV_FILE)),ok,$(Y)cp env/.env.example env/.env$(N))"
	@printf "\n$(B)Exemplos:$(N)\n"
	@printf "  make up OVERLAY=broetec-storage\n"
	@printf "  make deploy OVERLAY=broetec-core\n"
	@printf "  make ssh OVERLAY=broetec-monitor\n"
