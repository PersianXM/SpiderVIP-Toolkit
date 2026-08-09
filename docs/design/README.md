# SpiderVIP Console — Design system

Imported design source-of-truth for redesigning the Digigo-style Console / Frequency / Channels UI.

**Live CSS tokens today:** `spidervip/console/static/theme.css`  
**Cursor rule:** [`.cursor/rules/dashboard-design.mdc`](../../.cursor/rules/dashboard-design.mdc)

## Documents

| File | Role |
|---|---|
| [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md) | Palette, type, spacing, components, tokens |
| [`UI_ART_DIRECTION.md`](UI_ART_DIRECTION.md) | Art direction, composition, motion, anti-patterns |
| [`CURSOR_IMPLEMENTATION_PROMPT.md`](CURSOR_IMPLEMENTATION_PROMPT.md) | Implementation prompt for agents / redesign sessions |
| [`DESIGN.md`](DESIGN.md) | Current Digigo Console token snapshot (pre-redesign reference) |

## Source import

Copied from local `G:\design` into this folder (`.md`) and `.cursor/rules/` (`.mdc`). After verifying these paths in git, the original `G:\design` folder may be deleted.

## Redesign guardrails

- Keep existing element IDs, API routes, and backend contracts unless the task explicitly changes them.
- Prefer updating `theme.css` + static HTML/CSS/JS under `spidervip/console`, `spidervip/channels/static`, and `spidervip/frequency/templates`.
- Recoverable Digigo UI backup: branch `backup/ui-before-design-docs-redesign`, tag `ui-digigo-backup-20260809`.
