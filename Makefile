# =============================================================================
# Makefile — Broetec k8s-blueprint
# =============================================================================
# Entry point único para o ciclo de vida da infra de laboratório (KVM + Rocky).
#
# Uso rápido:
#   make help          lista todos os targets
#   make up            provisiona a VM (idempotente; cria chave do lab se faltar)
#   make ssh           conecta na VM via SSH com a chave do lab
#   make status        mostra estado da VM e da rede libvirt
#   make destroy       para e remove a VM (mantém cache da qcow2)
#   make clean         destrói tudo (VM + rede libvirt + cache + chave do lab)
#
# Multi-overlay (a configuração por ambiente vive em provisioning/inventory/):
#   make up OVERLAY=local
#
# Para overlays com VM/IP/rede diferentes do default, sobrescreva na linha
# de comando (ou edite as variáveis abaixo, se for o seu único uso):
#   make ssh     OVERLAY=local VM_IP=10.20.30.50
#   make destroy OVERLAY=local VM_NAME=node-02 KVM_NETWORK=outra-rede
# =============================================================================

# ---- Seleção de overlay (apenas troca o caminho do inventário Ansible) ------
OVERLAY ?= example

# ---- Defaults (válidos para o overlay "example"; sobrescreva se necessário) -
INVENTORY         ?= provisioning/inventory/$(OVERLAY)/hosts.ini
PLAYBOOK          ?= provisioning/site.yml
VM_NAME           ?= node-01
VM_IP             ?= 10.20.30.40
KVM_NETWORK       ?= broetec-lab
LIBVIRT_POOL_PATH ?= /var/lib/libvirt/images

# ---- Chave SSH local do lab (gerada e armazenada em env/) -------------------
# Nome explícito para não confundir com outras chaves no disco.
LAB_KEY ?= env/k8s-blueprint
# Caminho absoluto — necessário para Ansible e ssh usarem sempre o mesmo ficheiro.
LAB_KEY_ABS := $(CURDIR)/$(LAB_KEY)
# Opções SSH para o grupo `vms` (IdentityFile obriga a chave do lab, não ~/.ssh/id_*).
ANSIBLE_SSH_COMMON := -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o IdentityFile=$(LAB_KEY_ABS)

# Flags repassáveis ao ansible-playbook. Para sudo passwordless em todos os hosts:
#   make up SUDO_FLAGS=
#
# Fork + prompt interactivo (--ask-become-pass) pode causar "worker dead"; opções:
#   printf '%s\n' 'senha_sudo_do_HOST' > env/become.pass && chmod 600 env/become.pass
#   (se existir e tiver conteúdo, é usado automaticamente na 1ª play; ficheiro vazio → ignora-se)
#   ou: make up ANSIBLE_BECOME_PASSWORD_FILE=/abs/caminho/become.pass
BECOME_PASS_FILE := $(CURDIR)/env/become.pass
BECOME_PASS_OK := $(shell test -s '$(BECOME_PASS_FILE)' && echo 1)
ifeq ($(ANSIBLE_BECOME_PASSWORD_FILE),)
ifeq ($(BECOME_PASS_OK),1)
ANSIBLE_BECOME_PASSWORD_FILE := $(BECOME_PASS_FILE)
endif
endif
SUDO_FLAGS ?= $(if $(ANSIBLE_BECOME_PASSWORD_FILE),--become-password-file=$(ANSIBLE_BECOME_PASSWORD_FILE),--ask-become-pass)
# 2ª play (os_prepare em `vms`): NUNCA --ask-become-pass/-K — fork + TTY → "A worker was found in a dead state".
# Por defeito o rocky tem sudo NOPASSWD (cloud_init): deixe SUDO_FLAGS_VM vazio.
# Se o overlay exigir senha de sudo na VM: ficheiro (não vazio) ou --become-password-file=...
VM_BECOME_PASS_FILE := $(CURDIR)/env/vm-become.pass
VM_BECOME_PASS_OK := $(shell test -s '$(VM_BECOME_PASS_FILE)' && echo 1)
SUDO_FLAGS_VM ?=
ifeq ($(VM_BECOME_PASS_OK),1)
ifeq ($(strip $(SUDO_FLAGS_VM)),)
SUDO_FLAGS_VM := --become-password-file=$(VM_BECOME_PASS_FILE)
endif
endif
ifneq ($(filter --ask-become-pass -K,$(SUDO_FLAGS_VM)),)
$(error Na 2ª play (os_prepare) não use --ask-become-pass nem -K: causa "A worker was found in a dead state". Omita SUDO_FLAGS_VM se o rocky tiver sudo NOPASSWD (overlay example), ou crie env/vm-become.pass (uma linha, chmod 600) / use SUDO_FLAGS_VM=--become-password-file=CAMINHO)
endif
# Por defeito salta a tag `bootstrap` (dnf não existe em Bazzite/immutable).
# Fedora/RHEL tradicional com dnf: make up ANSIBLE_FLAGS=
ANSIBLE_FLAGS ?= --skip-tags bootstrap
# Um único fork evita "A worker was found in a dead state" (OOM / Cursor / agent).
ANSIBLE_FORKS ?= 1
ANSIBLE_CFG ?= $(CURDIR)/ansible.cfg
# Python do venv (modo clássico, USE_UV=0): primeiro existente entre 3.12 → 3.13 → 3.14 → python3 em /usr/bin.
# Com USE_UV=1: `uv venv --python $(UV_PYTHON)` descarrega o Python indicado (ex. 3.12) sem rpm-ostree — requer `uv` no PATH (https://docs.astral.sh/uv/).
# Ex.: make venv USE_UV=1   ou   make venv USE_UV=1 UV_PYTHON=3.13
USE_UV ?= 0
UV_PYTHON ?= 3.12
VENV_PYTHON ?= $(shell for p in /usr/bin/python3.12 /usr/bin/python3.13 /usr/bin/python3.14 /usr/bin/python3; do test -x "$$p" && echo "$$p" && exit 0; done; command -v python3)
# USE_VENV=1 → 1ª play com .venv (kvm_vm); 2ª play (SSH) prefere /usr/bin/ansible-core (outro Python) — o 3.14 no .venv
# ainda pode dar "A worker was found in a dead state" ao fazer fork. Override: ANSIBLE_PLAYBOOK_VM=/caminho/ansible-playbook
ifeq ($(USE_VENV),1)
ANSIBLE_PLAYBOOK_KVM := $(CURDIR)/.venv/bin/ansible-playbook
ANSIBLE_PLAYBOOK := $(ANSIBLE_PLAYBOOK_KVM)
else
# Preferir ansible-playbook do sistema quando existir (/usr/bin); senão o primeiro no PATH.
# O Python embutido no IDE pode falhar em fork; `dnf install ansible-core` costuma ir para /usr/bin.
ANSIBLE_PLAYBOOK ?= $(shell if test -x /usr/bin/ansible-playbook; then echo /usr/bin/ansible-playbook; elif command -v ansible-playbook >/dev/null 2>&1; then command -v ansible-playbook; else echo ansible-playbook; fi)
ANSIBLE_PLAYBOOK_KVM := $(ANSIBLE_PLAYBOOK)
endif
ANSIBLE_PLAYBOOK_VM ?= $(if $(filter 1,$(USE_VENV)),$(shell test -x /usr/bin/ansible-playbook && echo /usr/bin/ansible-playbook || echo $(CURDIR)/.venv/bin/ansible-playbook),$(ANSIBLE_PLAYBOOK))
# Com USE_VENV=1, a 2ª play usa env mínimo por defeito (evita variáveis herdadas do IDE/shell). Desligar: USE_VENV_STRICT=0
USE_VENV_STRICT ?= $(USE_VENV)
# SSH sem ControlMaster (multiplex) reduz falhas com workers; no_proxy=* evita proxy HTTP nas tasks.
ANSIBLE_SSH_ARGS ?= -C -o ControlMaster=no -o ControlPersist=no
# Cursor/AppImage: LD_PRELOAD/LD_LIBRARY_PATH/PYTHONPATH + fork dos workers; -u remove mesmo quando não definidos.
ANSIBLE_UNWRAP ?= env -u LD_PRELOAD -u LD_LIBRARY_PATH -u PYTHONPATH PYTHONNOUSERSITE=1 MALLOC_ARENA_MAX=2
# Prefixo da 2ª invocação (os_prepare): env mínimo se USE_VENV_STRICT=1 e USE_VENV=1.
PLAY2_ENV :=
ifeq ($(USE_VENV_STRICT),1)
ifeq ($(USE_VENV),1)
PLAY2_ENV := env -i HOME="$(HOME)" USER="$(USER)" PATH="$(dir $(ANSIBLE_PLAYBOOK_VM)):/usr/bin:/bin" SSL_CERT_FILE=/etc/pki/tls/certs/ca-bundle.crt LANG=C.UTF-8 TERM=dumb SSH_AUTH_SOCK="$(SSH_AUTH_SOCK)" no_proxy='*' NO_PROXY='*' ANSIBLE_CONFIG=$(ANSIBLE_CFG) ANSIBLE_FORKS=$(ANSIBLE_FORKS) ANSIBLE_PRIVATE_KEY_FILE=$(LAB_KEY_ABS) ANSIBLE_SSH_ARGS='$(ANSIBLE_SSH_ARGS)' PYTHONNOUSERSITE=1 MALLOC_ARENA_MAX=2
endif
endif
ifeq ($(strip $(PLAY2_ENV)),)
PLAY2_ENV := $(ANSIBLE_UNWRAP) no_proxy='*' NO_PROXY='*' ANSIBLE_SSH_ARGS='$(ANSIBLE_SSH_ARGS)' ANSIBLE_CONFIG=$(ANSIBLE_CFG) ANSIBLE_FORKS=$(ANSIBLE_FORKS) ANSIBLE_PRIVATE_KEY_FILE=$(LAB_KEY_ABS)
endif
# Duas invocações (uma por play) reiniciam o processo Python — contorna fork/thread no 2.º play.
UP_SPLIT ?= 1

# ---- Cores ------------------------------------------------------------------
B := \033[1m
G := \033[32m
Y := \033[33m
R := \033[31m
N := \033[0m

.DEFAULT_GOAL := help
.PHONY: help deps venv venv-create venv-install keys up ssh ssh-add-lab status destroy clean

# =============================================================================
# Help
# =============================================================================
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
	@printf "  Ansible     : 1ª=$(ANSIBLE_PLAYBOOK_KVM) 2ª=$(ANSIBLE_PLAYBOOK_VM) | $(ANSIBLE_FLAGS)  forks=$(ANSIBLE_FORKS)  up_split=$(UP_SPLIT)  cfg=$(ANSIBLE_CFG)\n"
	@printf "  USE_VENV    : (vazio)=ansible do sistema; 1=.venv (após $(B)make venv$(N)); USE_VENV_STRICT=$(USE_VENV_STRICT) (2ª play env mínimo se 1)\n"
	@printf "  USE_UV      : 0=venv com Python do sistema; 1=$(B)uv$(N) + UV_PYTHON=$(UV_PYTHON) — ex.: $(B)rm -rf .venv && make venv USE_UV=1$(N)\n"
	@printf "  Become (1ª play, host KVM): $(if $(ANSIBLE_BECOME_PASSWORD_FILE),ficheiro $(ANSIBLE_BECOME_PASSWORD_FILE),--ask-become-pass — preencha $(BECOME_PASS_FILE) (não vazio) para evitar prompt)\n"
	@printf "  Become (2ª play, VMs)      : %s\n" "$(if $(strip $(SUDO_FLAGS_VM)),$(SUDO_FLAGS_VM),sem flags — rocky sudo NOPASSWD; senha na VM: env/vm-become.pass ou SUDO_FLAGS_VM=--become-password-file=...)"
	@printf "\n$(B)Multi-overlay:$(N)\n"
	@printf "  make up OVERLAY=<nome>          # usa provisioning/inventory/<nome>/\n"
	@printf "  make ssh OVERLAY=<nome> VM_IP=<ip>\n"

# =============================================================================
# Pré-requisitos
# =============================================================================
venv: venv-create venv-install ## Cria .venv (ansible-core + ansible.posix). USE_UV=1 → uv + UV_PYTHON (defeito 3.12); senão VENV_PYTHON em /usr/bin

venv-create:
ifeq ($(USE_UV),1)
	@command -v uv >/dev/null 2>&1 || { printf "$(R)USE_UV=1 requer uv no PATH — https://docs.astral.sh/uv/  (ou: curl -LsSf https://astral.sh/uv/install.sh | sh)$(N)\n"; exit 1; }
	@printf "$(Y)==> Criando .venv com uv (Python $(UV_PYTHON); sem rpm-ostree)$(N)\n"
	@rm -rf $(CURDIR)/.venv
	@cd "$(CURDIR)" && $(ANSIBLE_UNWRAP) uv venv --python $(UV_PYTHON) "$(CURDIR)/.venv"
else
	@test -n "$(VENV_PYTHON)" || { printf "$(R)Não encontrei Python para o venv (defina VENV_PYTHON=/caminho/python3 ou USE_UV=1)$(N)\n"; exit 1; }
	@printf "$(Y)==> Criando .venv com $(VENV_PYTHON)$(N)\n"
	@if ! echo "$(VENV_PYTHON)" | grep -qF 'python3.12'; then \
	  printf "$(Y)==> Nota: não usaste Python 3.12 do sistema. Para 3.12 sem rpm-ostree: rm -rf .venv && make venv USE_UV=1$(N)\n"; \
	fi
	@rm -rf $(CURDIR)/.venv
	@env -i PATH=/usr/bin:/bin HOME="$(HOME)" USER="$(USER)" "$(VENV_PYTHON)" -m venv "$(CURDIR)/.venv"
endif

venv-install: ## Atualiza pip/ansible-core/ansible.posix dentro de .venv (mantém o diretório)
ifeq ($(USE_UV),1)
	@printf "$(Y)==> uv pip install no .venv$(N)\n"
	@$(ANSIBLE_UNWRAP) env SSL_CERT_FILE=/etc/pki/tls/certs/ca-bundle.crt HOME="$(HOME)" \
		uv pip install --python "$(CURDIR)/.venv/bin/python" -q 'ansible-core>=2.16' paramiko
else
	@printf "$(Y)==> pip install no .venv$(N)\n"
	@env -i PATH="$(CURDIR)/.venv/bin:/usr/bin:/bin" HOME="$(HOME)" SSL_CERT_FILE=/etc/pki/tls/certs/ca-bundle.crt \
		"$(CURDIR)/.venv/bin/python3" -m pip install -q -U pip setuptools wheel
	@env -i PATH="$(CURDIR)/.venv/bin:/usr/bin:/bin" HOME="$(HOME)" SSL_CERT_FILE=/etc/pki/tls/certs/ca-bundle.crt \
		"$(CURDIR)/.venv/bin/python3" -m pip install -q 'ansible-core>=2.16' paramiko
endif
	@printf "$(Y)==> ansible-galaxy collection install ansible.posix$(N)\n"
	@$(ANSIBLE_UNWRAP) env -i PATH="$(CURDIR)/.venv/bin:/usr/bin:/bin" HOME="$(HOME)" LD_PRELOAD= SSL_CERT_FILE=/etc/pki/tls/certs/ca-bundle.crt \
		"$(CURDIR)/.venv/bin/ansible-galaxy" collection install ansible.posix
	@printf "$(G)==> Pronto. Teste: $(B)make deps USE_VENV=1$(N) depois $(B)make up USE_VENV=1$(N)  (venv com $(if $(filter 1,$(USE_UV)),uv $(UV_PYTHON),$(VENV_PYTHON)))$(N)\n"

deps: ## Verifica que ansible-playbook, virsh e a coleção ansible.posix existem
	@$(ANSIBLE_UNWRAP) $(ANSIBLE_PLAYBOOK) --version >/dev/null 2>&1 \
	  || { printf "$(R)Falta ou não executa: $(ANSIBLE_PLAYBOOK)$(N) — veja provisioning/README.md\n"; exit 1; }
ifeq ($(USE_VENV),1)
	@$(ANSIBLE_UNWRAP) $(ANSIBLE_PLAYBOOK_VM) --version >/dev/null 2>&1 \
	  || { printf "$(R)Falta ou não executa (2ª play): $(ANSIBLE_PLAYBOOK_VM)$(N) — veja provisioning/README.md\n"; exit 1; }
	@if [ "$(ANSIBLE_PLAYBOOK_VM)" = "$(CURDIR)/.venv/bin/ansible-playbook" ]; then \
	  printf "$(Y)==> Dica: 2ª play = .venv — se \"worker dead\": make venv-install (instala paramiko) ou rpm-ostree install ansible-core; evite make do Cursor: /usr/bin/make up USE_VENV=1$(N)\n"; \
	fi
endif
	@command -v virsh >/dev/null \
	  || { printf "$(R)Falta virsh$(N) — instale o pacote libvirt-client\n"; exit 1; }
	@command -v ssh-keygen >/dev/null \
	  || { printf "$(R)Falta ssh-keygen$(N) — instale openssh-clients\n"; exit 1; }
	@ansible-galaxy collection list ansible.posix 2>/dev/null \
	  | grep -q ansible.posix \
	  || { printf "$(Y)==> Instalando coleção ansible.posix$(N)\n"; \
	       $(ANSIBLE_UNWRAP) $(ANSIBLE_PLAYBOOK:%-playbook=%-galaxy) collection install ansible.posix; }

# =============================================================================
# Chave SSH local do laboratório
# =============================================================================
# Gerada uma vez por clone do repo. Vive em env/ (gitignored) e é injetada na
# VM via cloud-init. Nunca toca em ~/.ssh/.
keys: $(LAB_KEY).pub ## Gera o par de chaves SSH local do lab (idempotente)

$(LAB_KEY).pub:
	@mkdir -p $(dir $(LAB_KEY))
	@printf "$(Y)==> Gerando chave SSH local do lab em $(LAB_KEY)$(N)\n"
	@ssh-keygen -t ed25519 -C "k8s-blueprint" -f $(LAB_KEY) -N "" -q
	@printf "$(G)==> Chave criada (gitignored; não vai pro git)$(N)\n"

# =============================================================================
# Ciclo de vida da VM
# =============================================================================
up: deps keys ## Provisiona a VM (idempotente; cria a chave do lab se faltar)
	@printf "$(B)==> Provisionando overlay '$(OVERLAY)'$(N)\n"
ifeq ($(UP_SPLIT),1)
	@printf "$(Y)==> Ansible 1/2 (tag kvm_lab) — $(ANSIBLE_PLAYBOOK)$(N)\n"
	$(ANSIBLE_UNWRAP) no_proxy='*' NO_PROXY='*' ANSIBLE_SSH_ARGS='$(ANSIBLE_SSH_ARGS)' ANSIBLE_CONFIG=$(ANSIBLE_CFG) \
	ANSIBLE_FORKS=$(ANSIBLE_FORKS) \
	ANSIBLE_PRIVATE_KEY_FILE=$(LAB_KEY_ABS) $(ANSIBLE_PLAYBOOK) \
	    --forks=$(ANSIBLE_FORKS) \
	    -i $(INVENTORY) \
	    $(PLAYBOOK) \
	    --tags kvm_lab \
	    $(ANSIBLE_FLAGS) \
	    $(SUDO_FLAGS) \
	    --private-key=$(LAB_KEY_ABS) \
	    -e "ssh_public_key_path=$(LAB_KEY_ABS).pub" \
	    -e "ansible_ssh_private_key_file=$(LAB_KEY_ABS)" \
	    -e "ansible_ssh_common_args=$(ANSIBLE_SSH_COMMON)"
	@printf "$(Y)==> Ansible 2/2 (tag os_prepare) — $(ANSIBLE_PLAYBOOK_VM)$(N)\n"
	$(PLAY2_ENV) $(ANSIBLE_PLAYBOOK_VM) \
	    --forks=$(ANSIBLE_FORKS) \
	    -i $(INVENTORY) \
	    $(PLAYBOOK) \
	    --tags os_prepare \
	    $(ANSIBLE_FLAGS) \
	    $(SUDO_FLAGS_VM) \
	    --private-key=$(LAB_KEY_ABS) \
	    -e "ssh_public_key_path=$(LAB_KEY_ABS).pub" \
	    -e "ansible_ssh_private_key_file=$(LAB_KEY_ABS)" \
	    -e "ansible_ssh_common_args=$(ANSIBLE_SSH_COMMON)"
else
	$(ANSIBLE_UNWRAP) no_proxy='*' NO_PROXY='*' ANSIBLE_SSH_ARGS='$(ANSIBLE_SSH_ARGS)' ANSIBLE_CONFIG=$(ANSIBLE_CFG) \
	ANSIBLE_FORKS=$(ANSIBLE_FORKS) \
	ANSIBLE_PRIVATE_KEY_FILE=$(LAB_KEY_ABS) $(ANSIBLE_PLAYBOOK) \
	    --forks=$(ANSIBLE_FORKS) \
	    -i $(INVENTORY) \
	    $(PLAYBOOK) \
	    $(ANSIBLE_FLAGS) \
	    $(SUDO_FLAGS) \
	    --private-key=$(LAB_KEY_ABS) \
	    -e "ssh_public_key_path=$(LAB_KEY_ABS).pub" \
	    -e "ansible_ssh_private_key_file=$(LAB_KEY_ABS)" \
	    -e "ansible_ssh_common_args=$(ANSIBLE_SSH_COMMON)"
endif
	@printf "\n$(G)==> Pronto.$(N) Use $(B)make ssh$(N) para entrar na VM.\n"

ssh: ## Conecta na VM via SSH usando a chave do lab
	@ssh -i $(LAB_KEY_ABS) \
	     -o StrictHostKeyChecking=no \
	     -o UserKnownHostsFile=/dev/null \
	     rocky@$(VM_IP)

ssh-add-lab: ## Adiciona a chave do lab ao ssh-agent (opcional; útil fora do Ansible)
	@ssh-add $(LAB_KEY_ABS)

status: ## Mostra estado da VM e da rede libvirt
	@printf "$(B)Domínios libvirt:$(N)\n"
	@virsh -c qemu:///system list --all
	@printf "\n$(B)Redes libvirt:$(N)\n"
	@virsh -c qemu:///system net-list --all

destroy: ## Para e remove a VM (mantém cache da imagem qcow2 base)
	-virsh -c qemu:///system destroy $(VM_NAME)
	-virsh -c qemu:///system undefine $(VM_NAME) --remove-all-storage
	-sudo rm -f $(LIBVIRT_POOL_PATH)/$(VM_NAME)-seed.iso
	@printf "$(G)==> VM '$(VM_NAME)' removida (cache preservado).$(N)\n"

clean: destroy ## Destrói TUDO (VM + rede libvirt + cache + chave do lab)
	-virsh -c qemu:///system net-destroy $(KVM_NETWORK)
	-virsh -c qemu:///system net-undefine $(KVM_NETWORK)
	-sudo rm -rf $(LIBVIRT_POOL_PATH)/_cache
	-rm -f $(LAB_KEY) $(LAB_KEY).pub
	@printf "$(G)==> Tudo limpo. Próximo 'make up' começa do zero.$(N)\n"
