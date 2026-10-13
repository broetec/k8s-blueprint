# =============================================================================
# make/ssh.mk — SSH, known_hosts e utilitários libvirt
# =============================================================================

.PHONY: ensure-user-known-hosts ensure-ssh-global-known-hosts ssh ssh-add-lab \
	ssh-host-key-forget ssh-host-key-refresh status destroy destroy-all clean \
	snapshot revert snapshots

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

# Uso interno do destroy-all: DESTROY_QUIET=1 cala os avisos de overlay sem VM
# e DESTROY_REPORT=<ficheiro> recebe o nome de cada VM removida.
DESTROY_QUIET ?=
DESTROY_REPORT ?=
_inventory_root := $(CURDIR)/provisioning/inventory

destroy: ssh-host-key-forget ## Remove VMs do overlay activo (mantém cache qcow2)
	@if [ -z "$(strip $(_inventory_vms_list))" ]; then \
	  printf "$(R)==> Nenhum host em [vms] em $(INVENTORY)$(N)\n"; exit 1; \
	fi
	@removed=""; \
	for vm in $(_inventory_vms_list); do \
	  disk="$(LAB_DISKS_PATH)/$$vm.qcow2"; seed="$(LAB_DISKS_PATH)/$$vm-seed.iso"; \
	  defined=0; virsh -c qemu:///system dominfo "$$vm" >/dev/null 2>&1 && defined=1; \
	  if [ $$defined -eq 0 ] && [ ! -e "$$disk" ] && [ ! -e "$$seed" ]; then \
	    [ -n "$(DESTROY_QUIET)" ] \
	      || printf "$(Y)==> VM '%s' não existe (OVERLAY=$(OVERLAY)): nada a remover.$(N)\n" "$$vm"; \
	    continue; \
	  fi; \
	  printf "$(Y)==> Removendo VM '%s'...$(N)\n" "$$vm"; \
	  if [ $$defined -eq 1 ]; then \
	    virsh -c qemu:///system destroy "$$vm" >/dev/null 2>&1 || true; \
	    virsh -c qemu:///system undefine "$$vm" --managed-save --snapshots-metadata \
	      || { printf "$(R)==> Falha ao remover o domínio '%s'$(N)\n" "$$vm"; exit 1; }; \
	  fi; \
	  rm -f "$$disk" "$$seed" \
	    || { printf "$(R)==> Falha ao apagar os discos de '%s'$(N)\n" "$$vm"; exit 1; }; \
	  removed="$$removed $$vm"; \
	  [ -z "$(DESTROY_REPORT)" ] || printf '%s\n' "$$vm" >> "$(DESTROY_REPORT)"; \
	done; \
	[ -z "$$removed" ] \
	  || printf "$(G)==> VM(s) removida(s):%s (cache preservado).$(N)\n" "$$removed"; \
	[ -z "$(DESTROY_QUIET)" ] || exit 0; \
	for disk in "$(LAB_DISKS_PATH)"/*.qcow2; do \
	  [ -e "$$disk" ] || continue; \
	  vm=$$(basename "$$disk" .qcow2); overlay=""; \
	  for inv in "$(_inventory_root)"/*/hosts.ini; do \
	    [ -e "$$inv" ] || continue; \
	    if awk -v vm="$$vm" 'BEGIN{v=0;f=0} /^\[vms\]$$/{v=1;next} /^\[/{v=0;next} v&&$$1==vm{f=1} END{exit !f}' "$$inv"; then \
	      overlay=$$(basename "$$(dirname "$$inv")"); break; \
	    fi; \
	  done; \
	  if [ -n "$$overlay" ]; then \
	    printf "$(B)==> VM '%s' continua existindo:$(N) make destroy OVERLAY=%s (ou make destroy-all)\n" "$$vm" "$$overlay"; \
	  else \
	    printf "$(B)==> Disco '%s' sem overlay no inventário:$(N) %s\n" "$$vm" "$$disk"; \
	  fi; \
	done

destroy-all: ## Remove as VMs de todos os overlays (versionados, locais e golden)
	@report=$$(mktemp); trap 'rm -f "$$report"' EXIT; \
	for inv in "$(_inventory_root)"/*/hosts.ini; do \
	  [ -e "$$inv" ] || continue; \
	  o=$$(basename "$$(dirname "$$inv")"); \
	  $(SUBMAKE) --no-print-directory -f $(CURDIR)/Makefile destroy OVERLAY=$$o \
	    DESTROY_QUIET=1 DESTROY_REPORT="$$report" || exit $$?; \
	done; \
	if [ -s "$$report" ]; then \
	  printf "\n$(G)==> %s VM(s) removida(s):$(N) %s\n" "$$(wc -l < "$$report")" "$$(tr '\n' ' ' < "$$report")"; \
	else \
	  printf "$(Y)==> Nenhuma VM do lab existe: nada a remover.$(N)\n"; \
	fi

snapshot: ## Snapshot das VMs do overlay (NAME=<nome>; guarda a memória se a VM estiver ligada)
	@test -n "$(NAME)" || { printf "$(R)Use: make snapshot NAME=<nome>$(N)\n"; exit 1; }
	@for vm in $(_inventory_vms_list); do \
	  printf "$(Y)==> Snapshot '%s' de '%s'...$(N)\n" "$(NAME)" "$$vm"; \
	  virsh -c qemu:///system snapshot-create-as "$$vm" "$(NAME)" --atomic || exit 1; \
	done

revert: ## Reverte as VMs do overlay para um snapshot (NAME=<nome>)
	@test -n "$(NAME)" || { printf "$(R)Use: make revert NAME=<nome>$(N)\n"; exit 1; }
	@for vm in $(_inventory_vms_list); do \
	  printf "$(Y)==> Revertendo '%s' para '%s'...$(N)\n" "$$vm" "$(NAME)"; \
	  virsh -c qemu:///system snapshot-revert "$$vm" "$(NAME)" || exit 1; \
	  for try in 1 2 3 4 5; do \
	    virsh -c qemu:///system domtime "$$vm" --sync >/dev/null 2>&1 && break; sleep 1; \
	  done; \
	done

snapshots: ## Lista os snapshots das VMs do overlay
	@for vm in $(_inventory_vms_list); do \
	  printf "$(B)%s:$(N)\n" "$$vm"; \
	  virsh -c qemu:///system snapshot-list "$$vm" || true; \
	done

clean: destroy ## VM + rede + lab/ + chave SSH
	-virsh -c qemu:///system net-destroy $(KVM_NETWORK)
	-virsh -c qemu:///system net-undefine $(KVM_NETWORK)
	-rm -rf $(LAB_DISKS_PATH) $(LAB_CACHE_PATH)
	-rm -f $(LAB_KEY) $(LAB_KEY).pub
	@printf "$(G)==> Limpo. Próximo $(B)make up$(N) começa do zero.$(N)\n"
