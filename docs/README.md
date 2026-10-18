# ffxivpp Documentation

Design documents by area. Implementation plans live in `../plans/`.

| Doc | Area |
|-----|------|
| [architecture.md](architecture.md) | System overview, services, storage, deployment, FastAPI target state |
| [questboard.md](questboard.md) | Quest model: trees, pledges, turn-ins, deadlines, reminders, permissions |
| [surfaces.md](surfaces.md) | Web UI and Discord parity, sync rules between the two |
| [integrations-wiki-tree.md](integrations-wiki-tree.md) | consolegameswiki recipe data, caching, patch detection, capped-resource flags |
| [integrations-voyages.md](integrations-voyages.md) | Sea/airship voyage tracking, static loot data, voyage-linked quests |
| [integrations-chest-plugin.md](integrations-chest-plugin.md) | FC chest visibility: Allagan interim flow + Dalamud mini-plugin experiment |
| [interop-teamcraft.md](interop-teamcraft.md) | Teamcraft/Artisan link-out and list import/export |
| [maintenance.md](maintenance.md) | Party planner maintenance mode, TODO.md dispositions, future areas |
| [trainer.md](trainer.md) | Keybind trainer: browser-side files, optional account save, server surface |
| [trainer-data-formats.md](trainer-data-formats.md) | Verified KEYBIND.DAT / HOTBAR.DAT formats and key ids |

## Status

- Questboard: **design agreed 2026-08**, see docs, implementation not started.
- Party planner (compute, home-channel embed): shipped, frozen in maintenance mode.
- Keybind trainer: shipped at `/trainer/`; browser-only by default, optional Discord account save.
