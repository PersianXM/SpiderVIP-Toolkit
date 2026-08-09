---
name: SpiderVIP Console
description: Neo-brutal / Neo-Memphis operational toolkit UI for satellite receiver ops
colors:
  page: "#F7F5EE"
  beige: "#EEEDE6"
  white: "#FFFEF9"
  ink: "#111426"
  navy: "#111426"
  muted: "#666978"
  lime: "#C5F238"
  orange: "#FF6418"
  sky: "#58A8F5"
  yellow: "#F7C84B"
  danger: "#E84A4A"
  ok: "#75C943"
  warn: "#F7C84B"
  line: "#111426"
  soft-danger: "#FFE0D6"
  soft-warn: "#F7C84B"
  soft-orange: "#FFE0D6"
  soft-rose: "#FFE4E8"
  info-ink: "#1D6FA5"
typography:
  display:
    fontFamily: "Space Grotesk, Vazirmatn, Segoe UI, system-ui, sans-serif"
    fontSize: "2rem"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Space Grotesk, Vazirmatn, Segoe UI, system-ui, sans-serif"
    fontSize: "1.35rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Vazirmatn, Inter, Segoe UI, system-ui, sans-serif"
    fontSize: "0.95rem"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "normal"
  small:
    fontFamily: "Vazirmatn, Inter, Segoe UI, system-ui, sans-serif"
    fontSize: "0.85rem"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "normal"
  caption:
    fontFamily: "Vazirmatn, Inter, Segoe UI, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "normal"
rounded:
  xs: "6px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
  pill: "999px"
spacing:
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
components:
  card:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "24px 26px"
  button-primary:
    backgroundColor: "{colors.lime}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "12px 20px"
  button-accent:
    backgroundColor: "{colors.orange}"
    textColor: "{colors.white}"
    rounded: "{rounded.md}"
    padding: "12px 20px"
  header-bar:
    backgroundColor: "{colors.navy}"
    textColor: "{colors.white}"
    rounded: "{rounded.lg}"
    padding: "14px 20px"
---

# Design System — SpiderVIP Console

> Canonical location: `docs/design/`. Index: [`README.md`](README.md). Broader visual system: [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md) · [`UI_ART_DIRECTION.md`](UI_ART_DIRECTION.md).
> On conflict, `DESIGN_SYSTEM.md` / `UI_ART_DIRECTION.md` win; live tokens in `theme.css`.

## Overview

Operate-mode UI for a satellite receiver toolkit: cream canvas, strong ink outlines, Space Grotesk + Vazirmatn/Inter, lime / orange / blue Memphis accents, controlled geometric decoration, hard offset shadows. Functional restraint — denser controls, real task copy, no fake marketplace stats.

Shared tokens live in `spidervip/console/static/theme.css` (served at `/static/console/theme.css`). Frequency and Channels embed the same token block for standalone runs; Console injects the shared stylesheet when modules are mounted.

## Colors

| Role | Token | Hex | Use |
|------|-------|-----|-----|
| Page | `--sv-page` | `#F7F5EE` | App background |
| Beige | `--sv-beige` | `#EEEDE6` | Secondary panels, muted cards |
| Surface | `--sv-white` | `#FFFEF9` | Cards / inputs |
| Ink | `--sv-ink` | `#111426` | Text, borders |
| Navy | `--sv-navy` | `#111426` | Header bar |
| Lime | `--sv-lime` | `#C5F238` | Frequency accent, primary CTAs |
| Orange | `--sv-orange` | `#FF6418` | Channels accent, strong actions |
| Blue | `--sv-sky` | `#58A8F5` | Info chips, secondary accent |
| Yellow | `--sv-yellow` | `#F7C84B` | Warnings / checking |
| Muted | `--sv-muted` | `#666978` | Secondary copy |

## Typography

- **Display / headings:** Space Grotesk + Vazirmatn (Persian)
- **Body / UI:** Vazirmatn first for RTL Console & Frequency; Inter for Channels EN
- Prefer design-system type scale; keep dense panels readable

## Layout

- Console home: dark header → asymmetric hero → connection card → two varied module cards (Frequency lime, Channels blue)
- Frequency: RTL stepper + progressive cards
- Channels: three-column operate grid (Channels / Favorites / Ops) with accent strips
- Max content widths: Console ~1080px, Frequency ~1040px, Channels ~1400px

## Elevation & Depth

- Prefer **1–2px solid ink borders** over soft shadows
- Hard offset shadow (`4px 4px 0` ink) on important interactive elements
- No glassmorphism / glow halos as decoration

## Shapes

- Cards: `--sv-radius-lg` / `--sv-radius-xl` (16–20px)
- Inputs/buttons: 8–12px (geometric, not soft marketplace pills for primary)
- Status: pill tags with ink outline
- Controlled geometric decorations (cube, circle, capsule, dots) — never in dense tables

## Components

- **Header:** navy bar, brand left, connection status pill right
- **Card:** surface fill, strong border, geometric radius
- **Primary button:** lime fill, ink text, strong border
- **Accent button:** orange fill (Apply / strong actions)
- **Ghost:** surface, strong border
- **Focus:** 3px blue ring outside border; respect `prefers-reduced-motion`

## Do's and Don'ts

**Do** keep Persian RTL on Console/Frequency; keep engineering copy factual.  
**Do** reuse the same border weight and radius across all three surfaces.  
**Don't** invent marketplace stats or decorative hero illustrations that claim product metrics.  
**Don't** soft-gradient dark-mode chrome or purple neon — that is the discarded prior Console look.  
**Don't** break mount injection, credential hiding under Console, or existing element IDs.
