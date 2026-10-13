# =============================================================================
# make/overlays.mk — overlays locais, catálogo, DNS e validação (app/cli.py)
# =============================================================================
#
# Atalhos para `uv run k8s-blueprint ...`. Overlays criados aqui não são
# versionados: ficam em provisioning/inventory/manifest.local.yml e em
# k8s/**/overlays/<id>/ (ambos no .gitignore).
#
#   make tui                          # menu interativo
#   make new NAME=meu-lab [FROM=broetec-core] [ARGS="--ip 10.20.30.80"]
#   make overlays                     # lista overlays (versionados e locais)
#   make rm-overlay NAME=meu-lab      # remove um overlay local
#   make dns-check                    # registros A esperados x o que resolve
#   make validate-k8s                 # kustomize build em todos os overlays
# =============================================================================

.PHONY: tui new overlays rm-overlay catalog dns-check validate-k8s

K8S_BLUEPRINT = $(ANSIBLE_UNWRAP) $(UV) run --directory "$(CURDIR)" k8s-blueprint

tui: sync ## Menu interativo para montar um overlay local
	@$(K8S_BLUEPRINT) tui

new: sync ## Cria um overlay local (NAME=, FROM=overlay base, ARGS=opções extras)
	@test -n "$(NAME)" || { printf "$(R)Uso: make new NAME=meu-lab [FROM=broetec-core] [ARGS='--ip 10.20.30.80']$(N)\n"; exit 1; }
	@$(K8S_BLUEPRINT) overlay new "$(NAME)" $(if $(FROM),--from "$(FROM)") $(ARGS)

overlays: sync ## Lista overlays versionados e locais
	@$(K8S_BLUEPRINT) overlay list

rm-overlay: sync ## Remove um overlay local (NAME=, ARGS=--purge-env/--force)
	@test -n "$(NAME)" || { printf "$(R)Uso: make rm-overlay NAME=meu-lab$(N)\n"; exit 1; }
	@$(K8S_BLUEPRINT) overlay rm "$(NAME)" $(ARGS)

catalog: sync ## Lista stacks e componentes do catálogo (k8s/catalog.yml)
	@$(K8S_BLUEPRINT) catalog

dns-check: sync ## Registros DNS esperados pelos overlays e os que faltam
	@$(K8S_BLUEPRINT) dns check $(if $(filter command line,$(origin OVERLAY)),--overlay "$(OVERLAY)")

validate-k8s: sync ## kustomize build em todos os overlays de k8s/
	@$(K8S_BLUEPRINT) validate $(if $(filter command line,$(origin OVERLAY)),--overlay "$(OVERLAY)")
