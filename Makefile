# =============================================================================
# Makefile — Broetec k8s-blueprint
# =============================================================================
# Ansible e dependências Python vêm de pyproject.toml + uv.lock (ver `make sync`).
#
# Uso rápido:
#   make help     lista targets e config
#   make sync     uv sync (cria/atualiza .venv a partir do lock)
#   make up       provisiona a VM (chave do lab + Ansible)
#   make ssh      SSH para rocky@VM_IP com a chave do lab
# =============================================================================

OVERLAY ?= example

INVENTORY         ?= provisioning/inventory/$(OVERLAY)/hosts.ini
PLAYBOOK          ?= provisioning/site.yml
VM_NAME           ?= node-01
VM_IP             ?= 10.20.30.40
KVM_NETWORK       ?= broetec-lab
LIBVIRT_POOL_PATH ?= /var/lib/libvirt/images

LAB_KEY ?= env/k8s-blueprint
LAB_KEY_ABS := $(CURDIR)/$(LAB_KEY)
ANSIBLE_SSH_COMMON := -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o IdentityFile=$(LAB_KEY_ABS)

# Become host (1ª play): env/become.pass não vazio → ficheiro; senão -K
BECOME_PASS_FILE := $(CURDIR)/env/become.pass
BECOME_PASS_OK := $(shell test -s '$(BECOME_PASS_FILE)' && echo 1)
ifeq ($(ANSIBLE_BECOME_PASSWORD_FILE),)
ifeq ($(BECOME_PASS_OK),1)
ANSIBLE_BECOME_PASSWORD_FILE := $(BECOME_PASS_FILE)
endif
endif
SUDO_FLAGS ?= $(if $(ANSIBLE_BECOME_PASSWORD_FILE),--become-password-file=$(ANSIBLE_BECOME_PASSWORD_FILE),--ask-become-pass)

# 2ª play: sem -K (worker morto); env/vm-become.pass opcional
VM_BECOME_PASS_FILE := $(CURDIR)/env/vm-become.pass
VM_BECOME_PASS_OK := $(shell test -s '$(VM_BECOME_PASS_FILE)' && echo 1)
SUDO_FLAGS_VM ?=
ifeq ($(VM_BECOME_PASS_OK),1)
ifeq ($(strip $(SUDO_FLAGS_VM)),)
SUDO_FLAGS_VM := --become-password-file=$(VM_BECOME_PASS_FILE)
endif
endif
ifneq ($(filter --ask-become-pass -K,$(SUDO_FLAGS_VM)),)
$(error Na 2ª play não use --ask-become-pass/-K. Omita SUDO_FLAGS_VM (NOPASSWD) ou use --become-password-file=...)
endif

ANSIBLE_FLAGS ?= --skip-tags bootstrap
ANSIBLE_FORKS ?= 1
ANSIBLE_CFG ?= $(CURDIR)/ansible.cfg
ANSIBLE_SSH_ARGS ?= -C -o ControlMaster=no -o ControlPersist=no
ANSIBLE_UNWRAP ?= env -u LD_PRELOAD -u LD_LIBRARY_PATH -u PYTHONPATH PYTHONNOUSERSITE=1 MALLOC_ARENA_MAX=2
UP_SPLIT ?= 1

UV ?= uv
UV_PYTHON ?= 3.12
# Variáveis de ambiente antes de `uv run`; depois ansible-playbook / ansible-galaxy.
ANSIBLE_FRONT = $(ANSIBLE_UNWRAP) no_proxy='*' NO_PROXY='*' ANSIBLE_HOST_KEY_CHECKING=False ANSIBLE_SSH_ARGS='$(ANSIBLE_SSH_ARGS)' ANSIBLE_CONFIG=$(ANSIBLE_CFG) ANSIBLE_FORKS=$(ANSIBLE_FORKS) ANSIBLE_PRIVATE_KEY_FILE=$(LAB_KEY_ABS) $(UV) run --directory "$(CURDIR)"

B := \033[1m
G := \033[32m
Y := \033[33m
R := \033[31m
N := \033[0m

.DEFAULT_GOAL := help
.PHONY: help sync venv keys up ssh ssh-add-lab ssh-host-key-forget ssh-host-key-refresh status destroy clean

help: ## Lista os targets disponíveis e a config atual
	@printf "$(B)Targets:$(N)\n"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / { \
		printf "  $(G)%-10s$(N) %s\n", $$1, $$2 \
	}' $(MAKEFILE_LIST)
	@printf "\n$(B)Config atual:$(N)\n"
	@printf "  Overlay     : $(OVERLAY)\n"
	@printf "  Inventory   : $(INVENTORY)\n"
	@printf "  VM          : $(VM_NAME) @ $(VM_IP)\n"
	@printf "  KVM network : $(KVM_NETWORK)\n"
	@printf "  Lab key     : $(LAB_KEY) ($(LAB_KEY_ABS))\n"
	@printf "  Ansible     : $(UV) run ansible-playbook | $(ANSIBLE_FLAGS)  forks=$(ANSIBLE_FORKS)  up_split=$(UP_SPLIT)\n"
	@printf "  UV_PYTHON   : $(UV_PYTHON) (make sync UV_PYTHON=3.13)\n"
	@printf "  Become (1ª): $(if $(ANSIBLE_BECOME_PASSWORD_FILE),ficheiro,$(B)--ask-become-pass$(N) ou $(B)env/become.pass$(N))\n"
	@printf "  Become (2ª): %s\n" "$(if $(strip $(SUDO_FLAGS_VM)),$(SUDO_FLAGS_VM),sem flags — rocky NOPASSWD)"
	@printf "\n$(B)Multi-overlay:$(N)\n"
	@printf "  make up OVERLAY=<nome>\n"
	@printf "  make ssh OVERLAY=<nome> VM_IP=<ip>\n"

sync: ## uv sync — instala/atualiza .venv (pyproject.toml + uv.lock)
	@command -v $(UV) >/dev/null 2>&1 || { printf "$(R)Instale uv: https://docs.astral.sh/uv/$(N)\n"; exit 1; }
	@printf "$(Y)==> uv sync (Python $(UV_PYTHON))$(N)\n"
	@cd "$(CURDIR)" && $(ANSIBLE_UNWRAP) $(UV) sync --python $(UV_PYTHON) --frozen

venv: sync ## Alias para make sync

deps: sync ## Verifica uv, Ansible, virsh, ssh-keygen e coleção ansible.posix
	@$(ANSIBLE_FRONT) ansible-playbook --version >/dev/null 2>&1 \
	  || { printf "$(R)ansible-playbook (uv run) não executa — corra $(B)make sync$(N)\n"; exit 1; }
	@command -v virsh >/dev/null \
	  || { printf "$(R)Falta virsh — instale libvirt-client$(N)\n"; exit 1; }
	@command -v ssh-keygen >/dev/null \
	  || { printf "$(R)Falta ssh-keygen — instale openssh-clients$(N)\n"; exit 1; }
	@$(ANSIBLE_FRONT) ansible-galaxy collection list ansible.posix 2>/dev/null | grep -q ansible.posix \
	  || { printf "$(Y)==> Instalando ansible.posix$(N)\n"; \
	       $(ANSIBLE_FRONT) ansible-galaxy collection install ansible.posix; }

keys: $(LAB_KEY).pub ## Gera o par de chaves SSH local do lab (idempotente)

$(LAB_KEY).pub:
	@mkdir -p $(dir $(LAB_KEY))
	@printf "$(Y)==> Gerando chave SSH local do lab em $(LAB_KEY)$(N)\n"
	@ssh-keygen -t ed25519 -C "k8s-blueprint" -f $(LAB_KEY) -N "" -q
	@printf "$(G)==> Chave criada (gitignored).$(N)\n"

up: deps keys ## Provisiona a VM (idempotente; cria a chave do lab se faltar)
	@printf "$(B)==> Provisionando overlay '$(OVERLAY)'$(N)\n"
ifeq ($(UP_SPLIT),1)
	@printf "$(Y)==> Ansible 1/2 (kvm_lab)$(N)\n"
	$(ANSIBLE_FRONT) ansible-playbook \
	    --forks=$(ANSIBLE_FORKS) \
	    -i $(INVENTORY) \
	    $(PLAYBOOK) \
	    --tags kvm_lab \
	    $(ANSIBLE_FLAGS) $(SUDO_FLAGS) \
	    --private-key=$(LAB_KEY_ABS) \
	    -e "ssh_public_key_path=$(LAB_KEY_ABS).pub" \
	    -e "ansible_ssh_private_key_file=$(LAB_KEY_ABS)" \
	    -e "ansible_ssh_common_args=$(ANSIBLE_SSH_COMMON)"
	@$(MAKE) ssh-host-key-refresh VM_IP=$(VM_IP) VM_NAME=$(VM_NAME)
	@printf "$(Y)==> Ansible 2/2 (os_prepare)$(N)\n"
	$(ANSIBLE_FRONT) ansible-playbook \
	    --forks=$(ANSIBLE_FORKS) \
	    -i $(INVENTORY) \
	    $(PLAYBOOK) \
	    --tags os_prepare \
	    $(ANSIBLE_FLAGS) $(SUDO_FLAGS_VM) \
	    --private-key=$(LAB_KEY_ABS) \
	    -e "ssh_public_key_path=$(LAB_KEY_ABS).pub" \
	    -e "ansible_ssh_private_key_file=$(LAB_KEY_ABS)" \
	    -e "ansible_ssh_common_args=$(ANSIBLE_SSH_COMMON)"
else
	$(ANSIBLE_FRONT) ansible-playbook \
	    --forks=$(ANSIBLE_FORKS) \
	    -i $(INVENTORY) \
	    $(PLAYBOOK) \
	    $(ANSIBLE_FLAGS) $(SUDO_FLAGS) \
	    --private-key=$(LAB_KEY_ABS) \
	    -e "ssh_public_key_path=$(LAB_KEY_ABS).pub" \
	    -e "ansible_ssh_private_key_file=$(LAB_KEY_ABS)" \
	    -e "ansible_ssh_common_args=$(ANSIBLE_SSH_COMMON)"
endif
	@printf "\n$(G)==> Pronto.$(N) $(B)make ssh$(N) para entrar na VM.\n"

ssh: ## Conecta na VM (rocky) com a chave do lab
	@ssh -i $(LAB_KEY_ABS) \
	     -o StrictHostKeyChecking=no \
	     -o UserKnownHostsFile=/dev/null \
	     rocky@$(VM_IP)

ssh-add-lab: ## Adiciona a chave do lab ao ssh-agent (opcional)
	@ssh-add $(LAB_KEY_ABS)

# Paramiko (grupo vms) ignora -o StrictHostKeyChecking; limpa known_hosts ao recriar a VM.
ssh-host-key-forget: ## Remove entradas SSH antigas de $(VM_IP) / $(VM_NAME) em ~/.ssh/known_hosts
	@ssh-keygen -R $(VM_IP) 2>/dev/null || true
	@ssh-keygen -R $(VM_NAME) 2>/dev/null || true

ssh-host-key-refresh: ssh-host-key-forget ## Regista a chave SSH actual da VM (evita prompt yes/no)
	@printf "$(Y)==> Registando chave SSH de $(VM_IP)...$(N)\n"
	@mkdir -p $(HOME)/.ssh
	@chmod 700 $(HOME)/.ssh 2>/dev/null || true
	@until ssh-keyscan -H $(VM_IP) 2>/dev/null | grep -q .; do sleep 2; done
	@ssh-keyscan -H $(VM_IP) >> $(HOME)/.ssh/known_hosts 2>/dev/null

status: ## Estado da VM e da rede libvirt
	@printf "$(B)Domínios libvirt:$(N)\n"
	@virsh -c qemu:///system list --all
	@printf "\n$(B)Redes libvirt:$(N)\n"
	@virsh -c qemu:///system net-list --all

destroy: ssh-host-key-forget ## Remove a VM (mantém cache da qcow2 base)
	-virsh -c qemu:///system destroy $(VM_NAME)
	-virsh -c qemu:///system undefine $(VM_NAME) --remove-all-storage
	-sudo rm -f $(LIBVIRT_POOL_PATH)/$(VM_NAME)-seed.iso
	@printf "$(G)==> VM '$(VM_NAME)' removida (cache preservado).$(N)\n"

clean: destroy ## VM + rede + cache + chave do lab
	-virsh -c qemu:///system net-destroy $(KVM_NETWORK)
	-virsh -c qemu:///system net-undefine $(KVM_NETWORK)
	-sudo rm -rf $(LIBVIRT_POOL_PATH)/_cache
	-rm -f $(LAB_KEY) $(LAB_KEY).pub
	@printf "$(G)==> Limpo. Próximo $(B)make up$(N) começa do zero.$(N)\n"
