# Design documentation

Visual language and UI guidance for SpiderVIP Console, Frequency Manager, and Channel & Favorite Manager.

**Live token source:** [`spidervip/console/static/theme.css`](../../spidervip/console/static/theme.css) (served as `/static/console/theme.css`). Prefer this file over prose when hex values or CSS variables disagree.

## Documents

| Doc | Purpose |
|---|---|
| [`DESIGN.md`](DESIGN.md) | SpiderVIP Console design notes (Digigo / neo-brutalist operate UI, product-specific tokens & layout) |
| [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md) | Operational dashboard design system (tokens, components, decoration, motion) |
| [`UI_ART_DIRECTION.md`](UI_ART_DIRECTION.md) | Art direction — composition, density, rhythm, QA checklist |
| [`CURSOR_IMPLEMENTATION_PROMPT.md`](CURSOR_IMPLEMENTATION_PROMPT.md) | Prompt for Cursor when implementing or refactoring dashboard UI |

## Cursor rules

Agent UI rules: [`.cursor/rules/spidervip-ui.mdc`](../../.cursor/rules/spidervip-ui.mdc) (scoped to console / frequency / channels static UI paths).
