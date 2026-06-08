# =============================================================================
# make/ssh.mk — SSH, known_hosts e utilitários libvirt
# =============================================================================

.PHONY: ensure-user-known-hosts ensure-ssh-global-known-hosts ssh ssh-add-lab \
	ssh-host-key-forget ssh-host-key-refresh status destroy clean

ensure-user-known-hosts: ## Prepara ~/.ssh e stubs SSH do lab no controlador (sem sudo)
	@mkdir -p $(HOME)/.ssh && chmod 700 $(HOME)/.ssh 2>/dev/null || true
	@touch $(HOME)/.ssh/known_hosts && chmod 644 $(HOME)/.ssh/known_hosts 2>/dev/null || true
	@mkdir -p env
	@touch $(LAB_SSH_GLOBAL_STUB)
	@test -f $(LAB_SSH_CONFIG_EXAMPLE) \
	  || { printf "$(R)Falta $(LAB_SSH_CONFIG_EXAMPLE)$(N)\n"; exit 1; }
	@sed 's|@REPO_ROOT@|$(CURDIR)|g' $(LAB_SSH_CONFIG_EXAMPLE) > $(LAB_SSH_CONFIG).tmp
	@mv $(LAB_SSH_CONFIG).tmp $(LAB_SSH_CONFIG)
	@printf "$(G)==> SSH do controlador pronto (~/.ssh/known_hosts, $(LAB_SSH_CONFIG)).$(N)\n"

ensure-ssh-global-known-hosts: ## Cria /etc/ssh/ssh_known_hosts se CREATE_SSH_GLOBAL_KNOWN_HOSTS=true
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

ssh: ## Conecta na VM (ansible_user do inventário) com a chave do lab
	@mkdir -p $(HOME)/.ssh && chmod 700 $(HOME)/.ssh 2>/dev/null || true
	@ssh -i $(LAB_KEY_ABS) \
	     -o StrictHostKeyChecking=accept-new \
	     -o UserKnownHostsFile=$(HOME)/.ssh/known_hosts \
	     $(VM_USER)@$(VM_IP)

ssh-add-lab: ## Adiciona a chave do lab ao ssh-agent (opcional)
	@ssh-add $(LAB_KEY_ABS)

ssh-host-key-forget: ## Remove entradas antigas de VM_IP em ~/.ssh/known_hosts
	@ssh-keygen -R $(VM_IP) -f $(HOME)/.ssh/known_hosts 2>/dev/null || true
	@ssh-keygen -R $(VM_NAME) -f $(HOME)/.ssh/known_hosts 2>/dev/null || true

ssh-host-key-refresh: ssh-host-key-forget ## Regista a chave da VM em ~/.ssh/known_hosts
	@printf "$(Y)==> Registando chave SSH de $(VM_IP) em $(HOME)/.ssh/known_hosts...$(N)\n"
	@mkdir -p $(HOME)/.ssh
	@chmod 700 $(HOME)/.ssh 2>/dev/null || true
	@touch $(HOME)/.ssh/known_hosts
	@keys=$$(mktemp); \
	trap 'rm -f $$keys' EXIT; \
	until ssh-keyscan -H $(VM_IP) 2>/dev/null | grep -E '^(ssh-|ecdsa-|\|[0-9]+\|)' > $$keys && test -s $$keys; do sleep 2; done; \
	cat $$keys >> $(HOME)/.ssh/known_hosts

status: ## Estado das VMs e redes libvirt
	@printf "$(B)Domínios libvirt:$(N)\n"
	@virsh -c qemu:///system list --all
	@printf "\n$(B)Redes libvirt:$(N)\n"
	@virsh -c qemu:///system net-list --all

destroy: ssh-host-key-forget ## Remove VMs do overlay activo (mantém cache qcow2)
	@if [ -z "$(strip $(_inventory_vms_list))" ]; then \
	  printf "$(R)==> Nenhum host em [vms] em $(INVENTORY)$(N)\n"; exit 1; \
	fi
	@for vm in $(_inventory_vms_list); do \
	  printf "$(Y)==> Removendo VM '%s'...$(N)\n" "$$vm"; \
	  virsh -c qemu:///system destroy "$$vm" 2>/dev/null || true; \
	  virsh -c qemu:///system undefine "$$vm" --remove-all-storage 2>/dev/null || true; \
	  rm -f "$(LAB_DISKS_PATH)/$$vm-seed.iso" 2>/dev/null || true; \
	done
	@printf "$(G)==> VM(s) do overlay removida(s) (cache preservado).$(N)\n"

clean: destroy ## VM + rede + lab/ + chave SSH
	-virsh -c qemu:///system net-destroy $(KVM_NETWORK)
	-virsh -c qemu:///system net-undefine $(KVM_NETWORK)
	-rm -rf $(LAB_DISKS_PATH) $(LAB_CACHE_PATH)
	-rm -f $(LAB_KEY) $(LAB_KEY).pub
	@printf "$(G)==> Limpo. Próximo $(B)make up$(N) começa do zero.$(N)\n"
