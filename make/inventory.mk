# =============================================================================
# make/inventory.mk — hosts.ini generation (app/inventory)
# =============================================================================

.PHONY: inventory inventory-overlay

inventory: sync ## Gera hosts.ini de todos os overlays
	@$(ANSIBLE_UNWRAP) $(UV) run python -m app.inventory.cli generate --all

inventory-overlay: sync ## Gera hosts.ini só do OVERLAY activo
	@$(ANSIBLE_UNWRAP) $(UV) run python -m app.inventory.cli generate -o $(OVERLAY)
