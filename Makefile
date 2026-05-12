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
# Fork + prompt interactivo (--ask-become-pass) pode causar "worker dead"; usar ficheiro:
#   printf '%s\n' 'tua_senha_sudo' > env/become.pass && chmod 600 env/become.pass
#   make up ANSIBLE_BECOME_PASSWORD_FILE=/abs/path/to/repo/env/become.pass
ANSIBLE_BECOME_PASSWORD_FILE ?=
SUDO_FLAGS ?= $(if $(ANSIBLE_BECOME_PASSWORD_FILE),--become-password-file=$(ANSIBLE_BECOME_PASSWORD_FILE),--ask-become-pass)
# Por defeito salta a tag `bootstrap` (dnf não existe em Bazzite/immutable).
# Fedora/RHEL tradicional com dnf: make up ANSIBLE_FLAGS=
ANSIBLE_FLAGS ?= --skip-tags bootstrap
# Um único fork evita "A worker was found in a dead state" (OOM / Cursor / agent).
ANSIBLE_FORKS ?= 1
ANSIBLE_CFG ?= $(CURDIR)/ansible.cfg
# Preferir ansible-playbook do sistema quando existir (/usr/bin); senão o primeiro no PATH.
# O Python embutido no IDE pode falhar em fork; `dnf install ansible-core` costuma ir para /usr/bin.
ANSIBLE_PLAYBOOK ?= $(shell if test -x /usr/bin/ansible-playbook; then echo /usr/bin/ansible-playbook; elif command -v ansible-playbook >/dev/null 2>&1; then command -v ansible-playbook; else echo ansible-playbook; fi)
# SSH sem ControlMaster (multiplex) reduz falhas com workers; no_proxy=* evita proxy HTTP nas tasks.
ANSIBLE_SSH_ARGS ?= -C -o ControlMaster=no -o ControlPersist=no
# Cursor/AppImage costuma injectar LD_PRELOAD; fork() dos workers Ansible rebenta com preload activo.
ANSIBLE_UNWRAP ?= env LD_PRELOAD=
# Duas invocações (uma por play) reiniciam o processo Python — contorna fork/thread no 2.º play.
UP_SPLIT ?= 1

# ---- Cores ------------------------------------------------------------------
B := \033[1m
G := \033[32m
Y := \033[33m
R := \033[31m
N := \033[0m

.DEFAULT_GOAL := help
.PHONY: help deps keys up ssh ssh-add-lab status destroy clean

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
	@printf "  Ansible     : $(ANSIBLE_PLAYBOOK) | $(ANSIBLE_FLAGS)  forks=$(ANSIBLE_FORKS)  up_split=$(UP_SPLIT)  cfg=$(ANSIBLE_CFG)\n"
	@printf "  Become      : $(if $(ANSIBLE_BECOME_PASSWORD_FILE),ficheiro $(ANSIBLE_BECOME_PASSWORD_FILE),prompt interactivo / ver Makefile)\n"
	@printf "\n$(B)Multi-overlay:$(N)\n"
	@printf "  make up OVERLAY=<nome>          # usa provisioning/inventory/<nome>/\n"
	@printf "  make ssh OVERLAY=<nome> VM_IP=<ip>\n"

# =============================================================================
# Pré-requisitos
# =============================================================================
deps: ## Verifica que ansible-playbook, virsh e a coleção ansible.posix existem
	@$(ANSIBLE_UNWRAP) $(ANSIBLE_PLAYBOOK) --version >/dev/null 2>&1 \
	  || { printf "$(R)Falta ou não executa: $(ANSIBLE_PLAYBOOK)$(N) — veja provisioning/README.md\n"; exit 1; }
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
	ANSIBLE_SSH_PIPELINING=false \
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
	@printf "$(Y)==> Ansible 2/2 (tag os_prepare) — $(ANSIBLE_PLAYBOOK)$(N)\n"
	$(ANSIBLE_UNWRAP) no_proxy='*' NO_PROXY='*' ANSIBLE_SSH_ARGS='$(ANSIBLE_SSH_ARGS)' ANSIBLE_CONFIG=$(ANSIBLE_CFG) \
	ANSIBLE_FORKS=$(ANSIBLE_FORKS) \
	ANSIBLE_SSH_PIPELINING=false \
	ANSIBLE_PRIVATE_KEY_FILE=$(LAB_KEY_ABS) $(ANSIBLE_PLAYBOOK) \
	    --forks=$(ANSIBLE_FORKS) \
	    -i $(INVENTORY) \
	    $(PLAYBOOK) \
	    --tags os_prepare \
	    $(ANSIBLE_FLAGS) \
	    $(SUDO_FLAGS) \
	    --private-key=$(LAB_KEY_ABS) \
	    -e "ssh_public_key_path=$(LAB_KEY_ABS).pub" \
	    -e "ansible_ssh_private_key_file=$(LAB_KEY_ABS)" \
	    -e "ansible_ssh_common_args=$(ANSIBLE_SSH_COMMON)"
else
	$(ANSIBLE_UNWRAP) no_proxy='*' NO_PROXY='*' ANSIBLE_SSH_ARGS='$(ANSIBLE_SSH_ARGS)' ANSIBLE_CONFIG=$(ANSIBLE_CFG) \
	ANSIBLE_FORKS=$(ANSIBLE_FORKS) \
	ANSIBLE_SSH_PIPELINING=false \
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
