# Operational Dashboard --- Design System

## 1. Purpose

This document is the visual and component source of truth for the
operational dashboard.

The product is a real operational application, not a marketing page or
visual concept. Functionality, information hierarchy, readability,
accessibility, and interaction clarity always take priority over
decoration.

The visual identity is based on:

-   Modern Neo-Brutalism
-   Neo-Memphis aesthetics
-   Geometric editorial design
-   Modular asymmetric composition
-   Bold geometric typography
-   Flat + subtle 3D geometric illustration
-   Controlled visual randomness
-   Subtle ambient motion

Do not copy the supplied reference layout. Extract and reuse its visual
language.

------------------------------------------------------------------------

## 2. Core Design Principles

1.  **Information first** --- operational data must always dominate
    decorative content.
2.  **Strong visual identity** --- the dashboard must not resemble a
    generic SaaS/admin template.
3.  **Controlled variation** --- components share the same system but
    should not all look identical.
4.  **Intentional imperfection** --- geometric accents may be irregular,
    rotated, or partially overlapping, but never chaotic.
5.  **Editorial composition** --- use visual weight, whitespace, and
    asymmetric modules to create rhythm.
6.  **Functional restraint** --- decoration must never reduce usability.
7.  **Reusable architecture** --- visual rules must be encoded as
    reusable tokens and components.

------------------------------------------------------------------------

## 3. Color Tokens

### Base

``` css
--color-background: #F7F5EE;
--color-surface: #FFFEF9;
--color-surface-muted: #EEEDE6;
--color-ink: #111426;
--color-ink-secondary: #303347;
--color-ink-muted: #666978;
--color-border: #111426;
```

### Accent palette

``` css
--color-lime: #C5F238;
--color-orange: #FF6418;
--color-blue: #58A8F5;
--color-yellow: #F7C84B;
```

### Semantic colors

Use semantic colors only when required by application meaning. They
should remain visually compatible with the main palette.

``` css
--color-success: #75C943;
--color-warning: #F7C84B;
--color-error: #E84A4A;
--color-info: #58A8F5;
```

### Color rules

-   Cream/off-white is the dominant canvas.
-   Deep navy/near-black is the structural color.
-   Lime, orange, and blue are accent colors.
-   Do not use all accent colors inside one small component.
-   Use large accent surfaces selectively.
-   Always maintain adequate text contrast.
-   Do not communicate status through color alone.

------------------------------------------------------------------------

## 4. Typography Tokens

Use a bold geometric sans-serif for display typography and a clean
modern sans-serif for functional UI.

Recommended families:

-   Display: Space Grotesk, Sora, Outfit, or equivalent geometric
    sans-serif.
-   UI/body: Inter, Geist, IBM Plex Sans, or equivalent.

Example tokens:

``` css
--font-display: "Space Grotesk", sans-serif;
--font-ui: "Inter", sans-serif;

--text-display: clamp(2.5rem, 5vw, 5rem);
--text-h1: clamp(2rem, 3.5vw, 3.5rem);
--text-h2: clamp(1.5rem, 2.5vw, 2.25rem);
--text-h3: 1.25rem;
--text-body: 0.95rem;
--text-small: 0.8rem;
--text-micro: 0.68rem;
```

Large KPI numbers should use the display font and strong weight.

Do not use decorative fonts that reduce operational readability.

------------------------------------------------------------------------

## 5. Spacing

Use a 4px base scale:

``` css
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-5: 20px;
--space-6: 24px;
--space-8: 32px;
--space-10: 40px;
--space-12: 48px;
--space-16: 64px;
--space-20: 80px;
```

Prefer consistent spacing tokens instead of arbitrary values.

------------------------------------------------------------------------

## 6. Borders

The reference style relies heavily on strong structural outlines.

``` css
--border-thin: 1px solid var(--color-border);
--border-strong: 2px solid var(--color-border);
```

Use strong borders for:

-   Main cards
-   Primary buttons
-   Important containers
-   Structural separators

Do not outline every tiny element.

------------------------------------------------------------------------

## 7. Radius

``` css
--radius-sm: 8px;
--radius-md: 12px;
--radius-lg: 16px;
--radius-xl: 20px;
--radius-pill: 999px;
```

Use rounded corners selectively. The interface should remain geometric
rather than overly soft.

------------------------------------------------------------------------

## 8. Shadows

Prefer flat surfaces and restrained depth.

``` css
--shadow-hard: 4px 4px 0 var(--color-ink);
--shadow-soft: 0 4px 18px rgba(17, 20, 38, 0.08);
```

Hard offset shadows may be used for important interactive elements.

Avoid large blurred SaaS-style shadows.

------------------------------------------------------------------------

## 9. Layout

Use a modular asymmetric grid.

Do not create repetitive rows of identical cards.

Use combinations of:

-   Large feature panels
-   KPI blocks
-   Medium cards
-   Charts
-   Tables
-   Activity panels
-   Status panels
-   Action panels

The underlying grid must remain consistent even when the composition
feels organic.

------------------------------------------------------------------------

## 10. Component Architecture

Create reusable components for:

-   AppShell
-   Sidebar
-   TopBar
-   PageHeader
-   KPI
-   Card
-   ChartCard
-   TableCard
-   ActivityFeed
-   StatusCard
-   AlertCard
-   ActionCard
-   Badge
-   Button
-   Tabs
-   Search
-   Filter
-   Pagination
-   EmptyState
-   GeometricDecoration

Each component should have controlled variants instead of one-off
styling.

------------------------------------------------------------------------

## 11. Card Variants

Supported visual variants:

``` text
default
minimal
lime
orange
blue
dark
featured
```

Cards should share:

-   Border language
-   Spacing system
-   Typography hierarchy
-   Radius
-   Interaction behavior

But may vary in composition.

------------------------------------------------------------------------

## 12. Button System

Variants:

``` text
primary
secondary
accent-lime
accent-orange
accent-blue
ghost
danger
```

States:

``` text
default
hover
active
focus
disabled
loading
success
error
```

Use tactile geometric feedback such as:

-   small translation
-   hard-shadow shift
-   border change
-   subtle background transition

Avoid generic oversized SaaS animations.

------------------------------------------------------------------------

## 13. Data Visualization

Charts should use the dashboard palette sparingly.

Rules:

-   Minimal grid lines
-   Strong readable labels
-   Limited series colors
-   Clear hierarchy
-   No decorative chart clutter
-   Consistent typography
-   Responsive behavior

Charts are operational components and must remain readable before they
become decorative.

------------------------------------------------------------------------

## 14. Tables

Tables should prioritize:

-   Column hierarchy
-   Readability
-   Sorting
-   Filtering
-   Status indicators
-   Row hover
-   Pagination
-   Keyboard accessibility

Avoid placing decorative objects inside dense data regions.

------------------------------------------------------------------------

# 15. Geometric Decoration System

Decorative primitives:

``` text
Square
Rectangle
Circle
HalfCircle
Capsule
Arc
OutlineSquare
OutlineCircle
Line
Dots
Grid
Cube
ExtrudedCube
GeometricFragment
```

Every decoration should support:

``` text
type
size
color
rotation
opacity
position
zIndex
animation
delay
```

These should be implemented as reusable components.

------------------------------------------------------------------------

## 16. Decoration Density

Use this approximate distribution:

-   35% of cards: no decoration
-   40%: one decoration
-   20%: two decorations
-   5%: three to five decorations in large featured areas

Never decorate every card.

Never decorate every corner.

Never repeat the exact same pattern in adjacent cards.

------------------------------------------------------------------------

## 17. Context-Aware Randomization

Randomness must be constrained by the component.

For each decorated component:

1.  Determine component importance.
2.  Determine available whitespace.
3.  Determine decoration density.
4.  Select compatible geometry.
5.  Select compatible color.
6.  Select position.
7.  Select rotation.
8.  Select animation.
9.  Validate collisions.
10. Render.

Decoration must never overlap:

-   Important text
-   Buttons
-   Inputs
-   Tables
-   Charts
-   Navigation
-   Alerts
-   Interactive targets

The output should look art-directed rather than procedurally chaotic.

------------------------------------------------------------------------

## 18. Decoration Positioning

Allowed placement zones:

``` text
top-left
top-right
bottom-left
bottom-right
edge-top
edge-right
edge-bottom
edge-left
between-sections
floating-near-content
```

Some objects may slightly cross a card boundary.

Some may be partially clipped by a parent container.

Some may appear behind a card.

Use z-index intentionally.

------------------------------------------------------------------------

## 19. Decoration Color Compatibility

Examples:

Cream card: - lime - orange - blue - navy outline

Lime card: - navy - orange - blue

Orange card: - navy - lime - blue

Blue card: - navy - lime - orange

Dark card: - lime - orange - blue

Do not use low-contrast decorative combinations.

------------------------------------------------------------------------

## 20. Decoration Rotation

Use restrained rotations:

``` text
-12deg
-8deg
-4deg
0deg
4deg
8deg
12deg
```

Do not rotate everything.

------------------------------------------------------------------------

# 21. Animation Tokens

Interactive motion:

``` css
--motion-fast: 180ms;
--motion-normal: 300ms;
--motion-slow: 500ms;
```

Ambient motion:

``` css
--motion-float: 6s;
--motion-drift: 9s;
--motion-rotate: 12s;
--motion-pulse: 8s;
```

Ambient animation must be subtle and use smooth easing.

Do not synchronize all decorative objects.

Use different durations and delays.

------------------------------------------------------------------------

## 22. Animation Variants

``` text
none
float
drift
rotate
pulse
orbit
micro-shift
```

Examples:

-   Cube: slow float
-   Circle: subtle drift
-   Outline square: slow rotation
-   Dot cluster: micro-shift
-   Arc: subtle pulse

The user should feel that the dashboard is alive without the animation
becoming a focal point.

------------------------------------------------------------------------

## 23. Accessibility Motion Rule

Respect:

``` css
@media (prefers-reduced-motion: reduce)
```

When reduced motion is enabled:

-   Disable ambient floating
-   Disable rotation
-   Disable orbit
-   Minimize transitions
-   Preserve the visual composition

------------------------------------------------------------------------

# 24. Responsive Rules

Desktop: - Full decoration system - Asymmetric composition - Large
visual hierarchy

Tablet: - Reduce decoration density to approximately 60--70% - Simplify
overlaps - Preserve hierarchy

Mobile: - Reduce decoration density to approximately 25--40% - Remove
complex overlaps - Reduce animation - Never create horizontal overflow -
Prioritize operational content

------------------------------------------------------------------------

# 25. Accessibility

Ensure:

-   WCAG-conscious contrast
-   Keyboard focus
-   Visible focus states
-   Semantic controls
-   Screen-reader-friendly labels
-   Color-independent status communication
-   Reduced-motion support

Decorative elements must not be interpreted as interactive controls.

------------------------------------------------------------------------

# 26. Source of Truth Rule

This document is the source of truth for visual decisions.

When implementing a new page or component:

1.  Reuse existing tokens.
2.  Reuse existing components.
3.  Add a new variant only when necessary.
4.  Do not introduce arbitrary colors.
5.  Do not introduce arbitrary radii.
6.  Do not introduce unrelated animation styles.
7.  Do not create one-off decorative geometry unless it becomes part of
    the system.
