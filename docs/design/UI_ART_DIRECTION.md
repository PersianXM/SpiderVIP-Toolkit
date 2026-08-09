# Operational Dashboard --- UI Art Direction

## 1. Purpose

This document defines how the dashboard should look and feel when the
Design System is applied.

The supplied reference image is inspiration only. Do not reproduce its
exact layout, content, illustration, or composition.

The goal is to create a new operational interface that inherits the same
visual DNA.

------------------------------------------------------------------------

## 2. Visual DNA

The target visual language combines:

-   Neo-Brutalist structure
-   Neo-Memphis geometry
-   Editorial layout
-   Bold typography
-   Vibrant color blocking
-   Cream canvas
-   Strong dark outlines
-   Playful geometric objects
-   Subtle pseudo-3D forms
-   Controlled asymmetry
-   Ambient micro-animation

The interface should feel like a premium operational product with a
strong art direction.

------------------------------------------------------------------------

## 3. Functional Priority

The dashboard is not a poster.

The following hierarchy must always remain true:

``` text
Operational data
      ↓
User actions
      ↓
Navigation
      ↓
Status
      ↓
Visualization
      ↓
Decoration
```

If a decorative element competes with information, remove or reduce the
decoration.

------------------------------------------------------------------------

## 4. Composition

Use an asymmetric editorial grid.

Avoid:

``` text
[Card] [Card] [Card]
[Card] [Card] [Card]
[Card] [Card] [Card]
```

Prefer:

``` text
[      Large Feature      ] [ KPI ]
[      Large Feature      ] [ KPI ]
[ Chart ] [ Chart ] [Activity]
[             Table             ]
```

The exact structure must be determined by the operational requirements.

Vary visual weight.

Allow large quiet areas.

Use color blocks to create visual anchors.

------------------------------------------------------------------------

## 5. Geometric Personality

The reference image uses geometric objects as a visual signature.

Replicate the PRINCIPLE, not the exact objects.

Use a family of:

-   Cubes
-   Squares
-   Circles
-   Half-circles
-   Arcs
-   Capsules
-   Dots
-   Thin lines
-   Small grids
-   Extruded blocks

These elements should recur throughout the application.

------------------------------------------------------------------------

## 6. Controlled Randomness

The interface should contain small geometric details that appear organic
and varied.

The placement should feel random to the user but remain constrained by
design rules.

### Good

A KPI card has a small lime cube partially outside its upper-right
corner.

A different card has a tiny orange circle near the lower-left corner.

A large chart panel has two subtle geometric elements in unused
whitespace.

A dense table has no decoration.

### Bad

Every card has two shapes.

Every shape is in the top-right corner.

Every shape has the same size.

Every card has the same color combination.

Decoration overlaps text.

The page becomes visually noisy.

------------------------------------------------------------------------

## 7. Decoration Density

Use an intentionally uneven distribution:

``` text
35% — none
40% — one
20% — two
5%  — three to five
```

This creates visual rhythm.

The absence of decoration is also a design decision.

------------------------------------------------------------------------

## 8. Micro-Composition Example

A card can behave like a miniature composition:

``` text
┌──────────────────────────────────────┐
│                              ◇       │
│                                      │
│  SYSTEM STATUS                       │
│                                      │
│  All systems operational             │
│                                      │
│  99.98% uptime                       │
│                                      │
│                         ●            │
└──────────────────────────────────────┘
```

The geometric elements are secondary.

The content remains the visual anchor.

------------------------------------------------------------------------

## 9. Layering

Use subtle depth:

``` text
Background
  ↓
Card
  ↓
Content
  ↓
Illustration
  ↓
Decorative geometry
  ↓
Ambient floating elements
```

Some geometric objects may:

-   overlap the card boundary
-   sit partially behind a card
-   appear slightly above the surface
-   be clipped by the container

Use z-index deliberately.

------------------------------------------------------------------------

## 10. Animation Philosophy

Animation is ambient, not performative.

Good:

-   Slow floating cube
-   Gentle circle drift
-   10-second rotation
-   Subtle pulse
-   Tiny position change

Bad:

-   Fast bouncing
-   Flashing
-   Large scaling
-   Constant parallax
-   Excessive hover effects
-   All decorations moving together

Animation should be noticed subconsciously.

------------------------------------------------------------------------

## 11. Visual Rhythm

Across a page, alternate visual intensity:

``` text
Bold → Quiet → Bold → Quiet
Large → Small → Medium → Large
Color → Neutral → Color → Neutral
Dense → Open → Dense
```

Do not make every section compete for attention.

------------------------------------------------------------------------

## 12. KPI Art Direction

KPI blocks should have strong typography.

Example hierarchy:

``` text
TOTAL REQUESTS

128,420

+12.8%

vs. previous period
```

The number should be visually dominant.

A small geometric element may sit near the edge, but must not compete
with the number.

------------------------------------------------------------------------

## 13. Chart Art Direction

Charts should feel integrated into the design system.

Use:

-   Strong titles
-   Minimal grid
-   Limited accent colors
-   Clear labels
-   Strong numerical hierarchy

Do not decorate chart plotting areas with unrelated geometry.

Decorations should remain in unused card space.

------------------------------------------------------------------------

## 14. Table Art Direction

Tables are high-density operational areas.

Therefore:

-   Keep them visually calm.
-   Use strong headers.
-   Use status badges.
-   Use subtle row interaction.
-   Avoid decorative objects inside rows.
-   If decoration exists, keep it outside the data region.

The table should feel like part of the same product, not like a
different UI library.

------------------------------------------------------------------------

## 15. Empty States

Empty states are a good location for more expressive geometric
composition.

Use:

-   2--4 geometric elements
-   One simple illustration
-   Short explanatory text
-   One clear action

Empty states can be more playful than dense operational areas.

------------------------------------------------------------------------

## 16. Alerts

Alerts must remain highly functional.

Use the established palette:

-   Blue = information
-   Lime/green = success
-   Yellow = warning
-   Orange/red = error

Decorative elements should be minimal around alerts.

Never make an alert look decorative enough to be mistaken for a
non-functional panel.

------------------------------------------------------------------------

## 17. Navigation

Navigation should be visually strong but restrained.

Use:

-   Deep navy structural color
-   Strong typography
-   Clear active state
-   Geometric separators
-   Minimal iconography

Avoid filling the navigation with decorative shapes.

------------------------------------------------------------------------

## 18. Empty Space

Whitespace is a first-class design element.

Do not attempt to fill every empty region.

Some areas should intentionally remain quiet.

Geometric decoration may occupy selected empty areas, but empty space
itself must remain part of the composition.

------------------------------------------------------------------------

## 19. Visual Contrast

Use contrast in three dimensions:

### Color contrast

Cream ↔ Navy Lime ↔ Navy Orange ↔ Navy Blue ↔ Navy

### Scale contrast

Large KPI ↔ small metadata

### Density contrast

Dense table ↔ open feature card

This creates hierarchy without relying on shadows.

------------------------------------------------------------------------

## 20. Art-Directed Randomization Algorithm

Conceptually use:

``` text
for each component:

    importance = determineImportance(component)

    whitespace = detectAvailableWhitespace(component)

    density = chooseDecorationDensity(importance, whitespace)

    if density == 0:
        return

    decoration = chooseCompatibleDecoration(component)

    color = chooseCompatibleColor(component)

    position = chooseSafePosition(whitespace)

    rotation = chooseSubtleRotation()

    animation = chooseAmbientAnimation()

    validateNoCollision()

    render()
```

This is a design behavior specification, not a requirement to expose an
algorithmic UI to users.

------------------------------------------------------------------------

## 21. Adjacency Rule

Never repeat identical decorative patterns in adjacent components.

For example, avoid:

``` text
Card A → lime cube top-right
Card B → lime cube top-right
Card C → lime cube top-right
```

Prefer:

``` text
Card A → lime cube
Card B → none
Card C → orange circle + blue line
Card D → outline square
```

------------------------------------------------------------------------

## 22. Color Rhythm

Avoid concentrating one accent color in one region.

For example:

``` text
Lime
Neutral
Blue
Neutral
Orange
Neutral
Lime
```

rather than:

``` text
Lime
Lime
Lime
Lime
```

The color system should feel balanced across the page.

------------------------------------------------------------------------

## 23. 3D Object Direction

Use pseudo-3D forms inspired by the reference.

Characteristics:

-   Simple geometry
-   Flat shading
-   Strong outline
-   Minimal perspective
-   No realistic material
-   No photorealism

A cube should look like a graphic design object, not a rendered game
asset.

------------------------------------------------------------------------

## 24. Interaction Art Direction

Interactive elements should feel tactile.

Example:

Default: flat button

Hover: slight movement + subtle shadow shift

Active: small pressed translation

Focus: clear high-contrast outline

This creates a physical graphic-design feel.

------------------------------------------------------------------------

## 25. Responsive Art Direction

### Desktop

Full composition.

Use:

-   asymmetric grid
-   decorative overlaps
-   subtle ambient motion
-   full color vocabulary

### Tablet

Simplify:

-   fewer decorations
-   fewer overlaps
-   slightly reduced typography scale

### Mobile

Prioritize:

-   content
-   navigation
-   actions
-   KPIs

Use decoration only as small accents.

Do not allow decorative elements to cause overflow.

------------------------------------------------------------------------

## 26. Quality Test

Before approving a screen, ask:

### Function

Can the user understand the operational information immediately?

### Hierarchy

Is the most important information visually dominant?

### Consistency

Does this screen clearly belong to the same product?

### Decoration

Would the screen still work if decorations were removed?

If no, the decoration is doing too much.

### Motion

Is the animation subtle enough to ignore?

### Randomness

Does the placement feel organic rather than repetitive?

### Density

Are dense areas calm and open areas expressive?

### Identity

Would the screen be recognizable without seeing the product logo?

If yes, the visual identity is working.

------------------------------------------------------------------------

## 27. Golden Rule

**Do not decorate the dashboard. Design the dashboard, then use
decoration to strengthen the composition.**

The geometric system is a supporting visual language, not the content.

The final result should feel:

``` text
Operational
+
Editorial
+
Geometric
+
Playful
+
Premium
+
Highly usable
```
