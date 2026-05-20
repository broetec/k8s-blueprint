# Scripts de inventário

A lógica reutilizável vive em **`app/inventory/`** (pacote Python instalado com `uv sync`).

Este diretório documenta o fluxo; a CLI oficial é:

```bash
uv run python -m app.inventory.cli list
uv run python -m app.inventory.cli show broetec-core
uv run python -m app.inventory.cli generate --all
uv run k8s-blueprint-inventory generate -o broetec-core
```

## Fonte de verdade

| Ficheiro | Função |
|----------|--------|
| `provisioning/inventory/manifest.yml` | Overlays e VMs versionados |
| `env/.env` | `OVERLAY`, `VM_NAME`, `VM_IP` (sobrescreve o overlay ativo) |
| `provisioning/inventory/_shared/group_vars/all.yml` | Variáveis Ansible partilhadas |

Cada overlay (`broetec-core`, etc.) contém `hosts.ini` **gerado** e `group_vars` → symlink para `_shared`.

## Make

```bash
make inventory          # gera todos os overlays
make inventory OVERLAY=broetec-storage   # só um
make up                 # gera o overlay ativo e provisiona
make up-lab             # sobe core + storage + monitor
```

## Futuro (TUI)

Importar `app.inventory.InventoryGenerator` e `InventoryManifest` num wizard `curses` / `rich` / `textual` sem duplicar regras.
