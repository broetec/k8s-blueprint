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
#
# Defaults locais (opcional): cp env/.env.example env/.env
# =============================================================================

LAB_ENV_FILE ?= env/.env
# Carrega env/.env (gitignored); ver env/.env.example
-include $(LAB_ENV_FILE)

OVERLAY ?= broetec-core

INVENTORY         ?= provisioning/inventory/$(OVERLAY)/hosts.ini
PLAYBOOK          ?= provisioning/site.yml
# Nomes libvirt = hostname Ansible no grupo [vms] do inventário ativo
_inventory_vms_list := $(shell awk 'BEGIN{v=0} /^\[vms\]$$/{v=1;next} /^\[/{if(v)v=0;next} v&&$$0!~/^[[:space:]]*([#;]|$$)/{print $$1}' "$(INVENTORY)" 2>/dev/null)
_inventory_first_vm := $(firstword $(_inventory_vms_list))
_inventory_first_vm_ip := $(shell awk 'BEGIN{v=0} /^\[vms\]$$/{v=1;next} /^\[/{if(v)v=0;next} v&&$$0!~/^[[:space:]]*([#;]|$$)/{for(i=2;i<=NF;i++){if($$i~/^vm_ip=/){sub(/^vm_ip=/,"",$$i);print $$i;exit} if($$i~/^ansible_host=/){sub(/^ansible_host=/,"",$$i);print $$i;exit}};exit}' "$(INVENTORY)" 2>/dev/null)
VM_NAME           ?= $(if $(_inventory_first_vm),$(_inventory_first_vm),broetec)
VM_IP             ?= $(if $(_inventory_first_vm_ip),$(_inventory_first_vm_ip),10.20.30.40)
KVM_NETWORK       ?= broetec-lab
# Discos/ISOs e cache qcow2 no repo (gitignored); alinhado com group_vars/all.yml
LAB_PATH ?= $(CURDIR)/lab
LAB_DISKS_PATH ?= $(LAB_PATH)/disks
LAB_CACHE_PATH ?= $(LAB_PATH)/cache
ANSIBLE_LAB_EXTRA = -e lab_disks_path=$(LAB_DISKS_PATH) -e lab_cache_dir=$(LAB_CACHE_PATH)

LAB_KEY ?= env/k8s-blueprint
LAB_KEY_ABS := $(CURDIR)/$(LAB_KEY)

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

# Opt-in em env/.env: CREATE_SSH_GLOBAL_KNOWN_HOSTS=true → /etc/ssh/ssh_known_hosts (sudo)
CREATE_SSH_GLOBAL_KNOWN_HOSTS ?= false
# Aceita true/false, 1/0, yes/no (definido em env/.env.example)
SSH_GLOBAL_KNOWN_HOSTS_ENABLED := $(filter 1 true yes TRUE YES,$(CREATE_SSH_GLOBAL_KNOWN_HOSTS))

UV ?= uv
UV_PYTHON ?= 3.12
VENV := $(CURDIR)/.venv
VENV_PYTHON := $(VENV)/bin/python
# Variáveis de ambiente antes de `uv run`; depois ansible-playbook / ansible-galaxy.
ANSIBLE_FRONT = $(ANSIBLE_UNWRAP) no_proxy='*' NO_PROXY='*' ANSIBLE_HOST_KEY_CHECKING=False ANSIBLE_SSH_ARGS='$(ANSIBLE_SSH_ARGS)' ANSIBLE_CONFIG=$(ANSIBLE_CFG) ANSIBLE_FORKS=$(ANSIBLE_FORKS) ANSIBLE_PRIVATE_KEY_FILE=$(LAB_KEY_ABS) $(UV) run --directory "$(CURDIR)"

B := \033[1m
G := \033[32m
Y := \033[33m
R := \033[31m
N := \033[0m

.DEFAULT_GOAL := help
.PHONY: help sync venv keys inventory inventory-overlay network-refresh up up-lab ensure-ssh-global-known-hosts ssh ssh-add-lab ssh-host-key-forget ssh-host-key-refresh status destroy clean

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
	@printf "  Lab data    : $(LAB_PATH) (discos=$(LAB_DISKS_PATH))\n"
	@printf "  Lab key     : $(LAB_KEY) ($(LAB_KEY_ABS))\n"
	@printf "  Ansible     : $(UV) run ansible-playbook | $(ANSIBLE_FLAGS)  forks=$(ANSIBLE_FORKS)  up_split=$(UP_SPLIT)\n"
	@printf "  UV_PYTHON   : $(UV_PYTHON) (make sync UV_PYTHON=3.13)\n"
	@printf "  env/.env    : %s\n" "$(if $(wildcard $(LAB_ENV_FILE)),$(CURDIR)/$(LAB_ENV_FILE),$(Y)ausente — cp env/.env.example env/.env$(N))"
	@printf "  known_hosts : %s (CREATE_SSH_GLOBAL_KNOWN_HOSTS=%s)\n" \
	  "$(if $(SSH_GLOBAL_KNOWN_HOSTS_ENABLED),$(G)/etc/ssh se faltar + ~/.ssh$(N),$(HOME)/.ssh apenas)" \
	  "$(CREATE_SSH_GLOBAL_KNOWN_HOSTS)"
	@printf "  Become (1ª): $(if $(ANSIBLE_BECOME_PASSWORD_FILE),ficheiro,$(B)--ask-become-pass$(N) ou $(B)env/become.pass$(N))\n"
	@printf "  Become (2ª): %s\n" "$(if $(strip $(SUDO_FLAGS_VM)),$(SUDO_FLAGS_VM),sem flags — rocky NOPASSWD)"
	@printf "\n$(B)Multi-overlay:$(N)\n"
	@printf "  make inventory          # gera hosts.ini (manifest.yml)\n"
	@printf "  make network-refresh    # DHCP + rede libvirt + firewalld\n"
	@printf "  make up OVERLAY=broetec-core\n"
	@printf "  make up-lab             # core + storage + monitor\n"
	@printf "  make ssh OVERLAY=<nome>\n"

sync: ## uv sync — instala/atualiza .venv (pyproject.toml + uv.lock)
	@command -v $(UV) >/dev/null 2>&1 || { printf "$(R)Instale uv: https://docs.astral.sh/uv/$(N)\n"; exit 1; }
	@printf "$(Y)==> uv sync (Python $(UV_PYTHON))$(N)\n"
	@cd "$(CURDIR)" && $(ANSIBLE_UNWRAP) $(UV) sync --python $(UV_PYTHON) --frozen
	@test -x '$(VENV_PYTHON)' \
	  || { printf "$(R).venv incompleto após sync — falta $(VENV_PYTHON)$(N)\n"; exit 1; }

venv: sync ## Alias para make sync

COLLECTIONS_REQ ?= provisioning/collections/requirements.yml

inventory: sync ## Gera hosts.ini de todos os overlays (manifest.yml + env/.env)
	@$(ANSIBLE_UNWRAP) $(UV) run python -m app.inventory.cli generate --all

inventory-overlay: sync ## Gera hosts.ini só do OVERLAY ativo
	@$(ANSIBLE_UNWRAP) $(UV) run python -m app.inventory.cli generate -o $(OVERLAY)

network-refresh: inventory-overlay deps ## Reaplica reservas DHCP (manifest) e limpa leases antigos
	@printf "$(Y)==> Atualizar rede libvirt $(KVM_NETWORK) (reservas DHCP)$(N)\n"
	$(ANSIBLE_FRONT) ansible-playbook \
	    -i $(INVENTORY) \
	    $(PLAYBOOK) \
	    --tags kvm_lab \
	    --limit kvm_hosts \
	    $(ANSIBLE_FLAGS) $(SUDO_FLAGS) \
	    -e kvm_network_force_restart=true \
	    $(ANSIBLE_LAB_EXTRA)

deps: sync ## Verifica uv, Ansible, virsh, ssh-keygen e coleções Galaxy (posix, netcommon)
	@test -x '$(VENV_PYTHON)' \
	  || { printf "$(R)Falta $(VENV_PYTHON) — corra $(B)make sync$(N)\n"; exit 1; }
	@$(ANSIBLE_FRONT) ansible-playbook --version >/dev/null 2>&1 \
	  || { printf "$(R)ansible-playbook (uv run) não executa — corra $(B)make sync$(N)\n"; exit 1; }
	@command -v virsh >/dev/null \
	  || { printf "$(R)Falta virsh — instale libvirt-client$(N)\n"; exit 1; }
	@command -v ssh-keygen >/dev/null \
	  || { printf "$(R)Falta ssh-keygen — instale openssh-clients$(N)\n"; exit 1; }
	@$(ANSIBLE_FRONT) ansible-galaxy collection install -r $(COLLECTIONS_REQ)

keys: $(LAB_KEY).pub ## Gera o par de chaves SSH local do lab (idempotente)

$(LAB_KEY).pub:
	@mkdir -p $(dir $(LAB_KEY))
	@printf "$(Y)==> Gerando chave SSH local do lab em $(LAB_KEY)$(N)\n"
	@ssh-keygen -t ed25519 -C "k8s-blueprint" -f $(LAB_KEY) -N "" -q
	@printf "$(G)==> Chave criada (gitignored).$(N)\n"

ensure-ssh-global-known-hosts: ## Cria /etc/ssh/ssh_known_hosts se env CREATE_SSH_GLOBAL_KNOWN_HOSTS=true
ifneq ($(SSH_GLOBAL_KNOWN_HOSTS_ENABLED),)
	@if [ -f /etc/ssh/ssh_known_hosts ]; then \
	  printf "$(G)==> /etc/ssh/ssh_known_hosts já existe.$(N)\n"; \
	else \
	  printf "$(Y)==> CREATE_SSH_GLOBAL_KNOWN_HOSTS=true: a criar /etc/ssh/ssh_known_hosts...$(N)\n"; \
	  sudo install -d -m 755 /etc/ssh; \
	  sudo install -m 644 /dev/null /etc/ssh/ssh_known_hosts; \
	  printf "$(G)==> /etc/ssh/ssh_known_hosts criado.$(N)\n"; \
	fi
else
	@:
endif

up: inventory-overlay deps keys ensure-ssh-global-known-hosts ## Provisiona a VM (idempotente; cria a chave do lab se faltar)
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
	    $(ANSIBLE_LAB_EXTRA)
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
	    $(ANSIBLE_LAB_EXTRA)
else
	$(ANSIBLE_FRONT) ansible-playbook \
	    --forks=$(ANSIBLE_FORKS) \
	    -i $(INVENTORY) \
	    $(PLAYBOOK) \
	    $(ANSIBLE_FLAGS) $(SUDO_FLAGS) \
	    --private-key=$(LAB_KEY_ABS) \
	    -e "ssh_public_key_path=$(LAB_KEY_ABS).pub" \
	    -e "ansible_ssh_private_key_file=$(LAB_KEY_ABS)" \
	    $(ANSIBLE_LAB_EXTRA)
endif
	@printf "\n$(G)==> Pronto.$(N) $(B)make ssh$(N) para entrar na VM.\n"

BROETEC_LAB_OVERLAYS := broetec-core broetec-storage broetec-monitor

up-lab: inventory ## Provisiona os 3 overlays de referência (core, storage, monitor)
	@for o in $(BROETEC_LAB_OVERLAYS); do \
	  printf "\n$(B)==> make up OVERLAY=%s$(N)\n" "$$o"; \
	  $(MAKE) up OVERLAY=$$o || exit $$?; \
	done
	@printf "\n$(G)==> Lab completo (3 VMs).$(N)\n"

ssh: ## Conecta na VM (rocky) com a chave do lab
	@mkdir -p $(HOME)/.ssh && chmod 700 $(HOME)/.ssh 2>/dev/null || true
	@ssh -i $(LAB_KEY_ABS) \
	     -o StrictHostKeyChecking=accept-new \
	     -o UserKnownHostsFile=$(HOME)/.ssh/known_hosts \
	     rocky@$(VM_IP)

ssh-add-lab: ## Adiciona a chave do lab ao ssh-agent (opcional)
	@ssh-add $(LAB_KEY_ABS)

# known_hosts só em $HOME/.ssh (nunca /etc/ssh). Útil ao recriar a VM ou `ssh` manual.
ssh-host-key-forget: ## Remove entradas antigas de $(VM_IP) em $(HOME)/.ssh/known_hosts
	@ssh-keygen -R $(VM_IP) -f $(HOME)/.ssh/known_hosts 2>/dev/null || true
	@ssh-keygen -R $(VM_NAME) -f $(HOME)/.ssh/known_hosts 2>/dev/null || true

ssh-host-key-refresh: ssh-host-key-forget ## Regista a chave da VM em $(HOME)/.ssh/known_hosts
	@printf "$(Y)==> Registando chave SSH de $(VM_IP) em $(HOME)/.ssh/known_hosts...$(N)\n"
	@mkdir -p $(HOME)/.ssh
	@chmod 700 $(HOME)/.ssh 2>/dev/null || true
	@touch $(HOME)/.ssh/known_hosts
	@until ssh-keyscan -H $(VM_IP) 2>/dev/null | grep -q .; do sleep 2; done
	@ssh-keyscan -H $(VM_IP) >> $(HOME)/.ssh/known_hosts 2>/dev/null

status: ## Estado da VM e da rede libvirt
	@printf "$(B)Domínios libvirt:$(N)\n"
	@virsh -c qemu:///system list --all
	@printf "\n$(B)Redes libvirt:$(N)\n"
	@virsh -c qemu:///system net-list --all

destroy: ssh-host-key-forget ## Remove VMs do grupo [vms] do inventário (mantém cache da qcow2 base)
	@if [ -z "$(strip $(_inventory_vms_list))" ]; then \
	  printf "$(R)==> Nenhum host em [vms] em $(INVENTORY)$(N)\n"; exit 1; \
	fi
	@for vm in $(_inventory_vms_list); do \
	  printf "$(Y)==> Removendo VM '%s'...$(N)\n" "$$vm"; \
	  virsh -c qemu:///system destroy "$$vm" 2>/dev/null || true; \
	  virsh -c qemu:///system undefine "$$vm" --remove-all-storage 2>/dev/null || true; \
	  sudo rm -f "$(LAB_DISKS_PATH)/$$vm-seed.iso" 2>/dev/null || true; \
	done
	@printf "$(G)==> VM(s) do overlay removida(s) (cache preservado).$(N)\n"

clean: destroy ## VM + rede + lab/ (discos+cache) + chave do lab
	-virsh -c qemu:///system net-destroy $(KVM_NETWORK)
	-virsh -c qemu:///system net-undefine $(KVM_NETWORK)
	-sudo rm -rf $(LAB_DISKS_PATH) $(LAB_CACHE_PATH)
	-rm -f $(LAB_KEY) $(LAB_KEY).pub
	@printf "$(G)==> Limpo. Próximo $(B)make up$(N) começa do zero.$(N)\n"
