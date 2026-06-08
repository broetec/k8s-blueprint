# =============================================================================
# make/setup.mk — controller bootstrap (uv, Galaxy, SSH keys)
# =============================================================================

.PHONY: sync venv deps keys setup

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

setup: sync deps keys ## Controlador: .venv, Galaxy, chave SSH
