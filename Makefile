# =============================================================================
# Makefile — Broetec k8s-blueprint
# =============================================================================
# Defaults: make/config.mk  |  Ansible: make/ansible.mk  |  SSH: make/ssh.mk
#
# Uso rápido:
#   make setup-host   1ª vez (controlador + host KVM)
#   make up           broetec-core: VM + SO + k8s (01–04; role 00 só em setup-host)
#   make up-all       todas as VMs do manifest.yml
#   make deploy       só k8s (03 + 04) no overlay activo
#
# cp env/.env.example env/.env  — defaults locais opcionais
# =============================================================================

include make/config.mk
include make/ansible.mk
include make/ssh.mk

B := \033[1m
G := \033[32m
Y := \033[33m
R := \033[31m
N := \033[0m

.DEFAULT_GOAL := help
.PHONY: help sync venv deps keys inventory inventory-overlay \
	setup setup-host create-vm prepare-vm install-rke2 deploy-k8s \
	deploy up up-all up-lab

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

sync: ## uv sync — cria/atualiza .venv
	@command -v $(UV) >/dev/null 2>&1 || { printf "$(R)Instale uv: https://docs.astral.sh/uv/$(N)\n"; exit 1; }
	@printf "$(Y)==> uv sync (Python $(UV_PYTHON))$(N)\n"
	@cd "$(CURDIR)" && $(ANSIBLE_UNWRAP) $(UV) sync --python $(UV_PYTHON) --frozen
	@test -x '$(VENV_PYTHON)' \
	  || { printf "$(R).venv incompleto — falta $(VENV_PYTHON)$(N)\n"; exit 1; }

venv: sync ## Alias para make sync

deps: sync ## Verifica .venv, virsh, ssh-keygen e coleções Galaxy
	@test -x '$(VENV_PYTHON)' \
	  || { printf "$(R)Falta $(VENV_PYTHON) — corra $(B)make sync$(N)\n"; exit 1; }
	@$(ANSIBLE_FRONT) ansible-playbook --version >/dev/null 2>&1 \
	  || { printf "$(R)ansible-playbook indisponível — corra $(B)make sync$(N)\n"; exit 1; }
	@command -v virsh >/dev/null \
	  || { printf "$(R)Falta virsh — instale libvirt-client$(N)\n"; exit 1; }
	@command -v ssh-keygen >/dev/null \
	  || { printf "$(R)Falta ssh-keygen$(N)\n"; exit 1; }
	@$(ANSIBLE_FRONT) ansible-galaxy collection install -r $(COLLECTIONS_REQ)

keys: ensure-user-known-hosts $(LAB_KEY).pub ## Gera par SSH do lab (idempotente)

$(LAB_KEY).pub:
	@mkdir -p $(dir $(LAB_KEY))
	@printf "$(Y)==> Gerando chave SSH em $(LAB_KEY)$(N)\n"
	@ssh-keygen -t ed25519 -C "k8s-blueprint" -f $(LAB_KEY) -N "" -q
	@printf "$(G)==> Chave criada.$(N)\n"

inventory: sync ## Gera hosts.ini de todos os overlays
	@$(ANSIBLE_UNWRAP) $(UV) run python -m app.inventory.cli generate --all

inventory-overlay: sync ## Gera hosts.ini só do OVERLAY activo
	@$(ANSIBLE_UNWRAP) $(UV) run python -m app.inventory.cli generate -o $(OVERLAY)

setup: sync deps keys ## Controlador: .venv, Galaxy, chave SSH

setup-host: setup inventory-overlay deps ensure-user-known-hosts ## 1ª vez: controlador + host KVM (role 00)
	@printf "$(B)==> [00] setup-host (OVERLAY=$(OVERLAY), KVM_HOST_BOOTSTRAP=$(KVM_HOST_BOOTSTRAP))$(N)\n"
	$(call run-playbook,$(SETUP_HOST_TAGS),$(SETUP_HOST_SUDO_FLAGS) $(SETUP_HOST_ANSIBLE_FLAGS),$(SETUP_HOST_EXTRA) $(EXTRA))

create-vm: inventory-overlay deps keys ## 01 — qcow2, cloud-init, virt-install
	@printf "$(Y)==> [01] create-vm (OVERLAY=$(OVERLAY))$(N)\n"
	$(call run-playbook,create_vm,$(ANSIBLE_FLAGS),$(EXTRA))

prepare-vm: inventory-overlay deps keys ssh-host-key-refresh ## 02 — SO dentro da VM
	@printf "$(Y)==> [02] prepare-vm (OVERLAY=$(OVERLAY))$(N)\n"
	$(call run-playbook,prepare_vm,$(SUDO_FLAGS_VM) $(ANSIBLE_FLAGS),$(EXTRA))

install-rke2: inventory-overlay deps keys ssh-host-key-refresh ## 03 — RKE2 (stub)
	@printf "$(Y)==> [03] install-rke2 (OVERLAY=$(OVERLAY))$(N)\n"
	$(call run-playbook,install_rke2,$(SUDO_FLAGS_VM) $(ANSIBLE_FLAGS),$(EXTRA))

deploy-k8s: inventory-overlay deps keys ssh-host-key-refresh ## 04 — manifests k8s (stub)
	@printf "$(Y)==> [04] deploy-k8s (OVERLAY=$(OVERLAY))$(N)\n"
	$(call run-playbook,deploy_k8s,$(SUDO_FLAGS_VM) $(ANSIBLE_FLAGS),$(EXTRA))

deploy: install-rke2 deploy-k8s ## 03 + 04 — actualizar só k8s

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

up-lab: up-all ## Alias deprecated → up-all
