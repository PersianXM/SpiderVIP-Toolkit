---
name: SpiderVIP Console
description: Neo-brutalist Digigo-inspired toolkit UI for satellite receiver ops
colors:
  page: "#FAFAF7"
  beige: "#F0F0E8"
  white: "#FFFFFF"
  ink: "#0B1220"
  navy: "#121A2A"
  muted: "#4A5568"
  lime: "#C1E152"
  orange: "#FF6B35"
  sky: "#89CFF0"
  danger: "#E11D48"
  ok: "#15803D"
  warn: "#CA8A04"
  line: "#0B1220"
  soft-danger: "#FFE4E0"
  soft-warn: "#FFF3BF"
  soft-orange: "#FFE4DC"
  soft-rose: "#FFE4E8"
  info-ink: "#1D6FA5"
typography:
  display:
    fontFamily: "Sora, Vazirmatn, Segoe UI, system-ui, sans-serif"
    fontSize: "2rem"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Sora, Vazirmatn, Segoe UI, system-ui, sans-serif"
    fontSize: "1.35rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Vazirmatn, Sora, Segoe UI, system-ui, sans-serif"
    fontSize: "0.95rem"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "normal"
  small:
    fontFamily: "Vazirmatn, Sora, Segoe UI, system-ui, sans-serif"
    fontSize: "0.85rem"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "normal"
  caption:
    fontFamily: "Vazirmatn, Sora, Segoe UI, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "normal"
rounded:
  xs: "6px"
  sm: "12px"
  md: "18px"
  lg: "26px"
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
    rounded: "{rounded.pill}"
    padding: "12px 20px"
  button-accent:
    backgroundColor: "{colors.orange}"
    textColor: "{colors.white}"
    rounded: "{rounded.pill}"
    padding: "12px 20px"
  header-bar:
    backgroundColor: "{colors.navy}"
    textColor: "{colors.white}"
    rounded: "{rounded.lg}"
    padding: "14px 20px"
---

# Design System — SpiderVIP Console

> Canonical location: `docs/design/`. Index: [`README.md`](README.md). Broader visual system: [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md) · [`UI_ART_DIRECTION.md`](UI_ART_DIRECTION.md).

## Overview

Operate-mode UI for a satellite receiver toolkit, dressed in Digigo-like neo-brutalism: clean off-white page, large rounded cards, thick solid black outlines, high-contrast lime / orange / sky accents, dark notched header. Playful geometry without toyish chrome — denser controls, real task copy, no fake marketplace stats.

Shared tokens live in `spidervip/console/static/theme.css` (served at `/static/console/theme.css`). Frequency and Channels embed the same token block for standalone runs; Console injects the shared stylesheet when modules are mounted.

## Colors

| Role | Token | Hex | Use |
|------|-------|-----|-----|
| Page | `--sv-page` | `#FAFAF7` | App background |
| Beige | `--sv-beige` | `#F0F0E8` | Secondary panels, muted cards |
| Ink | `--sv-ink` | `#0B1220` | Text, borders |
| Navy | `--sv-navy` | `#121A2A` | Header bar |
| Lime | `--sv-lime` | `#C1E152` | Frequency accent, primary CTAs |
| Orange | `--sv-orange` | `#FF6B35` | Channels accent, strong actions |
| Sky | `--sv-sky` | `#89CFF0` | Info chips, secondary accent |
| Muted | `--sv-muted` | `#4A5568` | Secondary copy |

## Typography

- **Display / headings:** Sora (geometric Latin) + Vazirmatn (Persian)
- **Body / UI:** Vazirmatn first for RTL Console & Frequency; Sora supports Channels EN
- Fixed rem scale (~1.15–1.2 steps); no fluid display type in dense panels

## Layout

- Console home: dark header → connection card → two module cards (Frequency lime, Channels orange/sky)
- Frequency: RTL stepper + progressive cards
- Channels: three-column operate grid (Channels / Favorites / Ops)
- Max content widths: Console ~960px, Frequency ~1040px, Channels ~1400px

## Elevation & Depth

- Prefer **thick 2–3px solid ink borders** over soft shadows
- Optional hard offset shadow (`4px 4px 0` ink) on hover for cards/buttons only
- No glassmorphism / glow halos as decoration

## Shapes

- Cards: `--sv-radius-lg` (~26px)
- Inputs/buttons: 12–18px or full pill for primary actions
- Icon buttons: circular with thick border
- Status: pill tags with ink outline

## Components

- **Header:** navy bar, brand left, connection status pill right (notched/tab feel OK)
- **Card:** white/beige fill, thick border, large radius
- **Primary button:** lime fill, ink text, thick border
- **Accent button:** orange fill (Apply / strong actions)
- **Ghost:** white/beige, thick border
- **Focus:** 3px sky or lime ring outside border; respect `prefers-reduced-motion`

## Do's and Don'ts

**Do** keep Persian RTL on Console/Frequency; keep engineering copy factual.  
**Do** reuse the same border weight and radius across all three surfaces.  
**Don't** invent marketplace stats or decorative hero illustrations that claim product metrics.  
**Don't** soft-gradient dark-mode chrome or purple neon — that is the discarded prior Console look.  
**Don't** break mount injection, credential hiding under Console, or existing element IDs.
