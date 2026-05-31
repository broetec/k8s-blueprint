# =============================================================================
# Makefile — Broetec k8s-blueprint
# =============================================================================
# Defaults: make/config.mk  |  Ansible: make/ansible.mk  |  SSH: make/ssh.mk
#
# Uso rápido:
#   make setup-host   1ª vez (controlador + host KVM)
#   make up           broetec-core: VM + SO + k8s (00–04, sem install-kvm)
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
.PHONY: help sync venv deps keys inventory inventory-overlay network-refresh \
	setup setup-host install-kvm create-vm prepare-vm install-rke2 deploy-k8s \
	deploy up up-all up-lab \
	_play-install-kvm _play-create-vm _play-prepare-vm _play-install-rke2 _play-deploy-k8s

help: ## Lista targets e config actual
	@printf "$(B)Setup (1ª vez):$(N)\n"
	@printf "  $(G)setup$(N)          uv sync + deps + chaves\n"
	@printf "  $(G)setup-host$(N)     setup + install-kvm (BOOTSTRAP=1)\n"
	@printf "\n$(B)Lab (cotidiano):$(N)\n"
	@printf "  $(G)up$(N)              create-vm + prepare-vm + deploy (OVERLAY=$(OVERLAY))\n"
	@printf "  $(G)up-all$(N)          todos os overlays ($(LAB_OVERLAYS))\n"
	@printf "  $(G)deploy$(N)          install-rke2 + deploy-k8s\n"
	@printf "\n$(B)Etapas (00–04):$(N)\n"
	@printf "  $(G)install-kvm$(N)    00 — host KVM/rede\n"
	@printf "  $(G)create-vm$(N)      01 — libvirt + qcow2\n"
	@printf "  $(G)prepare-vm$(N)     02 — SO na VM\n"
	@printf "  $(G)install-rke2$(N)   03 — RKE2 (stub)\n"
	@printf "  $(G)deploy-k8s$(N)     04 — manifests (stub)\n"
	@printf "\n$(B)Operações:$(N)\n"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / { \
		if ($$1 !~ /^(setup|setup-host|install-kvm|create-vm|prepare-vm|install-rke2|deploy-k8s|deploy|up|up-all)$$/) \
		  printf "  $(G)%-18s$(N) %s\n", $$1, $$2 \
	}' $(MAKEFILE_LIST)
	@printf "\n$(B)Config:$(N) OVERLAY=$(OVERLAY)  VM=$(VM_NAME)@$(VM_IP)  $(ANSIBLE_FLAGS)\n"
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

keys: $(LAB_KEY).pub ## Gera par SSH do lab (idempotente)

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

setup-host: setup ## 1ª vez: controlador + host KVM (bootstrap)
	@printf "$(B)==> setup-host: install-kvm com BOOTSTRAP=1$(N)\n"
	@$(MAKE) install-kvm BOOTSTRAP=1

install-kvm: inventory-overlay deps ## 00 — host KVM, rede libvirt, firewalld
	@printf "$(Y)==> [00] install-kvm (OVERLAY=$(OVERLAY))$(N)\n"
	@$(MAKE) _play-install-kvm

network-refresh: inventory-overlay deps ## Reaplica rede libvirt e reservas DHCP
	@printf "$(Y)==> network-refresh $(KVM_NETWORK)$(N)\n"
	@$(MAKE) _play-install-kvm EXTRA='-e kvm_network_force_restart=true --limit kvm_hosts'

create-vm: inventory-overlay deps keys ## 01 — qcow2, cloud-init, virt-install
	@printf "$(Y)==> [01] create-vm (OVERLAY=$(OVERLAY))$(N)\n"
	@$(MAKE) _play-create-vm

prepare-vm: inventory-overlay deps keys ## 02 — SO dentro da VM
	@printf "$(Y)==> [02] prepare-vm (OVERLAY=$(OVERLAY))$(N)\n"
	@$(MAKE) _play-prepare-vm

install-rke2: inventory-overlay deps keys ## 03 — RKE2 (stub)
	@printf "$(Y)==> [03] install-rke2 (OVERLAY=$(OVERLAY))$(N)\n"
	@$(MAKE) _play-install-rke2

deploy-k8s: inventory-overlay deps keys ## 04 — manifests k8s (stub)
	@printf "$(Y)==> [04] deploy-k8s (OVERLAY=$(OVERLAY))$(N)\n"
	@$(MAKE) _play-deploy-k8s

deploy: install-rke2 deploy-k8s ## 03 + 04 — actualizar só k8s

up: inventory-overlay deps keys ensure-ssh-global-known-hosts ## VM + SO + k8s (01–04)
	@printf "$(B)==> up OVERLAY='$(OVERLAY)'$(N)\n"
	@$(MAKE) create-vm OVERLAY=$(OVERLAY)
	@$(MAKE) ssh-host-key-refresh VM_IP=$(VM_IP) VM_NAME=$(VM_NAME)
	@$(MAKE) prepare-vm OVERLAY=$(OVERLAY)
	@$(MAKE) deploy OVERLAY=$(OVERLAY)
	@printf "\n$(G)==> Pronto.$(N) $(B)make ssh$(N) para entrar na VM.\n"

up-all: inventory deps keys ensure-ssh-global-known-hosts ## Sobe todos os overlays
	@for o in $(LAB_OVERLAYS); do \
	  printf "\n$(B)==> make up OVERLAY=%s$(N)\n" "$$o"; \
	  $(MAKE) up OVERLAY=$$o || exit $$?; \
	done
	@printf "\n$(G)==> Lab completo ($(words $(LAB_OVERLAYS)) VMs).$(N)\n"

up-lab: up-all ## Alias deprecated → up-all

# Passa EXTRA=... para _play-* (network-refresh)
_play-install-kvm:
	$(call run-playbook,$(if $(filter 1,$(BOOTSTRAP)),install_kvm,bootstrap,install_kvm),$(SUDO_FLAGS) $(INSTALL_KVM_ANSIBLE_FLAGS),$(EXTRA))

_play-create-vm:
	$(call run-playbook,create_vm,$(SUDO_FLAGS) $(ANSIBLE_FLAGS),$(EXTRA))

_play-prepare-vm:
	$(call run-playbook,prepare_vm,$(SUDO_FLAGS_VM) $(ANSIBLE_FLAGS),$(EXTRA))

_play-install-rke2:
	$(call run-playbook,install_rke2,$(SUDO_FLAGS_VM) $(ANSIBLE_FLAGS),$(EXTRA))

_play-deploy-k8s:
	$(call run-playbook,deploy_k8s,$(SUDO_FLAGS_VM) $(ANSIBLE_FLAGS),$(EXTRA))
