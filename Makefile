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

# Flags repassáveis ao ansible-playbook. Para sudo passwordless local:
#   make up SUDO_FLAGS=
SUDO_FLAGS    ?= --ask-become-pass
# Por defeito salta a tag `bootstrap` (dnf não existe em Bazzite/immutable).
# Fedora/RHEL tradicional com dnf: make up ANSIBLE_FLAGS=
ANSIBLE_FLAGS ?= --skip-tags bootstrap

# ---- Cores ------------------------------------------------------------------
B := \033[1m
G := \033[32m
Y := \033[33m
R := \033[31m
N := \033[0m

.DEFAULT_GOAL := help
.PHONY: help deps keys up ssh status destroy clean

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
	@printf "  Lab key     : $(LAB_KEY)\n"
	@printf "  Ansible     : $(ANSIBLE_FLAGS)\n"
	@printf "\n$(B)Multi-overlay:$(N)\n"
	@printf "  make up OVERLAY=<nome>          # usa provisioning/inventory/<nome>/\n"
	@printf "  make ssh OVERLAY=<nome> VM_IP=<ip>\n"

# =============================================================================
# Pré-requisitos
# =============================================================================
deps: ## Verifica que ansible-playbook, virsh e a coleção ansible.posix existem
	@command -v ansible-playbook >/dev/null \
	  || { printf "$(R)Falta ansible-playbook$(N) — veja provisioning/README.md\n"; exit 1; }
	@command -v virsh >/dev/null \
	  || { printf "$(R)Falta virsh$(N) — instale o pacote libvirt-client\n"; exit 1; }
	@command -v ssh-keygen >/dev/null \
	  || { printf "$(R)Falta ssh-keygen$(N) — instale openssh-clients\n"; exit 1; }
	@ansible-galaxy collection list ansible.posix 2>/dev/null \
	  | grep -q ansible.posix \
	  || { printf "$(Y)==> Instalando coleção ansible.posix$(N)\n"; \
	       ansible-galaxy collection install ansible.posix; }

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
	ansible-playbook \
	    -i $(INVENTORY) \
	    $(PLAYBOOK) \
	    $(ANSIBLE_FLAGS) \
	    $(SUDO_FLAGS) \
	    --private-key=$(CURDIR)/$(LAB_KEY) \
	    -e "ssh_public_key_path=$(CURDIR)/$(LAB_KEY).pub" \
	    -e "ansible_ssh_private_key_file=$(CURDIR)/$(LAB_KEY)"
	@printf "\n$(G)==> Pronto.$(N) Use $(B)make ssh$(N) para entrar na VM.\n"

ssh: ## Conecta na VM via SSH usando a chave do lab
	@ssh -i $(LAB_KEY) \
	     -o StrictHostKeyChecking=no \
	     -o UserKnownHostsFile=/dev/null \
	     rocky@$(VM_IP)

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
