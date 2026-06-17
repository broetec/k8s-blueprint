# =============================================================================
# make/docs.mk — documentação Sphinx
# =============================================================================

DOCS_BUILD ?= docs/_build/html

.PHONY: docs-html docs-clean

docs-html: ## Gera documentação HTML (Sphinx) → docs/_build/html/index.html
	uv run sphinx-build -b html -c docs . $(DOCS_BUILD)
	@printf "$(G)==> Docs prontos:$(N) $(DOCS_BUILD)/index.html\n"

docs-clean: ## Remove o build de documentação
	rm -rf docs/_build
	@printf "$(Y)==> docs/_build removido.$(N)\n"
